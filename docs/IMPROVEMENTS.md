# How This Code Was Improved (Software Engineering Guide)

This document explains the improvements made to Tank AI and **why** they matter. Use it to learn patterns you can reuse in other projects.

---

## 1. Configuration in One Place

**What:** All tunable values (speeds, distances, paths, YOLO settings) live in a single `Config` or config section at the top.

**Why:**
- **One place to look** when you want to change behavior (e.g. increase `STOP_DISTANCE`).
- **No magic numbers** scattered in the middle of the loop (`0.20`, `15`, `320`, `0.4`).
- **Easier testing and deployment**: you can load different configs for different environments (e.g. Pi vs. laptop).

**Before:** Numbers like `0.20`, `15`, `320` appear inline in the code.  
**After:** `config.py` or a `Config` object at the top; the rest of the code references `config.MAX_SPEED`, `config.STOP_DISTANCE`, etc.

---

## 2. Small Functions with Single Responsibility

**What:** The main loop is short and readable. Each logical step (capture frame, detect dog, update recording, handle keys) is a function with a clear name.

**Why:**
- **Readability:** `run_main_loop()` shows *what* the program does; details live in `detect_dog_in_results()`, `update_recording()`, etc.
- **Testability:** You can unit-test “did we detect a dog?” without running the camera or motors.
- **Reuse:** Functions like `get_detected_classes(results)` can be reused if you add more behaviors.

**Before:** One long `while True:` block with 100+ lines.  
**After:** Loop body is ~10–15 lines calling named functions; each function does one thing.

---

## 3. Explicit Error Handling (No Bare `except`)

**What:** Replace `except Exception: pass` with specific exception types and optional logging.

**Why:**
- **Bare `except Exception`** hides bugs (e.g. `KeyboardInterrupt`, or a typo that raises `NameError`).
- Catching **specific errors** (e.g. `OSError` for camera/serial, `AttributeError` for missing YOLO fields) makes failures predictable and debuggable.
- **Logging** (or at least a print in development) helps you see why something failed.

**Before:** `except Exception: dog_present = False` — you don’t know if YOLO failed or the tensor format changed.  
**After:** `except (AttributeError, IndexError) as e: logger.debug("Detection parse failed: %s", e); return False`.

---

## 4. Main Guard: `if __name__ == "__main__"`

**What:** Put the “run the robot” logic inside:

```python
if __name__ == "__main__":
    main()
```

**Why:**
- **Import without running:** Other code can `from tank_ai import run_detection` or reuse helpers without starting the camera and motors.
- **Testing:** Tests can import the module and call functions without the loop starting.
- **Standard Python idiom:** Expected in any script that might be reused or tested.

---

## 5. State in a Small Object (Instead of Many Globals)

**What:** Group related state (e.g. `dog_seen`, `video_writer`, `current_recording_path`) into one object or dataclass (e.g. `RecordingState`).

**Why:**
- **Fewer globals** → easier to reason about and pass into functions.
- **Shutdown** can clear one state object instead of touching several global variables.
- **Clear ownership:** “Everything about recording lives here.”

**Before:** `dog_seen`, `video_writer`, `current_recording_path` as separate globals; `shutdown()` uses `global video_writer`.  
**After:** `state = RecordingState()`; functions receive `state`; shutdown calls `state.close()`.

---

## 6. Docstrings and Type Hints

**What:** Every public function has a one-line (or short) docstring; arguments and return values use type hints where helpful.

**Why:**
- **Documentation:** You (and others) see what a function does and what it expects without reading the body.
- **IDE support:** Autocomplete and “go to definition” work better.
- **Contracts:** `def detect_dog_in_results(results) -> bool` makes it obvious the function returns True/False for “dog present.”

**Example:**

```python
def detect_dog_in_results(results, model) -> bool:
    """Return True if any detection in this frame is class 'dog'."""
    ...
```

---

## 7. Constants for “Magic” Values

**What:** Names for values that have meaning: `YOLO_CONFIDENCE = 0.4`, `YOLO_IMGSZ = 320`, `COCO_CLASS_DOG = "dog"`.

**Why:**
- **Self-documenting:** `if confidence > YOLO_CONFIDENCE` is clearer than `if confidence > 0.4`.
- **Change in one place:** Tuning YOLO means editing one line.
- **Easier to make configurable:** Those constants can later come from config or env.

---

## 8. Graceful Degradation

**What:** If a non-critical part fails (e.g. espeak, WhatsApp), the rest of the app keeps running and optionally logs the failure.

**Why:**
- **Robustness:** One missing dependency shouldn’t kill the whole robot.
- **User feedback:** “WhatsApp notification skipped” is better than a silent failure or a crash.

---

## Summary Table

| Improvement            | Benefit                          |
|------------------------|----------------------------------|
| Config in one place    | Easier tuning and deployment     |
| Small functions        | Readable, testable, reusable     |
| Explicit exceptions     | Debuggable, predictable failures |
| `if __name__ == "__main__"` | Importable, testable script  |
| State object            | Fewer globals, clear ownership   |
| Docstrings + types      | Clear contracts, better tooling  |
| Named constants         | Self-documenting, single place to change |
| Graceful degradation   | Robustness, better UX            |

The refactored `tank_ai.py` applies these ideas so you can read the main loop and jump into the right function when you need to change behavior.
