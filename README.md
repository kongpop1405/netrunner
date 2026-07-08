# NetRunner

Auto-farm engine for LDPlayer (Android emulator). **CV + scripted control over ADB.** Game-agnostic — a game is just a JSON config + a folder of template PNGs.

```
capture (adb screencap) → perceive (opencv match) → act (adb tap) → FSM loop
```

## Requirements

- **Python 3.10+**
- **ADB** on PATH (`adb version` must work). Comes with Android Platform Tools or bundled in LDPlayer's `dnadb.exe`.
- **LDPlayer** with ADB debugging enabled (LDPlayer → Settings → Other → ADB debugging: *Open local connection*).
- (optional) **Tesseract** binary for OCR states — [install](https://github.com/UB-Mannheim/tesseract/wiki), then `pip install pytesseract`.

```bash
pip install -r requirements.txt
```

## Connect LDPlayer over ADB

LDPlayer instances listen on ports `5555, 5557, 5559, ...` (port + 2 per instance).

```bash
adb connect 127.0.0.1:5555
adb devices          # confirm the emulator shows up
```

Use that address as `"device"` in your config (or pass `--device`).

## Quick start

```bash
# 1. see connected devices
python main.py --list-devices

# 2. capture current screen (to build templates)
python tools/snap.py --device 127.0.0.1:5555 --out templates/example_game/

# 3. run a farm config
python main.py --config config/example_game.json

# dry-run: FSM logs decisions but sends no taps
python main.py --config config/example_game.json --dry-run
```

## Add a new game

1. `mkdir templates/<game>/`
2. Run `tools/snap.py`, crop distinctive UI bits (a button, a "victory" banner) into `.png` inside that folder. Tight crops match better.
3. Write `config/<game>.json` describing the FSM (see [config/example_game.json](config/example_game.json)).
4. `python main.py --config config/<game>.json --dry-run` until state transitions look right, then drop `--dry-run`.

## Config schema

```jsonc
{
  "device": "127.0.0.1:5555",        // adb address; overridable via --device
  "templates_dir": "templates/example_game",
  "poll_ms": 800,                    // gap between capture cycles
  "match_threshold": 0.85,           // 0..1, higher = stricter match
  "start_state": "home",
  "states": {
    "<state_name>": {
      "detect": "marker.png",        // template that identifies this state
      "on_match":  [ <action>, ... ],// runs when state detected
      "on_absent": { "goto": "..." },// optional: state not detected
      "timeout_ms": 120000           // optional: bail if stuck this long
    }
  }
}
```

### Action types

| type | fields | effect |
|------|--------|--------|
| `tap_template` | `template`, `threshold?` | find PNG on screen, tap its center |
| `tap_xy` | `x`, `y` | tap absolute pixel |
| `swipe` | `x1,y1,x2,y2`, `ms?` | swipe/drag |
| `wait` | `ms` | sleep |
| `goto` | `state` | jump to another state |
| `stop` | — | end the run |

Taps get small random jitter + delay to avoid a robotic fixed-pixel pattern.

## Layout

```
src/
  device.py    ADB wrapper — connect, list, resolution, raw shell
  capture.py   screencap → numpy BGR
  perceive.py  cv2.matchTemplate + OCR → (found, score, x, y)
  act.py       tap/swipe/wait + jitter, executes one action dict
  config.py    load + validate config JSON
  fsm.py       the perceive→act loop
tools/snap.py  save current screen as PNG (build templates)
main.py        CLI entrypoint
```

> RL is **out of scope** for now. `perceive`/`act` are structured so a learned policy could later replace the FSM's rule dispatch, but no agent/training code exists yet.
