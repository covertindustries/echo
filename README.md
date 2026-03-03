# CovertIndustries - TankAI

Autonomous-capable Raspberry Pi Tank with:

- Manual WASD control
- Ultrasonic collision prevention
- YOLOv8 object detection (e.g. dog)
- Event recording when a dog is in scene **or** when motion is detected (frame-diff)
- Optional WhatsApp notification when a recording is saved (free via CallMeBot)
- Live camera overlay and automatic braking
- **Radar-style “two eyes”** — L/R distance shown as two circles on screen (green = far, yellow/red = close)
- **Proximity beep** — espeak says “close” when either eye is below a threshold; beep rate increases as you get closer
- **Snapshot** — press C to save a single JPEG to `recordings/`

---

## Hardware

- Raspberry Pi 5
- Freenove Tank V2.0
- HC-SR04 Ultrasonic Sensor (one or two: left + right for true radar)
- OV5647 Pi Camera

---

## Controls

| Key | Action |
|-----|--------|
| W | Forward |
| S | Backward |
| A | Turn Left |
| D | Turn Right |
| G | Say “Hi Human” |
| C | Snapshot (save JPEG to `recordings/`) |
| Q | Quit |

**Recording:** Clips start when a dog is detected or when motion (frame-diff) is detected; they save when the scene is clear. Files are named `dog_*.avi` or `motion_*.avi`. **Proximity:** When either ultrasonic eye is closer than `Config.PROXIMITY_BEEP_CM` (default 25 cm), the tank says “close”; the rate increases as you get closer. Tune with `MOTION_DIFF_THRESHOLD` and `PROXIMITY_BEEP_CM` in `Config`.

**Radar eyes:** The overlay shows two circles (L and R) with distance in cm; color = green (far), yellow (mid), red (close). With one sensor, both eyes show the same value. To use a **second ultrasonic** for left/right, set `Config.ULTRASONIC_RIGHT = (echo_gpio, trigger_gpio)` in `tank_ai.py` (e.g. `(24, 23)` for the right sensor).

---

## Setup

```bash
python3 -m venv tankai --system-site-packages
source tankai/bin/activate
pip install -r requirements.txt
python3 tank_ai.py
```

---

## WhatsApp notifications (optional, free)

When a dog recording is saved, the app can send you a WhatsApp message (e.g. *"Tank AI: dog recording saved — dog_2025-03-02_14-30-45.avi"*). This uses **CallMeBot**, which is free and does not require Twilio.

1. **Get an API key**  
   - Add **+34 644 66 32 62** to your phone contacts.  
   - In WhatsApp, send this contact: **"I allow callmebot to send me messages"**.  
   - You’ll receive a reply with your API key.

2. **Configure**  
   Set these in your environment (or copy `.env.example` to `.env` and fill in; load with `python-dotenv` if you use it):

   - `CALLMEBOT_WHATSAPP_APIKEY` — the key from step 1  
   - `CALLMEBOT_WHATSAPP_PHONE` — your number in E.164 (e.g. `+15551234567`)

   Example:

   ```bash
   export CALLMEBOT_WHATSAPP_APIKEY="your_api_key_here"
   export CALLMEBOT_WHATSAPP_PHONE="+15551234567"
   ```

3. **Run**  
   If both are set, you’ll get a WhatsApp message each time a dog recording is saved. If either is unset, recordings still save to `recordings/`; notifications are simply skipped.

Reference: [CallMeBot WhatsApp API](https://www.callmebot.com/blog/free-api-whatsapp-messages/).

---

## Project layout

- `tank_ai.py` — main script (camera, YOLO, motors, recording, keyboard). Uses a `Config` class, `RecordingState`, and small functions so the main loop stays readable.
- `notifications/` — notification backends (e.g. WhatsApp via CallMeBot).
- `recordings/` — saved dog clips (created automatically).
- `.env.example` — example env vars for WhatsApp (copy and set values as needed).
- `docs/IMPROVEMENTS.md` — **software-engineering guide**: why the code is structured this way and how to improve it further.
- `docs/DAILY_LOG.md` — **daily log**: what was built or changed each day (add new entries as you go).
