# NetRunner

Auto-farm engine for LDPlayer (Android emulator). **CV + scripted control over ADB.** Game-agnostic — a game is just a JSON config + a folder of template PNGs.

```
capture (adb screencap) → perceive (opencv match) → act (adb tap) → FSM loop
```

New machine? Follow [SETUP.md](docs/SETUP.md) (onboarding checklist). Day-to-day bot commands: [RUN.md](docs/RUN.md).

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

## Connecting to LDPlayer — auto-detected

adb and the emulator are found automatically: adb from `PATH` or the newest
`C:\LDPlayer\LDPlayer*\adb.exe`, the instance by scanning ports `5555, 5557, 5559, 5561`
(port = `5555 + 2*instance_index`). Start LDPlayer with ADB debugging enabled and run —
no configuration needed.

Overrides (optional, via `.env` — copy [.env.example](.env.example); git-ignored, never commit):

| key | when |
|-----|------|
| `NETRUNNER_DEVICE` | several instances running — pin which one the bot drives |
| `ADB_PATH` | adb in a non-standard location |
| `DISCORD_WEBHOOK_URL` | crash/livelock alerts to a Discord channel |

Precedence: CLI flag (`--device`/`--adb`) > `.env` > auto-detect > config JSON.

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
  "poll_ms": 800,                    // gap between capture cycles; [500, 900] = fresh
                                     // random draw per cycle (kills the metronome cadence)
  "match_threshold": 0.85,           // 0..1, higher = stricter match
  "start_state": "home",

  // ── human pacing (all optional; omit = old fixed behaviour) ──
  "inter_game_delay_s": [30, 60],    // idle between games, on ENTRY to...
  "inter_game_state": "home",        // ...this state (default: start_state)

  // ── scheduled app restart (needs a Restarter — see --launch) ──
  "session_reset_s": [5400, 10800],  // force-stop + relaunch every 1.5-3h
  "reset_at_state": "home",          // only restart from a safe screen
  "package": "com.devsisters.crg",   // what to force-stop/relaunch

  // ── timed side errands (send lives, etc.) ──
  "periodic_routines": [
    { "name": "send_lives",
      "interval_s": [1500, 2100],    // every 25-35 min
      "at_state": "home",            // detour only from the safe state
      "goto": "lives_scan",          // entry of the errand's state chain
      "after_reset": true }          // also run right after a session reset
  ],

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
      "timeout_ms": 120000,          // optional: bail if ABSENT this long
      "match_timeout_ms": 25000,     // optional: bail if still MATCHED this long
                                     // (a stuck dismiss loop; timeout_ms never fires there)
      "on_match_timeout": { "goto": "..." }, // optional escape for match_timeout_ms
                                     // (default: the on_absent goto)
      "boost_role": "probe",         // optional: labels the boost buy chain for --boost
                                     // (probe / buy / picker / gate; see src/boost.py)
      "boost_skip_goto": "check_heart" // required on gate states: where --boost none jumps
    }
  }
}
```

Configs are validated at load time: every `goto` target, template file, and field
range is checked; the `on_absent`-goto-to-itself + `timeout_ms` combination is
rejected (it guarantees an `FsmError` crash when the timeout fires), and the same
check covers `match_timeout_ms` escapes. Unreachable states are warned about —
run `python tools/lint_config.py config/cookierun/*.json` for the full report
(orphans, note/detect drift, optional `--svg` transition graphs).

### Action types

| type | fields | effect |
|------|--------|--------|
| `tap_template` | `template`, `threshold?` | find PNG on screen, tap its center |
| `tap_xy` | `x`, `y` | tap absolute pixel |
| `swipe` | `x1,y1,x2,y2`, `ms?` | swipe/drag |
| `wait` | `ms` | sleep; `[min,max]` = fresh random draw per execution |
| `key` | `code` | Android keyevent (4 = BACK) |
| `jump` | `cx,cy`, `rx?,ry?` | human-like tap in a button ellipse, 35% double-jump |
| `slide` | `cx,cy`, `rx?,ry?`, `hold_ms?` | press-and-hold (same-point swipe) |
| `text` | `value` | type ASCII text char-by-char into the focused field |
| `goto` | `state` | jump to another state |
| `stop` | — | end the run |

Shared game actions (behaviour lives in `Actor`, tunable in one place):

| type | fields | effect |
|------|--------|--------|
| `relay_tap` | `x?,y?,taps?` | Cookie Relay Boost tap (blind by design — no template exists) |
| `faststart_tap` | `x?,y?,taps?,gap_ms?` | spam the Fast Start prompt across its window |
| `close_popup` | `x,y`, `verify?`, `settle_ms?`, `retries?` | tap a close button and, with `verify`, re-read the screen and re-tap while the popup's marker still matches — a dismiss that checks it landed |
| `restart_app` | — | force-stop + relaunch + stability-verify the game, for screens it cannot recover from itself (a lost connection); no-op with a warning when no Restarter is wired |
| `solve_cards` | `cells`, `cell_size`, `bail_goto`, `pick?`, `gap_min?`, `confirm_xy?` | odd-cards-out captcha: compare the cells against each other and tap the odd ones — or, when the split is not clearly wider than `gap_min`, tap **nothing** and route to `bail_goto` (a wrong captcha answer risks the account) |
| `run_config` | `config` (path) | detour into another config's own FSM — loads it fresh, drives it on a new `Runner` sharing this run's device, and returns once that config's own `stop` fires. No webhook/restarter/further-errand passed through. No-op with a warning when no Runner wired it up (e.g. called outside `main.py`/a `Runner`). See boxrun's `check_heart` in [docs/RUN.md](docs/RUN.md) for a worked example (Send-Life + Mailbox errands while hearts regen) |

Taps get small random jitter + delay to avoid a robotic fixed-pixel pattern.

## Layout

```
src/
  device.py    ADB wrapper — connect, list, resolution, raw shell (retries, AdbError)
  capture.py   screencap → numpy BGR
  perceive.py  cv2.matchTemplate, odd-cells-out, OCR counter reading
  act.py       executes one action dict; humanized taps + shared game actions
  config.py    load + validate config JSON (incl. reachability warning)
  fsm.py       the perceive→act loop; pacing, session resets, routines,
               match-timeout escapes, unknown-screen archiving
  session.py   force-stop + relaunch + pidof stability verification
  boost.py     boost profiles + role-marker retargeting (--boost)
  launcher.py  ldconsole: boot an LDPlayer instance, start the game
  alert.py     file logging + Discord webhook alerts (per-title cooldown)
config/
  example_game.json   schema showcase (placeholder templates)
  cookierun/          one JSON per bot task (coinrun, giftdraw, ...)
templates/<game>/     curated template crops referenced by configs
snaps/<game>/         raw captures from tools/snap.py (git-ignored)
unknown_screens/      frames archived when a loop stalls (git-ignored)
tests/                pytest suite (python -m pytest tests/)
tools/
  snap.py             save current screen as PNG (build templates)
  lint_config.py      orphan states, note drift, --svg transition graphs
  report_runs.py      summarize the rotated logs into an HTML run report
  run_toggle.py       boxrun_toggle launcher with per-run feature flags
  fetch_db_icons.py   download cookierundb.com icons + index.json (labeling reference)
main.py        CLI entrypoint (--boost, --launch, --dry-run, ...)
install.bat    first-run setup checker (stays at repo root)
launchers/     double-click bot launchers (*.bat), one per bot task
docs/          RUN.md, SETUP.md, PLAY_SETUP.md, HANDOFF.md + reports/plans
```

> RL is **out of scope** for now. `perceive`/`act` are structured so a learned policy could later replace the FSM's rule dispatch, but no agent/training code exists yet.
