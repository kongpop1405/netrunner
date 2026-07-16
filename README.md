# NetRunner

Auto-farm engine for LDPlayer (Android emulator). **CV + scripted control over ADB.** Game-agnostic — a game is just a JSON config + a folder of template PNGs.

```
capture (adb screencap) → perceive (opencv match) → act (adb tap) → FSM loop
```

New machine? Follow [SETUP.md](SETUP.md) (onboarding checklist). Day-to-day bot commands: [RUN.md](RUN.md).

> ⚠️ **Clone to a plain-ASCII path outside OneDrive** (e.g. `C:\dev\netrunner`).
> OpenCV fails **silently** on paths with non-ASCII characters (e.g. Thai `เอกสาร`) —
> templates never match and nothing errors. OneDrive sync also fights `logs/`/`snaps/` writes.

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

## Machine settings — `.env`

Machine-specific values live in `.env` (copy [.env.example](.env.example); git-ignored, never commit):

| key | what |
|-----|------|
| `ADB_PATH` | adb binary path (skip if `adb` is on PATH) |
| `NETRUNNER_DEVICE` | your instance's adb address — overrides the config's `"device"` |
| `DISCORD_WEBHOOK_URL` | optional crash/livelock alerts |

Read by `main.py` (python-dotenv) and every `run_*.bat`. Precedence: CLI flag > `.env` > config JSON.

## Quick start

```bash
# 1. see connected devices
python main.py --list-devices

# 2. capture current screen (to build templates)
python tools/snap.py --device 127.0.0.1:5555 --out snaps/example_game/

# 3. run a farm config
python main.py --config config/example_game.json

# dry-run: FSM logs decisions but sends no taps
python main.py --config config/example_game.json --dry-run
```

## Add a new game

1. Run `tools/snap.py --out snaps/<game>/` — raw screen captures land there (git-ignored).
2. Crop distinctive UI bits (a button, a "victory" banner) into `.png` files in `templates/<game>/`. Tight crops match better. Keep this folder curated — raw snaps stay in `snaps/`.
3. Write the FSM config (see [config/example_game.json](config/example_game.json)). One-off game = `config/<game>.json`; several bots for the same game = `config/<game>/<task>.json` (like `config/cookierun/`).
4. `python main.py --config <path> --dry-run` until state transitions look right, then drop `--dry-run`.

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
      "detect": "marker.png",        // template that identifies this state,
                                     // or a LIST ["a.png","b.png"] (any-of, first found wins)
      "threshold": 0.9,              // optional: per-state override of match_threshold
      "on_match":  [ <action>, ... ],// runs when state detected. With a detect LIST it
                                     // may be a dict { "a.png": [...], "b.png": [...] }
                                     // — the branch of the template that matched runs
      "absent_retries": 3,           // optional: tolerate N absent polls before on_absent
      "absent_wait_ms": 1000,        // optional: extra sleep per absent retry
      "on_absent": { "goto": "..." },// optional: state not detected (after retries)
      "timeout_ms": 120000           // optional: bail if stuck this long
    }
  }
}
```

Configs are validated at load time: every `goto` target, template file, and field
range is checked, and the `on_absent`-goto-to-itself + `timeout_ms` combination is
rejected (it guarantees an `FsmError` crash when the timeout fires).

### Action types

| type | fields | effect |
|------|--------|--------|
| `tap_template` | `template`, `threshold?` | find PNG on screen, tap its center |
| `tap_xy` | `x`, `y` | tap absolute pixel |
| `swipe` | `x1,y1,x2,y2`, `ms?` | swipe/drag |
| `wait` | `ms` | sleep |
| `key` | `code` | Android keyevent (4 = BACK) |
| `jump` | `cx,cy`, `rx?,ry?` | human-like tap in a button ellipse, 35% double-jump |
| `slide` | `cx,cy`, `rx?,ry?`, `hold_ms?` | press-and-hold (same-point swipe) |
| `text` | `value` | type ASCII text char-by-char into the focused field |
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
  alert.py     file logging + Discord webhook alerts
config/
  example_game.json   schema showcase (placeholder templates)
  cookierun/          one JSON per bot task (coinrun, giftdraw, ...)
templates/<game>/     curated template crops referenced by configs
snaps/<game>/         raw captures from tools/snap.py (git-ignored)
tests/                pytest suite (python -m pytest tests/)
tools/snap.py  save current screen as PNG (build templates)
main.py        CLI entrypoint
run_*.bat      double-click launchers, one per bot task
```

> RL is **out of scope** for now. `perceive`/`act` are structured so a learned policy could later replace the FSM's rule dispatch, but no agent/training code exists yet.
