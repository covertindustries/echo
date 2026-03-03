"""
Tank AI — Raspberry Pi tank robot with vision and obstacle avoidance.

Runs a small tank that: detects objects (e.g. dog) with YOLO, records clips when
a dog is in scene, notifies via WhatsApp when a clip is saved, uses ultrasonic
for distance and auto-brake, and accepts WASD keyboard control.

Hardware: Raspberry Pi, GPIO motors, Picamera2, HC-SR04-style ultrasonic.
Run: source tankai/bin/activate && python3 tank_ai.py

Steps overview:
  - main(): 1) Config + dir  2) Headless?  3) Hardware  4) RecordingState
            5) Shutdown handler  6) Banner + run_main_loop()
  - run_main_loop() each frame: 1) Capture+flip  2) YOLO  3) Dog? Greet once
            4) Distance + auto-brake  5) Overlays  6) Recording + notify
            7) Display + key  8) Quit or apply_drive()
"""

import os
import shlex
import signal
import sys
import subprocess
import threading
import time
import wave
from datetime import datetime

import numpy as np

from dotenv import load_dotenv

# Load .env from script directory so it's found when run from any cwd (e.g. WhatsApp keys)
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

import cv2
from gpiozero import Motor, DistanceSensor
from picamera2 import Picamera2
from ultralytics import YOLO

from notifications.whatsapp import notify_recording_saved

# Optional: for hold-R voice recording and mic check
try:
    import sounddevice as sd
    _HAS_SOUNDDEVICE = True
except ImportError:
    _HAS_SOUNDDEVICE = False
try:
    from pynput import keyboard
    _HAS_PYNPUT = True
except ImportError:
    _HAS_PYNPUT = False


# -----------------------------------------------------------------------------
# MIC CHECK — whether we can record from a microphone
# -----------------------------------------------------------------------------
def is_mic_available(device=None) -> bool:
    """True if sounddevice sees an input device (microphone). Pass device index for USB mic."""
    if not _HAS_SOUNDDEVICE:
        return False
    try:
        if device is not None:
            dev = sd.query_devices(device)
            return dev.get("max_input_channels", 0) > 0
        default = sd.query_devices(kind="input")
        return default is not None and default.get("max_input_channels", 0) > 0
    except Exception:
        return False


# -----------------------------------------------------------------------------
# STEP 0: CONFIG — all tunable values in one place (see docs/IMPROVEMENTS.md)
# -----------------------------------------------------------------------------
# Every constant the rest of the program uses lives here. Change behavior by
# editing this class (e.g. STOP_DISTANCE_CM, YOLO_CONFIDENCE, DETECT_CLASS).

class Config:
    """
    Tunable settings for motors, detection, recording, and display.
    Used by main(), run_main_loop(), and helper functions.
    """

    # Motors (GPIO: left 24/23, right 5/6; speed 0–1)
    MOTOR_LEFT_FWD, MOTOR_LEFT_BWD = 24, 23
    MOTOR_RIGHT_FWD, MOTOR_RIGHT_BWD = 5, 6
    MAX_SPEED = 0.20
    TURN_SPEED = 0.15
    STOP_DISTANCE_CM = 15

    # Ultrasonic "eyes" (HC-SR04: echo, trigger; max_distance in meters)
    # Left eye (or single sensor)
    ULTRASONIC_ECHO, ULTRASONIC_TRIGGER = 22, 27
    ULTRASONIC_MAX_M = 4.0
    # Right eye: set to (echo, trigger) if you have a second sensor; else None to use same as left
    ULTRASONIC_RIGHT = None  # e.g. (24, 23) for second HC-SR04

    # Camera
    CAMERA_SIZE = (640, 480)
    CAMERA_FORMAT = "RGB888"
    CAMERA_FLIP = -1  # -1 = 180° (camera mounted upside down)

    # YOLO (yolov8n = nano, good for Pi)
    YOLO_MODEL = "yolov8n.pt"
    YOLO_IMGSZ = 320
    YOLO_CONFIDENCE = 0.4
    DETECT_CLASS = "dog"  # COCO class to trigger recording & greeting

    # Recording
    RECORDINGS_DIR = "recordings"
    RECORD_FPS = 10
    # Motion-triggered recording: frame diff mean above this => motion (0–255 scale)
    MOTION_DIFF_THRESHOLD = 18
    MOTION_RESIZE = (160, 120)  # smaller = faster; (width, height)
    # Proximity beep: beep when either eye closer than this (cm); beep rate increases as you get closer
    PROXIMITY_BEEP_CM = 25
    PROXIMITY_BEEP_ENABLED = True

    # Greeting (espeak) — USB speaker (card 3), amplified with sox for extra volume
    GREETING_PHRASE = "Hello Pepe"
    ALSA_CARD = "3"  # USB speaker (see cat /proc/asound/cards); None = default device
    GREETING_GAIN_DB = 10  # extra dB when using sox (espeak | sox gain | aplay); 0 = no sox

    # Voice recording (hold R): save to this dir; length = how long you hold R
    VOICE_RECORD_DIR = "recordings"
    # USB mics often need 48000 or 16000; 44100 can cause "Invalid sample rate"
    VOICE_SAMPLE_RATE = 48000
    VOICE_CHANNELS = 1
    # Input device for mic: 0 = USB mic (UACDemoV1.0 hw:2,0); None = system default
    VOICE_INPUT_DEVICE = 0


# -----------------------------------------------------------------------------
# VOICE RECORDING — hold R: record while key is held, save WAV when released
# -----------------------------------------------------------------------------
def _record_voice_thread(voice_state: dict, config: Config) -> None:
    """Background thread: record from default mic until voice_state['stop_flag'][0] is True, then save WAV."""
    if not _HAS_SOUNDDEVICE:
        voice_state["recording"] = False
        return
    stop_flag = voice_state["stop_flag"]
    chunks = []
    try:
        block_ms = 100  # Check stop flag every 100 ms
        block_frames = int(config.VOICE_SAMPLE_RATE * block_ms / 1000.0)
        device = getattr(config, "VOICE_INPUT_DEVICE", None)  # None = default; or USB mic index
        with sd.InputStream(
            device=device,
            samplerate=config.VOICE_SAMPLE_RATE,
            channels=config.VOICE_CHANNELS,
            dtype=np.int16,
            blocksize=block_frames,
        ) as stream:
            while not stop_flag[0]:
                chunk, _ = stream.read(block_frames)
                chunks.append(chunk)
        if chunks:
            os.makedirs(config.VOICE_RECORD_DIR, exist_ok=True)
            path = os.path.join(
                config.VOICE_RECORD_DIR,
                f"voice_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.wav",
            )
            data = np.concatenate(chunks, axis=0)
            with wave.open(path, "wb") as wf:
                wf.setnchannels(config.VOICE_CHANNELS)
                wf.setsampwidth(2)  # 16-bit
                wf.setframerate(config.VOICE_SAMPLE_RATE)
                wf.writeframes(data.tobytes())
            print(f"Voice saved: {path}")
    except Exception as e:
        print(f"Voice recording error: {e}")
    finally:
        voice_state["recording"] = False


def start_voice_recording(voice_state: dict, config: Config) -> None:
    """Start recording from mic (press R). Runs in a background thread."""
    if voice_state.get("recording"):
        return
    voice_state["recording"] = True
    voice_state["stop_flag"] = [False]
    t = threading.Thread(target=_record_voice_thread, args=(voice_state, config), daemon=True)
    t.start()


def stop_voice_recording(voice_state: dict) -> None:
    """Stop recording and save WAV (release R)."""
    if voice_state.get("stop_flag") is not None:
        voice_state["stop_flag"][0] = True


# -----------------------------------------------------------------------------
# STEP 0 (continued): RECORDING STATE — one object for "dog seen" + video writer
# -----------------------------------------------------------------------------
# Tracks: (1) whether we've already said "Hello Pepe" for the current dog
# appearance, and (2) the active VideoWriter and its path. Created in main(),
# passed into run_main_loop(), and closed on shutdown.

class RecordingState:
    """
    Holds state for dog detection and video recording.
    - dog_seen: True after we greet; reset when dog leaves frame.
    - _writer / _current_path: active recording; None when not recording.
    """

    def __init__(self, recordings_dir: str, record_fps: int):
        """Store where to save clips and at what FPS; start with no recording and dog not yet greeted."""
        self.recordings_dir = recordings_dir
        self.record_fps = record_fps
        self.dog_seen = False  # True after we say "Hello Pepe" for this dog appearance
        self._writer = None   # OpenCV VideoWriter when recording; None when idle
        self._current_path = None  # Path of the file we're writing to

    def start_recording(self, frame, filename: str) -> None:
        """Step: Start a new video file and set _writer + _current_path."""
        self._current_path = os.path.join(self.recordings_dir, filename)
        h, w = frame.shape[:2]  # Frame size for the video
        fourcc = cv2.VideoWriter_fourcc(*"MJPG")  # Codec that works well on Pi
        self._writer = cv2.VideoWriter(
            self._current_path, fourcc, self.record_fps, (w, h)
        )
        print(f"Recording: {self._current_path}")

    def write_frame(self, frame) -> None:
        """Step: Append one frame to the current recording; no-op if not recording."""
        if self._writer is not None:
            self._writer.write(frame)

    def stop_recording(self) -> str | None:
        """
        Step: Release the writer, clear state, return the saved file path (or None).
        Caller uses the path for WhatsApp notification.
        """
        if self._writer is None:
            return None
        path = self._current_path  # Save path before clearing so we can return it
        self._writer.release()     # Close the file so it's playable
        self._writer = None
        self._current_path = None
        return path

    @property
    def is_recording(self) -> bool:
        """True if we are currently writing frames to a file."""
        return self._writer is not None

    def close(self) -> None:
        """Step (shutdown): Release writer so we don't leave a file open on exit."""
        if self._writer is not None:
            self._writer.release()
            self._writer = None
            self._current_path = None


# -----------------------------------------------------------------------------
# STEP 1 (in loop): DETECTION — turn YOLO results into a yes/no "dog in frame"
# -----------------------------------------------------------------------------

def detect_dog_in_results(results, model, class_name: str = "dog") -> bool:
    """
    Step: Decide if any detection in this frame is the given class (e.g. 'dog').
    YOLO gives class indices; model.names maps index -> string name.
    Returns True if at least one detection matches; False otherwise or on parse error.
    """
    try:
        cls_tensor = results[0].boxes.cls  # Class index for each detected box
        if cls_tensor is None:
            return False
        # Convert to a list we can loop over (works for PyTorch tensor or numpy)
        if hasattr(cls_tensor, "cpu"):
            cls_arr = cls_tensor.cpu().numpy()
        elif hasattr(cls_tensor, "numpy"):
            cls_arr = cls_tensor.numpy()
        else:
            cls_arr = list(cls_tensor)
        for c in cls_arr:
            # model.names maps index (e.g. 16) to name (e.g. "dog")
            if model.names.get(int(c), "") == class_name:
                return True
        return False
    except (AttributeError, IndexError, TypeError):
        return False  # No box data or wrong shape -> assume no dog


def speak_phrase(config: Config, phrase: str) -> None:
    """Say a phrase on the configured ALSA card (e.g. USB speaker), with sox gain if set. Non-blocking."""
    try:
        card = getattr(config, "ALSA_CARD", None)
        gain_db = getattr(config, "GREETING_GAIN_DB", 0)
        if card and gain_db > 0:
            safe_phrase = shlex.quote(phrase)
            cmd = f"espeak -a 200 --stdout {safe_phrase} | sox -t wav - -t alsa hw:{card},0 gain {gain_db}"
            subprocess.Popen(cmd, shell=True)
        else:
            env = os.environ.copy()
            if card:
                env["ALSA_CARD"] = str(card)
            subprocess.Popen(["espeak", "-a", "200", phrase], env=env)
    except (FileNotFoundError, OSError):
        pass


def speak_dog_greeting(config: Config) -> None:
    """Step: Say the configured greeting once (e.g. 'Hello Pepe') on the USB speaker."""
    speak_phrase(config, getattr(config, "GREETING_PHRASE", "Hello Pepe"))


# -----------------------------------------------------------------------------
# MOTION DETECTION — frame diff to decide if scene changed (for motion recording)
# -----------------------------------------------------------------------------

def detect_motion(frame, prev_gray_small, config: Config) -> tuple[bool, np.ndarray]:
    """
    Compare current frame to previous (grayscale, resized). Return (motion_detected, next_prev).
    prev_gray_small: (H,W) from last call or None on first frame.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    small = cv2.resize(gray, config.MOTION_RESIZE)
    if prev_gray_small is None:
        return False, small
    diff = cv2.absdiff(prev_gray_small, small)
    mean_diff = float(np.mean(diff))
    motion = mean_diff > config.MOTION_DIFF_THRESHOLD
    return motion, small


# -----------------------------------------------------------------------------
# STEP 2 (in loop): OVERLAYS — draw distance and brake warning on the frame
# -----------------------------------------------------------------------------

def _radar_color(cm: float, stop_cm: float):
    """Green when far, yellow mid, red when close (for radar eyes)."""
    if cm >= stop_cm * 2:
        return (0, 255, 0)   # Green
    if cm >= stop_cm:
        return (0, 255, 255)  # Yellow
    return (0, 0, 255)       # Red


def draw_overlays(frame, left_cm: float, right_cm: float, stop_distance_cm: float) -> None:
    """Step: Draw radar-style two eyes (L/R distance) and 'AUTO BRAKE!' if too close. Modifies frame in-place."""
    h, w = frame.shape[:2]
    # Radar "two eyes" at top: two circles (left half, right half) with distance and color
    eye_radius = 28
    left_center = (w // 4, 50)
    right_center = (3 * w // 4, 50)
    for label, center, cm in [("L", left_center, left_cm), ("R", right_center, right_cm)]:
        color = _radar_color(cm, stop_distance_cm)
        cv2.circle(frame, center, eye_radius, color, 3)
        cv2.putText(frame, f"{cm:.0f}", (center[0] - 18, center[1] + 6),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
        cv2.putText(frame, label, (center[0] - 8, center[1] - eye_radius - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
    # Brake warning if either eye is too close
    if min(left_cm, right_cm) < stop_distance_cm:
        cv2.putText(frame, "AUTO BRAKE!", (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 3)


# -----------------------------------------------------------------------------
# SNAPSHOT — save single JPEG to recordings/ with timestamp
# -----------------------------------------------------------------------------

def save_snapshot(frame, recordings_dir: str) -> str | None:
    """Save current frame as JPEG; return path or None on failure. Frame is RGB (e.g. from YOLO plot)."""
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    name = f"snapshot_{timestamp}.jpg"
    path = os.path.join(recordings_dir, name)
    try:
        # OpenCV imwrite expects BGR; frame from camera/YOLO is often RGB
        bgr = cv2.cvtColor(frame, cv2.COLOR_RGB2BGR)
        if cv2.imwrite(path, bgr):
            print(f"Snapshot saved: {path}")
            return path
    except Exception:
        pass
    return None


# -----------------------------------------------------------------------------
# PROXIMITY BEEP — say "close" when either eye below threshold; rate increases when closer
# -----------------------------------------------------------------------------

def try_proximity_beep(closest_cm: float, config: Config, state: dict) -> None:
    """
    If closest_cm below PROXIMITY_BEEP_CM, speak "close" at a rate that increases as you get closer.
    state: dict with 'last_beep' (float, time.time()); mutated in place.
    """
    if not getattr(config, "PROXIMITY_BEEP_ENABLED", True):
        return
    threshold = getattr(config, "PROXIMITY_BEEP_CM", 25)
    if closest_cm >= threshold:
        return
    now = time.time()
    # Interval in sec: longer when just under threshold, shorter when very close (min 0.25s)
    ratio = max(0, closest_cm / threshold)
    interval = 0.25 + ratio * 0.75  # 0.25s at 0cm, 1.0s at threshold
    if now - state.get("last_beep", 0) >= interval:
        speak_phrase(config, "close")
        state["last_beep"] = now


# -----------------------------------------------------------------------------
# STEP 3 (in loop): RECORDING — start/continue/stop clip and notify when saved
# -----------------------------------------------------------------------------

def update_recording(
    state: RecordingState,
    dog_present: bool,
    motion_detected: bool,
    annotated_frame,
    config: Config,
) -> None:
    """
    Step: If dog or motion in frame, start recording (if not already) and write this frame.
    If both leave, stop recording, save path, and notify WhatsApp (background).
    Filename prefix is "dog_" or "motion_" depending on which triggered the start.
    """
    recording_active = dog_present or motion_detected
    if recording_active:
        if not state.is_recording:
            timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            prefix = "dog" if dog_present else "motion"
            state.start_recording(annotated_frame, f"{prefix}_{timestamp}.avi")
        state.write_frame(annotated_frame)
    elif state.is_recording:
        saved_path = state.stop_recording()
        print("Recording saved.")
        if saved_path:
            notify_recording_saved(saved_path)


# -----------------------------------------------------------------------------
# STEP 4 (in loop): DRIVE — map keyboard + distance to motor commands
# -----------------------------------------------------------------------------

def apply_drive(
    key: int,
    distance_cm: float,
    left_motor: Motor,
    right_motor: Motor,
    config: Config,
) -> None:
    """
    Step: Set motor speeds from key (W/S/A/D) and distance.
    Forward (W) only if distance >= STOP_DISTANCE_CM; else stop.
    No key or other key -> stop both motors.
    """
    stop = config.STOP_DISTANCE_CM
    if key == ord("w") and distance_cm >= stop:
        # Forward only when clear of obstacles
        left_motor.forward(config.MAX_SPEED)
        right_motor.forward(config.MAX_SPEED)
    elif key == ord("s"):
        left_motor.backward(config.MAX_SPEED)
        right_motor.backward(config.MAX_SPEED)
    elif key == ord("a"):
        # Turn left: left wheel back, right wheel forward
        left_motor.backward(config.TURN_SPEED)
        right_motor.forward(config.TURN_SPEED)
    elif key == ord("d"):
        # Turn right: left wheel forward, right wheel back
        left_motor.forward(config.TURN_SPEED)
        right_motor.backward(config.TURN_SPEED)
    else:
        # No key pressed or key not W/S/A/D -> stop so tank doesn't drift
        left_motor.stop()
        right_motor.stop()


# -----------------------------------------------------------------------------
# MAIN LOOP — pipeline runs every frame until Q or Ctrl+C
# -----------------------------------------------------------------------------
# Pipeline per frame:
#   1. Capture frame from camera and flip (camera is upside down).
#   2. Run YOLO to get detections and an annotated image.
#   3. Detect if 'dog' is in frame; if first time, speak greeting.
#   4. Read ultrasonic distance; if too close, stop motors and draw AUTO BRAKE.
#   5. Draw distance (and brake text) on the frame.
#   6. Update recording: start/continue/stop clip; notify WhatsApp when clip saved.
#   7. Show the frame (or sleep if headless) and read keyboard.
#   8. If Q, shutdown; else apply drive from key and distance.

def run_main_loop(
    picam2: Picamera2,
    model: YOLO,
    sensor_left: DistanceSensor,
    sensor_right: DistanceSensor,
    left_motor: Motor,
    right_motor: Motor,
    config: Config,
    state: RecordingState,
    headless: bool,
    shutdown_callback,
) -> None:
    """
    Run the per-frame pipeline until shutdown_callback() (Q or Ctrl+C).
    Each iteration: capture -> motion -> YOLO -> overlay -> record -> display -> drive.
    """
    motion_prev = None  # For motion detection (frame diff)
    proximity_state = {"last_beep": 0.0}  # Throttle proximity "close" beeps

    while True:
        # --- Step 1: Capture and flip ---
        frame = picam2.capture_array()  # Grab one frame from the camera
        frame = cv2.flip(frame, config.CAMERA_FLIP)  # Upside-down camera -> flip 180°

        # --- Step 1b: Motion detection (frame diff for motion-triggered recording) ---
        motion_detected, motion_prev = detect_motion(frame, motion_prev, config)

        # --- Step 2: YOLO detection and annotated image ---
        results = model(
            frame,
            imgsz=config.YOLO_IMGSZ,
            conf=config.YOLO_CONFIDENCE,
            verbose=False,
        )
        annotated_frame = results[0].plot()  # Draw boxes/labels on the frame for display

        # --- Step 3: Dog in frame? If first time this appearance, speak once ---
        dog_present = detect_dog_in_results(results, model, config.DETECT_CLASS)
        if dog_present and not state.dog_seen:
            speak_dog_greeting(config)  # "Hello Pepe" on USB speaker (non-blocking)
            state.dog_seen = True
        elif not dog_present and state.dog_seen:
            state.dog_seen = False  # Reset so we greet again next time dog appears

        # --- Step 4: Two "eyes" distance and auto-brake (stop if either side too close) ---
        left_cm = sensor_left.distance * 100
        right_cm = sensor_right.distance * 100 if sensor_right is not sensor_left else left_cm
        closest_cm = min(left_cm, right_cm)
        if closest_cm < config.STOP_DISTANCE_CM:
            left_motor.stop()
            right_motor.stop()
        draw_overlays(annotated_frame, left_cm, right_cm, config.STOP_DISTANCE_CM)

        # --- Step 4b: Proximity beep — "close" when either eye below threshold; faster when closer ---
        try_proximity_beep(closest_cm, config, proximity_state)

        # --- Step 5: Recording (dog or motion) — start/continue/stop; notify when saved ---
        update_recording(state, dog_present, motion_detected, annotated_frame, config)

        # --- Step 6: Display frame and read key (or sleep if headless) ---
        if headless:
            key = -1
            time.sleep(0.01)  # Avoid busy loop when there's no window
        else:
            cv2.imshow("Tank AI Vision", annotated_frame)
            key = cv2.waitKey(1) & 0xFF  # Non-blocking key read; 0xFF for cross-platform

        # --- Step 7: Quit on Q; G = say "Hi Human"; C = snapshot ---
        if key == ord("q"):
            shutdown_callback()
            return
        if key == ord("g"):
            speak_phrase(config, "Hi Human")
        if key == ord("c"):
            save_snapshot(annotated_frame, config.RECORDINGS_DIR)

        # --- Step 8: Apply drive from key and closest obstacle distance ---
        apply_drive(key, closest_cm, left_motor, right_motor, config)


def main() -> None:
    """
    Entry point: set up config, hardware, and state; register shutdown; run loop.
    Steps:
      1. Load config and create recordings dir.
      2. Detect headless (no DISPLAY or HEADLESS=1).
      3. Create motors, ultrasonic sensor, camera, YOLO model.
      4. Create RecordingState.
      5. Register shutdown handler (Ctrl+C) to stop motors, close recording, exit.
      6. Print banner and run the per-frame loop.
    """
    # --- Step 1: Config and recordings directory ---
    config = Config()
    os.makedirs(config.RECORDINGS_DIR, exist_ok=True)  # So we can save clips

    # --- Step 2: Headless if no display (e.g. SSH) or HEADLESS=1 ---
    headless = (
        os.environ.get("HEADLESS", "").strip() == "1"
        or not os.environ.get("DISPLAY", "").strip()
    )

    # --- Step 3: Hardware — motors, ultrasonic "eyes", camera, YOLO ---
    left_motor = Motor(config.MOTOR_LEFT_FWD, config.MOTOR_LEFT_BWD)
    right_motor = Motor(config.MOTOR_RIGHT_FWD, config.MOTOR_RIGHT_BWD)
    sensor_left = DistanceSensor(
        echo=config.ULTRASONIC_ECHO,
        trigger=config.ULTRASONIC_TRIGGER,
        max_distance=config.ULTRASONIC_MAX_M,
    )
    # Second "eye": use separate sensor if ULTRASONIC_RIGHT (echo, trigger) set; else same as left
    right_pins = getattr(config, "ULTRASONIC_RIGHT", None)
    if right_pins is not None:
        sensor_right = DistanceSensor(
            echo=right_pins[0],
            trigger=right_pins[1],
            max_distance=config.ULTRASONIC_MAX_M,
        )
    else:
        sensor_right = sensor_left
    picam2 = Picamera2()
    picam2.preview_configuration.main.size = config.CAMERA_SIZE
    picam2.preview_configuration.main.format = config.CAMERA_FORMAT
    picam2.configure("preview")
    picam2.start()
    model = YOLO(config.YOLO_MODEL)  # Load YOLO nano model for object detection

    # --- Step 4: Recording state (dog_seen + video writer) ---
    state = RecordingState(config.RECORDINGS_DIR, config.RECORD_FPS)

    # --- Step 5: Shutdown on Ctrl+C or Q — stop motors, release writer, close window ---
    def shutdown(sig=None, frame=None):
        left_motor.stop()
        right_motor.stop()
        state.close()  # Release video writer if we were recording
        if not headless:
            cv2.destroyAllWindows()
        print("\nShutdown complete.")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)  # Catch Ctrl+C

    # --- Step 5b: Hold R to record from mic (only if mic found and not headless) ---
    voice_state = {}
    mic_ok = is_mic_available(getattr(config, "VOICE_INPUT_DEVICE", None))
    if not mic_ok:
        print("(No mic found — install sounddevice and connect a mic for Hold R = record)")
    elif not headless and _HAS_PYNPUT:
        def on_press(key):
            try:
                if getattr(key, "char", None) and str(key.char).lower() == "r":
                    start_voice_recording(voice_state, config)
            except Exception:
                pass

        def on_release(key):
            try:
                if getattr(key, "char", None) and str(key.char).lower() == "r":
                    stop_voice_recording(voice_state)
            except Exception:
                pass

        _key_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        _key_listener.daemon = True
        _key_listener.start()

    # --- Step 6: Banner and run the per-frame pipeline ---
    print("\n--- TANK AI MODE STARTED ---")
    if headless:
        print("(headless — no display; detection, recording & notifications only)")
    else:
        print("W = Forward   S = Backward   A = Left   D = Right   G = Hi Human   Q = Quit")
        print("C = snapshot (JPEG)   Dog or motion → records to ./recordings/ (saved when clear)")
        if mic_ok and _HAS_PYNPUT:
            print("Hold R = record from mic (length = how long you hold)")
    print("----------------------------\n")

    run_main_loop(
        picam2, model, sensor_left, sensor_right, left_motor, right_motor,
        config, state, headless, shutdown,
    )


# -----------------------------------------------------------------------------
# ENTRY: run main() only when this file is executed (not when imported)
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    main()
