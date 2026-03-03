# Tank AI — Daily log

What we built or changed each day. Add new entries at the top and fill in the date when you work.

---

## 2026-03-03 (or latest session)

- **Radar “two eyes”** — Overlay shows L and R distance circles (green / yellow / red). Optional second ultrasonic via `Config.ULTRASONIC_RIGHT`.
- **Motion-triggered recording** — Recording starts when the scene changes (frame-diff), not only when a dog is detected. Clips named `motion_*.avi` or `dog_*.avi`.
- **Snapshot key (C)** — Press C to save a single JPEG to `recordings/snapshot_YYYY-MM-DD_HH-MM-SS.jpg`.
- **Proximity beep** — When either ultrasonic eye is closer than `PROXIMITY_BEEP_CM`, the tank says “close”; beep rate increases as you get closer.
- **README** — Updated with radar eyes, motion recording, proximity beep, and snapshot.

---

## Earlier: Refactor and voice

- **Code refactor** — `Config` class, `RecordingState`, small functions, docstrings. See `docs/IMPROVEMENTS.md`.
- **“Hi Human” (G key)** — Press G to speak “Hi Human” on the USB speaker.
- **Hold R to record voice** — Hold R to record from the mic; length = how long you hold. Saves WAV to `recordings/voice_*.wav`. Mic check on startup.
- **Speaker volume** — Greeting uses espeak piped through sox for extra gain on USB speaker (ALSA card 3).

---

## Earlier: Notifications and headless

- **Dog recording** — Record video when a dog is in scene; save when dog leaves.
- **WhatsApp notification** — CallMeBot: free WhatsApp message when a recording is saved. Keys in `.env`; notification runs in a background thread.
- **Headless mode** — Run over SSH without a display: no `cv2.imshow` when `DISPLAY` is unset or `HEADLESS=1`.

---

## Earlier: Setup and safety

- **Documentation** — Inline comments and docstrings so the code is easier to follow.
- **`.env` and `.env.example`** — API keys and phone number in `.env`; example file for others.
- **Git and GitHub** — `.gitignore` for `.env` and `recordings/`; pre-commit hook to block committing them. Push via PAT.

---

## How to use this log

1. **When you work on the project**, add a new `## YYYY-MM-DD` section at the top (under the “Daily log” heading).
2. **Bullet points** — One line per feature or change.
3. **Optional** — Add a short “Next” or “TODO” at the bottom of a day if you want to remember what to do next.
