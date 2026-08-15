# RUN — cookierun bot cheatsheet

Day-to-day bot commands. New machine? Start at [SETUP.md](SETUP.md).

adb + device are **auto-detected** (adb from PATH / newest `C:\LDPlayer\LDPlayer*`, device by
scanning ports 5555-5561) — commands below need no `--adb`/`--device`. `.env` is optional and
only pins overrides. Precedence: CLI flag > `.env` > auto-detect > config JSON.

## Verified environment (2026-07-10)

- Python 3.10.11, `opencv-python` 4.13, `numpy` 2.2.6, `requests`, `python-dotenv` — installed.
- **LDPlayer14**, instance `LDPlayer-1` (index 1), device `127.0.0.1:5557` @ 1920x1080, `device` state — auto-detected.
- Bundled adb: `C:\LDPlayer\LDPlayer14\adb.exe` — auto-detected.
- The original index-0 `LDPlayer` instance's adbd got stuck permanently offline (TCP handshake
  never completed even after kill-server/regen-key/instance-reboot — root cause never isolated,
  only a full Windows restart cleared it once, and a second incident needed a brand new instance).
  If `adb devices` shows a device stuck `offline` for more than a minute despite reconnects,
  don't sink more time into that instance — create a fresh one in LDMultiPlayer, set its
  resolution to 1920x1080 (`ldconsole modify --index N --resolution 1920,1080,240`, instance
  must be stopped first) — auto-detect finds the new port by itself (clear any `NETRUNNER_DEVICE` pin in `.env`).
- Dry-run smoke test passed on the new device/port (2026-07-10).

## Engine upgrade (2026-07-16) — not yet live-verified

Engine + layout overhaul; unit tests pass (48) and every config validates, but **no live
run since** — treat the first live run of each bot as a smoke test (`--max-cycles` capped).

- **Layout**: configs moved to `config/cookierun/<task>.json`; `cookierun.json` renamed
  `coinrun.json`; `run_bot.bat` renamed `coinrun.bat`; raw `snap_*.png` moved out of
  `templates/` into `snaps/<game>/` (git-ignored); `templates/<game>/` is curated crops only.
- **`absent_retries` / `absent_wait_ms`** (per state): tolerate N absent polls (each optionally
  sleeping `absent_wait_ms`) before `on_absent` fires. The hand-written retry chains
  (`gift_draw_2/_3`, `reward_2..5`, `await_faststart_2/_3`, `await_shop_2`, `picker_2`,
  `rescue_check2`) are collapsed into their head states.
- **`detect` any-of + branching `on_match`**: `detect` accepts a list (first found wins) and
  `on_match` may be a dict keyed by template — one state can watch several popups. Existing
  probe chains still work; collapse them opportunistically after a live verify.
- **Per-state `threshold`**: overrides global `match_threshold` (e.g. tune the thin
  `heart_empty.png` margin without touching other templates).
- **Load-time validation**: goto targets, template files, and field ranges are checked at
  startup; the `on_absent`-self-goto + `timeout_ms` crash trap (see Engine gotcha below) is
  now **rejected at load** instead of crashing mid-farm.
- **Stale-frame goto-cycle fix**: a pure-goto cycle (no taps/waits) used to spin forever on
  one cached frame; the engine now forces a re-grab + poll-sleep once a goto chain revisits
  a state, and fires a "possible livelock" Discord alert if states keep flipping with no
  action for ~100 polls (same threshold as the same-state warning).
- **Tests**: `python -m pytest tests/` (259 tests — perceive/config/fsm/act/cli/session/routine/pacing/boost/popup/ocr/captcha/observability; 7 skip without tesseract).

## Shared action types (2026-07-29) — fix one place, every bot gets it

Behaviour that every bot repeats — the Fast Start spam, the Cookie Relay tap, closing a
popup — used to be copy-pasted into each config as raw `tap_xy` entries. Fixing "the relay
sometimes doesn't fire" then meant editing 13 JSON files and hoping none were missed.

That behaviour now lives in `Actor` (`src/act.py`, section *shared game actions*) behind
three action types. A config names the action; the engine supplies the coordinates, the
counts, and the retry policy:

| action | replaces | tune it at |
|--------|----------|------------|
| `relay_tap` | `tap_xy(960,540)` | `Actor.relay_xy` / `relay_taps` / `relay_gap_s` |
| `faststart_tap` | `tap_xy(985,515)` + `wait`, ×12-14 (24 JSON entries) | `Actor.faststart_xy` / `faststart_taps` / `faststart_gap_ms` |
| `close_popup` | `tap_xy(x,y)` + `wait` | `Actor.popup_settle_ms` / `popup_retries` |

**The point**: `Actor.relay_taps = 2` is a one-line change in `src/act.py` and every config
that says `{"type": "relay_tap"}` fires twice from the next run on — no JSON edit, no regen,
no sync step. Every field is still overridable per action (`{"type": "relay_tap", "taps": 3}`)
for the one screen that needs to differ.

`close_popup` also takes `verify` — the popup's own marker template. With it the close is
confirmed instead of assumed: after the settle wait a fresh frame is captured, and the tap is
repeated while the marker is still on screen. That is the fix for a close tap that lands
while the dialog is still fading in and silently does nothing. Verification is best-effort —
a failed re-read logs a warning and moves on rather than crashing a farm.

```json
{"type": "close_popup", "x": 727, "y": 688, "verify": "sendlife_marker.png"}
```

**Migration**: `tools/migrate_action_types.py` rewrote the inline ladders across all 13
configs (−2255 lines, +79). It defaults to a dry run that prints what would change; `--write`
applies it. `close_popup` rewriting is opt-in via `--close-popups` because "tap something,
then wait" is also the shape of buy-cell taps and menu navigation, which coordinates alone
can't distinguish. `tap_xy` is still a valid action — nothing was removed, so an un-migrated
config keeps working.

```powershell
python tools/migrate_action_types.py                    # report only
python tools/migrate_action_types.py --write <config>   # apply to one file
```

## Parity + anti-detection upgrade (2026-07-30) — not yet live-verified

Everything below shipped on `feature/parity-anti-detection` and is covered by the
test suite (259 passed), but none of it has run against a live emulator yet — see
**HANDOFF.md** for the verification gate and the work that still needs a real screen.
The full plan with per-phase findings: `docs/plans/PLAN_feature-parity-anti-detection.html`.

- **Human pacing** — `poll_ms: [500,750]`, `wait.ms: [800,1400]` (fresh draw each
  time), `inter_game_delay_s: [30,60]` idle between games. Enabled in
  `boxrun_toggle.json` only; every other config keeps fixed pacing until it is proven.
- **Session reset** — `session_reset_s: [5400,10800]` force-stops and relaunches the
  game every 1.5-3h, verified alive via `pidof` across 3 spaced checks. Also in
  `boxrun_toggle.json` only.
- **Send-lives errand** — `periodic_routines` detours to the grafted `lives_*` chain
  every 25-35 min and right after each reset (`boxrun_toggle.json`).
- **Verified popup closes** — 194 blind `tap_xy`+`wait` dismisses became
  `close_popup` + `verify` across all 13 configs.
- **`--boost` everywhere** — `main.py --boost {magnet,speed,doublecoins,none}` works
  on any config whose chain carries `boost_role` markers (6 configs). 8 more boosts
  are listed but refused until their banners are cropped.
- **OCR box counter** — `--quit-after-boxes N` reads the actual "[?] xN" pill when
  tesseract is installed; falls back to the old per-run counting when not.
- **Captcha solver (odd-cards-out)** — implemented and tested, wired into **no**
  config: the cell coordinates have never been measured against a real challenge.
- **Observability** — a stalled loop archives its frame to `unknown_screens/` and
  posts it to Discord; `tools/report_runs.py` summarizes the rotated logs
  (runs/hour, boxes, failures) into an HTML report.
- **Zero orphan states** — `tools/lint_config.py` guards it; ep3's boost chain and
  the ep5 family's popup probes were silently unreachable before.

## Progress watchdog + News guard (2026-08-01) — live-verified

Fixes a 13h livelock: the bot jumped into an unrecognised **News** popup 389 times
between 22:18 and 12:00 without a single warning. Both existing livelock detectors
stayed silent by design — state kept changing (so `same_state_streak` reset every
poll) and `jump`/`slide` count as actions (so `no_act_streak` reset every poll).
They ask *"did the bot stop?"*; the bot was working hard and getting nowhere.

**Root cause was two-layered.** ADB dropped at 22:26 (`daemon not running`, then
`device not found` ×5), the client relaunched itself, and the relaunch brought up
News — which covers Play! (`home_play` scores 0.263 through it). No guard
recognised it, so `guard_not_inactive.on_absent` concluded "genuinely mid-run" and
jumped. The probe chain *would* have handled it, but it is only reachable when the
loop is on the probe side, and the loop was in the `running` guard chain.

- **`news_marker.png`** — teal News banner. Self 1.000, clear home 0.383, and it
  scored 1.000 on the actual stuck frame from that night. No threshold change.
- **Two guards, not one** — `probe_news` (probe side) *and* `guard_not_news` (the
  mid-run side that failed). Replaying the stuck frame through the patched chain
  walks the same five guards, then `guard_not_news` matches at 1.000 and closes it
  at (1688,113).
- **Progress watchdog** (`src/fsm.py`) — the class fix, since News was the 14th
  popup patched this way. Configs declare `progress_states` (arrivals that prove
  the loop got somewhere: `home`, `run_result`, `mystery_box`, `check_heart`) and
  `no_progress_goto`. Reaching none of them for `no_progress_s` means the screen is
  something the FSM cannot name, whatever it looks like. Opt-in: configs without the
  keys behave exactly as before. **`no_progress_s` was 300 and is now 600** — see
  [the wall clock had the same sizing bug](#the-wall-clock-had-the-same-sizing-bug-2026-08-15).
- **Blind-screen detector** (`blind_lap_cycles` per config, engine default 160 —
  added 2026-08-06, made per-config 2026-08-14) — the same recovery, reached without
  waiting out the wall clock. `no_progress_s` alone cannot tell a long run from a
  stuck one; a streak of polls where *nothing* matched can. It counts across state
  changes, unlike `absent_streak`, which resets on every transition and so never
  sees a chain walking thirty states in a row. The threshold is measured, not
  derived, **and it is table-length-dependent** — see the live numbers below.
- **Two-step recovery, escalating** — `recover_unknown` spends one cheap pass
  through the probe chain (free, and it fixes every *known* popup); a second fire
  means that failed, so `recover_unknown_restart` cycles the app and re-auths via
  `recover_login`. The escalation is not optional: live test proved the **Events**
  popup has no marker, ignores Android BACK, and survives a full probe-chain walk.
- **Recovery grace window** (`_RECOVERY_GRACE_S`, 180s) — `restart_app` + relogin
  measured **99s** live, longer than a tight `no_progress_s`. Without the grace the
  watchdog fires mid-restart and stacks another restart on the one in flight.

Live verification (2026-08-01, `boxrun_toggle` with `no_progress_s=40`):
fire #1 → probe chain → still stuck → fire #2 → `restart_app` → `recover_login` →
**home at 13:02:00**, counter reset, loop resumed and banked a Mystery Box.

Applied to all five guard-chain configs (`boxrun_default`, `boxrun_magnet`,
`boxrun_toggle`, `coinrun`, `xpstat`) — +5 states each. 306 tests pass.

**Known gap**: Events (and any future unnamed popup) is still only *recovered*,
not *recognised* — each watchdog fire archives its frame to `unknown_screens/` and
posts it to Discord precisely so the marker can be cropped afterwards.

##### The wall clock had the same sizing bug (2026-08-15)

Fixing the blind detector left its twin mis-sized in exactly the same way. Measured over
**1,610 real inter-progress gaps** in this repo's logs (arrivals at `run_result`,
`mystery_box`, `home`, `check_heart`):

| statistic | gap |
|---|---|
| median | 64s |
| p90 | **302s** |
| p99 | **439s** |
| max | 1771s (the SDK dead window — a real fault) |

`no_progress_s` was **300**, i.e. sitting exactly on the p90, so **10.8% of healthy gaps
(174 of 1,610) tripped it** — a false recovery roughly every ninth game. Caught live at
02:33:23: the wall clock fired on a run that was merely long, the Result popup rendered two
seconds later, and the recovery walked the probe chain and reached `run_result` in three
seconds. Textbook correct handling of an alarm that should never have been raised.

Raised to **600** in all eight configs: clears the p99 with 1.4× headroom, and still speaks
before the blind detector's reach (600 polls at the measured 0.48 polls/s is ~1250s), so the
two detectors keep covering different failure shapes instead of one shadowing the other.
`tests/test_run_toggle.py::test_wall_clock_clears_a_long_but_healthy_game` locks it against
the measured p99 and against becoming slower than the blind detector — mutant-verified by
setting it back to 300, which fails the test.

**The general lesson, now paid for three times** (48 → 160 → 300): every threshold in this
watchdog must be sized off a *measured distribution of healthy behaviour*, and re-measured
whenever the state table or the game's pacing changes. A number that was right for a
32-state table and a 4-minute game is not right for a 66-state table and a 7-minute one.

##### The dialog that cost ten hours: `probe_sdkfail` + `guard_not_sdkfail` (2026-08-15)

Counting warnings per hourly log across 2026-08-14 turned up a window nobody had noticed:

| hours | blind fires/hr | `restart_app`/hr | games banked |
|---|---|---|---|
| 00:00-07:00 | 11-12 | 0 | 10-12 |
| **08:00-17:00** | 14-17 | **6-9** | **0** |
| 19:00-22:00 | 7-19 | 0-5 | 7-151 |
| 00:00-01:32 (after the 600 fix) | **0** | 0 | 12 |

Ten hours, zero games, a forced game restart every seven minutes. The cause is a dialog
with no marker anywhere in the config: **"Failed to connect to server. SDK Code:0"**, the
server-handshake failure that lands on the title screen. **166 of the 313 frames archived
that day are this dialog.** Every state missed it, the blind watchdog escalated to
`restart_app`, the client came back up, failed the handshake again, and the loop repeated.

⚠️ **`probe_connectionlost` does not cover it.** That marker is the *"Connection lost!"*
text and scores **0.648** on this frame — below the 0.82 threshold. The two dialogs share a
frame style and a green Confirm button but not a single word of text (template cross-scores
0.156 / 0.235), which is exactly why one marker cannot serve both.

The fix is the now-familiar pair, in all eight farm configs:

| piece | what |
|---|---|
| `home/sdkfail_marker.png` | the "Failed to connect to server. SDK" line cropped tight (50×770 at 575,405). **1.000** on 30/30 sampled positives, max **0.321** across 60 negatives — margin 0.679 |
| `probe_sdkfail` | **head** of the probe chain, ahead of `probe_connectionlost` — nothing further down the chain can work while the client is offline. `home` and `recover_unknown_probe` both route into it |
| `guard_not_sdkfail` | mid-run chain, `partyrun → friendinfo → **sdkfail** → inactive`. **This is the side that actually failed**: the archived frames came from `relay_stage2_jump_3`, `jump_2` and `running` |
| both `on_match` | tap Confirm (959,687 — inside the measured HSV blob bbox 744,614,431,147), then `restart_app` + `recover_login`. Confirm drops to the title screen rather than dismissing, so resuming `running` or `home` would resume a session that no longer exists |

**Fourth screen to need a probe *and* a guard** — News (2026-07-31), Party Run (08-06),
Friend's Info (08-14), SDK-failure (08-15). The lesson has now cost four incidents: a
probe-side fix cannot catch a popup that opens mid-run, because `probe_*` states are only
reachable from the probe side. When adding a marker for any new screen, add both halves at
once unless you can show the screen cannot appear during a run.

**Not every archived frame is a bug — check before cropping a marker for it.** The
wall-clock detector fired once on 2026-08-14 at 23:48:29 (`no progress for 301s`) and
archived `20260814_234830_relay_stage1_jump_4.png`. Nothing in the config matched it
(best score 0.547), which looks exactly like an unnamed-popup livelock. It was not:
the frame is the **"Save the Cookie" Pit Lift revive prompt** during BONUS TIME — the
game offering to sell a revive after the cookie falls. That screen clears itself when
the cookie dies, and the run banked normally right through it (`run_result` 23:48:55 →
`mystery_box` 23:48:58 → `home` 23:49:42 → next game 23:50:11). The recovery spent one
cheap probe-chain pass and never escalated. One fire in four hours of log, not a
pattern.

Do **not** add a marker and a guard for it. The config's own `_comment` already warns
that this screen can render *the same instant as the Cookie Relay prompt*, so a guard
closing it risks eating the relay — the failure the 2026-08-09 `absent_retries` fix
exists to prevent. A screen that resolves itself and costs nothing is correctly handled
by the watchdog noticing and moving on.

##### Relay stage 1 was waiting on a marker that never matches (2026-08-15)

The Cookie Relay is worth chasing: over 202 runs in one day, runs that fired a relay lasted
**280s median against 226s without — +54s, +24%**. Only 77 of those 202 caught one.

The prompt window is 2-3s and the bot was re-checking every **13.0s**, so roughly three
relays in four were never even looked at. The time was going somewhere specific:
`relay_stage1_*` and `relay_poll1_*` — five states — each carried `absent_retries: 2` plus
`absent_wait_ms: 400`, about **5s per visit**, waiting for `relay_prompt_marker`.

That marker has never matched. **Zero hits across 1,414 archived frames, best 0.673** — and
the frame holding that best score is the Mailbox *"Send a free Life"* dialog, not a relay
prompt at all. The commit that built the two-stage chain had already written it down: *"its
green Continue pill never passed 0.40."* This build's mid-run relay prompt has **no
Continue/Quit pair**; it shows the text plus the partner cookie's card, and tapping the
**card** is what fires it — stage 2's job, which works (threshold 0.62, 72 relays caught).

So five states were spending ~25s of every 13s check cycle on a guaranteed miss, while the
thing they were guarding lasts three seconds.

Fix: strip `absent_retries` / `absent_wait_ms` from stage 1 and poll 1 in all seven configs.
**The states stay** — if a build ever restores the two-button dialog this is where it gets
caught; they simply no longer wait around for it. Stage 2 is untouched: it matches, so its
retry and its 0.62 threshold both earn their keep.

Measured after the change: `relay_poll1_running` **5.0s → 0.0s**, check interval **13.0s →
9.0s**, catch chance ~23% → ~33%.

⚠️ **Counting relay taps by coordinate gives 16,840; the true number is 72.** The Fast Start
spam taps (985,515) with ±5px jitter, which lands on the relay card at (980,515). Only the
surrounding state tells them apart — count taps that occur inside `relay_poll2` / `relay_stage2`
`on_match`, never by pixel.

##### Watching the screen, not just the log (2026-08-15)

`tools/screen_watch.py` grabs a frame every 20s, compares consecutive frames with an 8×8
aHash, and when the screen holds still past a threshold it identifies it against every
template and saves the frame. `IDLE_SCREENS` gives the screens that are *supposed* to sit
still — heart regen (1800s), home (600s) — longer patience.

It exists because the log has a blind spot the SDK dialog walked straight through: for ten
hours the log looked busy (`restart_app` every ~7 minutes) while the screen never changed,
and nobody knew what was on it until a frame was opened by hand. The log reports what the bot
*believes*; this reports what is actually on the glass.

Proven both ways before being trusted, which is the only way a watcher like this is worth
anything: silent for 70s while the bot played normally, then — with the bot killed so the
screen genuinely froze — `SCREEN stuck 28s on mailbox/dialog_buttons_marker.png (1.00)` plus
the saved frame.

```bash
python tools/screen_watch.py --interval 20 --stuck-after 180
```

##### Why the blind threshold is per-config (and was 160)

Sizing it off the state table (32 states → 48) looked reasonable and was wrong.
Live on 2026-08-06, `boxrun_magnet` measured **70 consecutive misses while running
perfectly**: `home` → ten probes → `boost_shop` → the in-run jump chain match
nothing by design, because the jump chain drives entirely off absent edges. At 48
the watchdog fired mid-run and the recovery cost a heart and a 7.3M-point run —
worse than the livelock it exists to break. See
`docs/evidence/blind_false_positive_in_run.png`: the cookie is mid-level at 7.37M
at the moment the detector fired on it.

| screen | consecutive misses |
|---|---|
| healthy `boxrun_magnet` run (measured twice: 70, 68) | **70** |
| Events popup — no marker, survives BACK | **229** before escalation |

160 cleared the first with 2.3× headroom and still beat the 300s clock by 2-3×.
Re-tested after the change: **0 fires** across 200 cycles, peak streak 68, and the
run finished at 58.1M.

**Then the tables grew, and 160 became the false positive it replaced
(2026-08-14).** Both numbers above came off a **32-state** `boxrun_magnet`. Every
boxrun config has since roughly doubled — `speed`/`magnet` 63 states, `relay`/
`coinrun` 65, `toggle` **88** — with 19-28 of them driven by `on_absent` action
lists. A longer table walks proportionally more absent edges per lap, so a ceiling
fitted to 32 states fires mid-run on 63.

Live on `boxrun_speed`: **eight fires in 31 minutes** of healthy farming, every one
at exactly streak 160, and the eighth (`21:46:37`, streak 190, *"only 1s of 300s
elapsed"*) escalated to `recover_unknown_restart` and force-quit a run that was
going fine. Archived frames were ordinary mid-run gameplay. Real progress states do
match every game (`run_result` → `mystery_box` → `home` → `check_heart` arriving as
a set) but up to **443s apart**, and `blind_streak` resets only on an actual marker
match — so a healthy game legitimately spends that whole window blind.

Fix: **`blind_lap_cycles` is now a per-config field**, falling back to the engine's
160 when unset. All eight boxrun/coinrun/xpstat configs set **600**. The engine also
logs `blind-streak peak N polls (cleared by '<state>')` whenever a match clears the
streak — the measurement that was never recorded before, since a fire only ever
reported the threshold it tripped.

First readings on the restarted `boxrun_speed` (2026-08-14 23:32 onward):

| peak | cleared by | note |
|---|---|---|
| 4 | `await_shop` | startup, before the first run |
| **172** | `jump_2` | 4 min in — **above the old 160 threshold** |
| **176** | `relay_stage2_jump_3` | 15 min in |
| **177** | `relay_stage2_jump_3` | 22 min in, 6 games — *looked* like a plateau (+4, then +1) |
| **187** | `jump_2` | 3 h in |
| **201** | `running` | 3 h in |
| **205** | `running` | 3.2 h in |
| **227** | `jump_2` | 4.5 h in — **past the 229 that used to separate stuck from healthy** |
| **401** | `check_shop_after_run` | 14 h in — one 486s run, the longest of 224 that day. **67% of the 600 trip line** |

172 already settles the diagnosis: a run doing nothing wrong exceeds 160, so the old
ceiling sat below what healthy play produces and **every config still on 160 would
fire mid-run**, not just `boxrun_speed`. The `cleared by` column shows what actually
resets the streak — a different mid-run state each time (`await_shop`, `jump_2`,
`relay_stage2_jump_3`), never a progress state, which is why the count swings with
the rhythm of a game instead of climbing monotonically.

Same run, measured across the restart at 23:32:51:

| | window | watchdog fires | rate |
|---|---|---|---|
| before (160) | 18.4 min | 3 | **9.8/hr** |
| after (600) | 15 min | **0** | 0 |

Four Mystery Boxes banked in that window with no recovery and no forced restart.

**600 is the right number — and waiting for data is what proved it.** At 22 minutes the
peak read 177 and looked settled (+4, then +1), which made `300` look like the obvious
tightening: 1.7× headroom, and it would let the blind detector speak in ~10 minutes
instead of ~21. Three hours later the peak was **205**. Against that, `300` gives only
**1.46×** headroom — thin enough to start false-firing on the slowest games, which is the
exact failure being fixed. `600` gives 2.9×.

What the numbers settled:

- Measured poll rate: **0.48/s** (632 transitions over 1,312s).
- Healthy peak **205** polls ≈ 427s blind — right up against the p99 healthy gap of 439s
  measured independently from 1,610 progress arrivals. Two different measurements of the
  same underlying thing agreeing is the strongest evidence available here.
- `600` ≈ 1250s before the blind detector speaks, and the wall clock now fires at 600s,
  so **the wall clock is the fast detector and the blind streak is the backstop**. That
  ordering is deliberate: a screen with no marker at all is caught by the clock, while the
  streak catches the case where markers exist but nothing is banking.

⚠️ **A plateau over 20 minutes is not a plateau.** 177 → 187 → 201 → 205 → 227 kept climbing
for four and a half hours. The value only logs on a new record, so a quiet stretch reads
identically to a converged one. Anyone re-tightening this should watch for a full session,
include heart-empty waits and boost-shop detours, and keep at least 2× over the highest
reading.

**Second day of data (2026-08-15, 224 gaps, errand detours excluded):** median 240s, p90
301s, p99 327s, **max 486s**. Against that distribution the 600s wall clock fired **zero**
times, while the old 300 would have fired on **12.9%** of them — the same verdict the
1,610-gap dataset gave, reached independently.

That 486s run is what produced the 401 peak, so **the two knobs are not equally comfortable**:
the wall clock has 1.2× headroom over the worst observed gap, the blind streak only
**1.5×** (401 of 600). Watch the peak rather than the fire count — a run at 0 fires can
still be one long game away from tripping. If the peak reaches ~480, raise
`blind_lap_cycles` before it fires, not after.

⚠️ **Exclude errand detours when measuring gaps.** `periodic_routines` hand off to another
config through `run_config` (sendlife, then sendlife_mailbox), and the farm loop reaches no
progress state for as long as that takes — 1,466s on 2026-08-15 at 11:45. That is correct
behaviour, not a stall, and the watchdog rightly stayed quiet. But a naive gap measurement
counts it as one enormous healthy gap and inflates every percentile. Filter on the
`run_config:` line before computing anything from arrival timestamps.

The same blocking detour also shows up as a `match_timeout` warning, and that one is
**expected, not a bug**. `run_config` runs the errand's FSM to completion inside the calling
state, so the host state's `entered_at` keeps running the whole time. Seen once on
2026-08-16: `state 'check_heart' stuck 1554406ms >= timeout 1500000ms -> goto 'running'`
after a Send-Life sweep that had been dispatching to a long friend list since 00:02. The
errand was healthy throughout (`scan → confirm_dialog → message_sent`, one friend at a time)
and the timeout recovered in 13s — `check_heart → running → guard_not_home → home`.

Once in every log in the repo, against a median errand of 117s (max 156s), so do **not**
"fix" it by resetting `state_entered_at` when the errand returns: that would blind the
timeout to a host state that genuinely hangs after a detour, trading a 13-second false
alarm for a real stall that nothing catches. If it ever becomes frequent, raise
`check_heart`'s `timeout_ms` above the worst observed errand instead.

⚠️ **The old healthy/stuck boundary is gone.** The table at the top of this section says a
healthy `boxrun_magnet` run peaked at 70 and the Events popup — a genuinely stuck screen —
reached 229 before escalating, and 160 was chosen to sit between them. On the 66-state
configs a *healthy* run now reaches **227**. There is no longer a gap between the two
measurements to put a threshold in, which is why the wall clock (600s) is now the fast
detector and the blind streak (600 polls, ~1250s) is the backstop rather than the other way
round. Do not resurrect "somewhere between 70 and 229" as a sizing rule; both numbers belong
to a state table that no longer exists.

`tests/test_observability.py` locks the default's bounds *and* the override in both
directions — a config may raise the line, and a raised line must still trip.
Mutant-verified: ignoring the override fails both new tests, hardcoding
`blind = False` fails the second.

⚠️ **Do not add absence-checked states to `progress_states`.** A first attempt at
this fix added `"running"` to all eight configs, reasoning that `running` is real
gameplay being misread as "no progress". It cannot work and is unsafe:
`progress_states` membership resets only `last_progress_at`, never `blind_streak`
(which resets at `fsm.py`'s `elif m.found:` and nowhere else), so the wall clock was
never what fired; `running` detects `result_marker.png` by **absence** and so never
matches anyway; and `running` is reachable from `probe_friendinfo.on_absent` — the
exact path the 2026-07-31 News livelock rode, meaning a stuck bot would have had its
budget refreshed every lap.

Both detectors are exempt during a recovery. The grace window works by pushing
`last_progress_at` into the future, which silences the wall clock but says nothing
about a streak — and a restart+relogin polls ~99s matching nothing, so without the
exemption the streak stacks a second recovery onto the one still running. Live
`fire #2` read *"229 consecutive polls … only 1s of 300s elapsed"*: proof the wall
clock alone would have stayed quiet for another 299s.

## cd into repo first

```powershell
cd <repo>   # wherever you cloned netrunner (ASCII path — see SETUP.md)
```

## Commands

**Run live, continuous** (long farm — stop with `Ctrl+C`):

```powershell
python main.py --config config/cookierun/coinrun.json
```

**Run live, capped 20 cycles** (short trial):

```powershell
python main.py --config config/cookierun/coinrun.json --max-cycles 20 -v
```

**Dry-run** (no taps, log only — validate FSM):

```powershell
python main.py --config config/cookierun/coinrun.json --dry-run -v
```

## Gift Draw (box opener)

Double-click **`launchers/utility/giftdraw.bat`** — prompts for how many boxes to open, then runs `config/cookierun/giftdraw.json` capped to that many draws (`boxes*5 + 15` cycles — extra headroom for the rescue path below).

Precondition: the **Gift Draw popup already open** (home → tap the Rewards gift-box icon, bottom bar). Loop: tap Draw → pick the yellow box → tap Confirm (finds it via `tap_template`, handles both reward-reveal layouts) → repeat. Auto-stops when draws run out (Draw greys → pick_box times out → closes the popup). `Ctrl+C` to abort early.

Design notes (2026-07-08):

- **Rare treasure popup** — a treasure reward pops a second "Congratulations! Treasure received!" dialog **over** the Gift Draw popup. Its Confirm matches `giftreward_confirm.png` (verified live, score 1.00 at 962,853), but the old config froze anyway: the FSM sat in `gift_draw` whose marker was covered, and its `on_absent` self-loop + `timeout_ms` combo made the engine raise `FsmError` (timeout with a self-goto has no escape target) — bot died with the popup stuck on screen.
- **Fix: absent_retries + rescue** — `gift_draw` and `reward` tolerate absence via `absent_retries`/`absent_wait_ms` (originally hand-written state chains `gift_draw_2/_3`, `reward_2..5`, collapsed 2026-07-16 when the engine got counters) and fall through to a `rescue` state: re-check the Confirm template, tap it if present, else blind-tap (962,853) as backstop for future unknown popups, then verify recovery via `rescue_check` before resuming (or stop cleanly via `done`).
- **Engine gotcha** — `on_absent` goto pointing at the state itself + `timeout_ms` = guaranteed `FsmError` crash when the timeout fires ([src/fsm.py](../src/fsm.py) `_handle_absent`). Self-loop-with-timeout only works when `on_absent` is a dict goto to a *different* state (like `pick_box` → `done`). Since 2026-07-16 the config validator **rejects the trap at load time**, so it can't reach a live run anymore.

Manual equivalent:

```powershell
python main.py --config config/cookierun/giftdraw.json --max-cycles 50
```

## Send-Life (friends list, all Episodes)

Double-click **`launchers/utility/sendlife.bat`** — runs `tools/run_sendlife_loop.py --launch`, which cycles Episodes 1-6 in order, clearing each one's friend list before switching to the next (fixed-preset launcher, no prompt).

Precondition: **home screen** (any Episode selected on entry — the Episode picker is opened and driven automatically, no need to be on the Friends tab already).

Per-Episode loop (`config/cookierun/sendlife.json`, unchanged): scan for any visible Send-Life icon (`tap_template`, so row position doesn't matter) → tap → Confirm the "Send a free Life?" dialog → Confirm "Message sent!" → repeat. When no icon is visible it swipes the list up and re-scans; stops (FSM `stop`) once several consecutive scans past a swipe find nothing (bottom of list).

Between Episodes, `tools/switch_episode.py`'s `switch_episode()` opens the Episode Map (`Episode` button, top-right of home), swipes to the map's left edge (verified via `episode/ep7_banner.png`, not counted — swipe distance isn't pixel-exact), steps right one swipe at a time checking for the target `episode/epN_banner.png` after each, taps it, then taps `Enter` on the confirm dialog. `--order` defaults to `1,2,3,4,5,6`; a failed switch (e.g. banner not found) logs and skips to the next Episode rather than aborting the whole run. `Ctrl+C` to abort early.

Manual equivalent:

```powershell
python tools/run_sendlife_loop.py --launch
# or a custom subset/order:
python tools/run_sendlife_loop.py --order 2,4,6 --launch
```

## Mailbox Send-Life (Mailbox popup — different screen from the Friends-tab bot above)

Double-click **`launchers/utility/sendlife_mailbox.bat`** — runs `config/cookierun/sendlife_mailbox.json`, capped 250 cycles.

Not the same bot as **Send-Life** above: that one drives the home-screen
**Friends tab** list (per-row icon, "Send \<name\> a free Life? (+3 Gift Points)"
then a separate "Message sent!" popup). This one drives the **Mailbox → Lives
tab** popup instead — same game (OvenBreak), different screen and a simpler
flow (no separate "Message sent" step).

Precondition: **Mailbox open, Lives tab selected** (the "Received Lives are
stored for 3 days." list with per-friend "Receive & Send" rows and the green
**"Quick Receive & Send Lives"** banner at the bottom). Loop: tap the banner once
→ a "Send \<name\> a free Life? (+3 Gift Points)" dialog opens → tap Confirm →
the **same dialog instantly re-opens for the next friend** — no "Message sent"
popup in between, unlike the Friends-tab flow. So the loop is just "keep
confirming until the dialog stops reappearing" (live-verified 2026-08-01 across
55+ consecutive sends with zero drift, zero extra popup types). `Ctrl+C` to
abort early.

Design notes (2026-08-01):

- **Confirm dialog marker is name-agnostic** — crops only the "(+3 Gift Points)"
  line, never the "Send \<name\>..." line above it (a name-specific crop would
  miss on literally every friend after the first).
- **`tap_template` everywhere, not `tap_xy`** — the Confirm button and the Quick
  banner are both found by template match each poll, so the tap follows wherever
  the element actually renders instead of a hardcoded pixel.
- **Humanized pacing is mandatory for this bot** (user requirement, applies
  project-wide — see the new "Humanized timing" rule below): `poll_ms` and every
  `wait.ms` are `[min, max]` ranges (fresh random draw per cycle), on top of the
  engine's own per-tap spatial jitter + randomized delay (`src/act.py _jitter`).
  Live dry-run confirmed no two taps in a row land on the same pixel or wait the
  same duration (coords wandered ±5-10px, waits varied 700-1400ms across 8
  consecutive cycles).

Manual equivalent:

```powershell
python main.py --config config/cookierun/sendlife_mailbox.json --max-cycles 250
```

## Add Friends (Find tab)

Double-click **`launchers/utility/addfriend.bat`** — prompts for how many friend requests to send, then runs `config/cookierun/addfriend.json` capped to `friends*5/4 + 8` cycles.

Entry automated: from **home** it taps the Friends icon (1203,465) → Find tab (851,117); if the popup is already on Find it starts straight away. Loop: **Refresh first** (fresh all-green batch), then a fixed-coordinate walk taps each of the 4 rows exactly once (y = 367/529/691/853), then Refresh again → repeat. No natural end — the cycle cap ends the run. `Ctrl+C` to abort early.

Design notes (learned live):
- Every tap raises a center-screen toast — "Friend request sent!" or "This player's friend list is full!" — visually identical cream boxes. A full player's button **stays green**, so a `tap_template` scanner would re-tap them forever; the fixed walk taps them once and moves on (= skip), and Refresh replaces the batch.
- Tapping a dark already-sent button is **not** a no-op — it opens that row's "Friend's Info" screen. Refresh-first guarantees the walk never taps a dark button; `check_find` closes a stray Friend's Info (X at 1640,107) as a safety net.

⚠️ Don't touch the emulator while any bot runs — a screen change mid-flow makes taps land on whatever's on screen (e.g. the Manage/remove-friend list).

Manual equivalent:

```powershell
python main.py --config config/cookierun/addfriend.json --max-cycles 50
```

## Box Farm — Speed, quit at first box (`launchers/boxrun_speed1.bat`)

Double-click **`launchers/boxrun_speed1.bat`** — runs `config/cookierun/boxrun_default.json` (device `127.0.0.1:5557`, unlimited cycles, `Ctrl+C` to stop). Farms **Mystery Boxes**: plays runs, and after each Result opens the Mystery Box screen (`?` boxes picked up mid-run) and collects the reward. Quits each run as soon as one box is banked — the `1` in the name — where `boxrun_speed.bat` plays to death on the same boost.

(Was `launchers/boxrun_default.bat`, archived 2026-08-03, then promoted back on 2026-08-04 under the behaviour-first name. The config file keeps its old `boxrun_default.json` filename.)

**Precondition**: **any episode already selected on home** before starting — the bot only taps `Play!`, it does **not** navigate episode selection, so it farms whichever episode is on home. Switch with `tools/switch_episode.py --episode N`. Configs are named by behaviour (`boxrun_magnet` / `boxrun_default` / `boxrun_toggle`), not by episode.

Differences from `cookierun.json` (the coin grinder), all learned live 2026-07-15:

- **Buys +17% base speed, not Double Coins.** Same Multi-Buy machinery, but the picker pins a different boost. On each shop entry `probe_speed` checks `speedbase17_banner.png` (the `+17% base speed` pill on the right panel; CV: present=1.000, absent ~0.33-0.38). Absent → `buy_speed` taps the pink **Multi** toggle (1649,337) → `picker` (where **+17% base speed is PRE-TICKED** by the game — do NOT tap any row, tapping the ticked row un-ticks it) → **Multi-Buy** (953,899) → the game auto-rolls, spending coins, until the +17% boost lands. `start_run` re-verifies the pill; absent → `retry_buy`. Coins dry mid-roll → `insufficient_coins` (Cancel 770,685, never Confirm) → `force_play`.
- **Taps the Fast Start prompt.** After `check_heart` taps Play, `await_faststart` (2 extra looks via `absent_retries`, ~700ms apart) waits for `Tap to activate Fast Start Boost!` and taps the blue-arrow button `faststart_btn.png` at (985,515). CV: prompt=1.000; mid-run tray icon 0.197 / bonustime 0.255 / shop 0.335 (no false-positive — the green glow + size distinguish it from the small tray icon). Prompt auto-dismisses after a few seconds, so a miss just means no fast-start that run, not a crash.
- **No Cookie Relay Boost.** The coin bot's center-screen relay tap (960,540) in `guard_not_shop` is **removed** — box farming doesn't need it, and it added leaderboard-mistap risk.
- **In-run pattern J→J→S→J** (3 jump : 1 slide per 4-hop cycle) instead of jump-only. `jump_3` is a `slide` (Slide button ~1671,937, ~550ms hold) to clear overhead bars — the one obstacle class a jump can never clear. No per-frame obstacle CV (capture ~850ms is slower than obstacles appear), so the blind mixed cadence covers both pits (jump + engine's 35% double-jump) and bars (slide). **Ratio + slide `hold_ms` are the first knobs to retune after watching a live Episode-3 run.**

New templates added to `templates/cookierun/`: `faststart_btn.png`, `speedbase17_banner.png`. New engine action `slide` (registered in `src/config.py` — the actuator already had it, only the validator whitelist was missing it).

Manual equivalent:

```powershell
python main.py --config config/cookierun/boxrun_default.json
```

## Box Farm — archived variants

These were trimmed from the active set on 2026-07-31 and moved to
`config/cookierun/_archive/` (see its README). The active box-farm set is now
just **`boxrun_default`**, **`boxrun_magnet`**, and **`boxrun_toggle`** (below).

Archived: `boxrun_speed_quit2` · `boxrun_speed_noquit` · `boxrun_passive` ·
`boxrun_passive_3boost` · `boxrun_magnet_quit3`. Each still works — move its JSON
back up to `config/cookierun/` to reactivate. `boxrun_toggle` covers most of
them via flags (relay/jump/slide off, `--quit-after-boxes N`).

## Box Farm — Toggle (`launchers/boxrun_toggle.bat`)

Double-click **`launchers/boxrun_toggle.bat`** — asks 4 questions, then runs `config/cookierun/boxrun_toggle.json` through `tools/run_toggle.py` with those actions patched in/out of the FSM in memory. The JSON on disk never changes — same Mystery Box farm loop as `boxrun_default`/`ep5`/`ep6`, just with each optional action switchable per launch instead of baked into a separate config file per combination.

The prompts (shortened 2026-08-03 — Enter accepts the bracketed default on every line):

| prompt | default | passed as |
|--------|---------|-----------|
| `Fast Start? [y]:` | `y` | `--faststart` |
| `Boost? 0=none 1=magnet 2=speed 3=coins [0]:` | `0` = none | `--boost` |
| `Relic? y=claim n=claim+stop [n]:` | `n` = `stop` | `--relic-mode` |
| `Quit after N boxes? 0=off [0]:` | `0` | `--quit-after-boxes` |

The Relay prompt was **dropped** on 2026-08-04 — the relay is no longer switchable anywhere, so the launcher does not pass `--relay` at all (see the Cookie Relay section below).

Boost is picked **by number**, not by name — an out-of-range answer re-asks instead of falling through to a default.

Two prompts are commented out in the `.bat` rather than deleted:

- **Jump + Slide** — merged into one `JUMPSLIDE` variable that feeds both `--jump` and `--slide`, hardcoded to **`y`**. Uncomment the `set /p "JUMPSLIDE=..."` pair to ask again. Pinning it to `n` used to also break the relay — with no jump/slide the hop states carried only a `goto`, so the engine kept matching the same cached frame and the relay chain never saw the ~2-3s prompt. Each relay stage now takes its own short jittered wait on the absent path, which the engine treats as an acting state and re-grabs after, so the chain refreshes frames on its own regardless of jump/slide (2026-08-04). The warm-up burst still fires on `jump=n + slide=n` for the separate game-side bug where a zero-tap run is not counted at all.
- **Idle** — hardcoded to `n` (no idling between games). Uncomment the `set /p "IDLE=..."` pair to ask again.

`tools/run_toggle.py` is unchanged and still takes `--jump`/`--slide`/`--idle` separately, so any combination the launcher no longer asks for is reachable from the command line. Same for `--relic-mode hoard`: the launcher now offers only `claim`/`stop` (hoard and stop overlapped in practice), but the flag still accepts all three.

**Precondition**: any episode (3/5/6) selected on home before starting — the bot only taps `Play!`, same as the other boxrun bots.

### Cookie Relay — the blind tap never worked (fixed 2026-08-03, live-verified)

Every boxrun/coinrun config carried a blind `relay_tap` at **(960,540)**, fired once per hop. It did nothing, for a simple reason: **there is no relay button on a normal in-run screen.** Measured on live frames, (960,540) has texture 0.00% and std 2.5 — flat gameplay background. A grid scan across 78 mid-run frames from three runs found no intermittent UI element anywhere (best stillness 25.9, where a real control reads near 0), and the partner-count badge at the bottom (avatar + flag, ~521,1009) is an *indicator*, not a button — tapping it mid-run leaves the count unchanged. That badge is also what an earlier fix mistook for the button before reverting to (960,540); both coordinates were wrong.

The real Cookie Relay is a **two-stage prompt that appears whenever a relay partner becomes available — mid-run, not only on death** (see the threshold section below for the live evidence; an earlier version of this line said "only on death", which is why nothing polled the relay outside the hop chain):

| stage | screen | tap | template |
|-------|--------|-----|----------|
| 1 | `Tap to activate Cookie Relay Boost!` + **Continue** / Quit | **(946,433)** — Continue. **Never** Quit at (946,636), which ends the run | `boxrun/relay_prompt_marker.png` (the Continue pill: self=1.000, stage-2=0.346, everything else ≤0.35) |
| 2 | same text + the relay cookie's card | **(980,515)** — the card | `boxrun/relay_prompt2_marker.png` (self=1.000, stage-1=0.367; mid-run **up to 0.464** — not 0.256 as first measured, see the threshold section below) |

Stage 1 is detected by the **Continue pill**, not the prompt text: both stages show the identical sentence, so a text crop scored 1.000 on stage 2 as well (margin ≤0.05) and could not tell them apart. The pill crop separates them by 0.65.

Each hop state (`guard_not_inactive`, `jump_2`, `jump_3`, `jump_4`) routes through `relay_stage1_X → relay_stage2_X → X`, polling at hop cadence because the whole window is only ~2-3 seconds. Stage 2 is reachable directly (stage 1 absent) on purpose: by the time the FSM has walked its guard chain, the Continue tap has often already landed — from the Fast Start spam, or a hop tap — and only the card is left. That is exactly what the live runs showed.

#### Two more poll points outside the hop chain (added 2026-08-04)

Hanging the chain off the hop states alone still lost relays, because **the hop states are not where the FSM sits for large parts of a cycle**. Two windows had no relay check at all, both wide enough to swallow the entire ~2-3s prompt:

| gap | what the FSM is doing | new poll |
|---|---|---|
| `running` → `guard_not_home` → `guard_not_shop` → … | the long guard walk on the way into a run, re-entered from `check_heart` and `await_shop` every cycle | `running` absent → `relay_poll1_running` → `relay_poll2_running` → `guard_not_home` |
| `check_box` (absent) → `check_shop_after_run` → `probe_boostshop` → … | a run just ended **without** a box, so the loop is leaving the run phase and no hop is visited until the next run has started | `check_box` absent → `relay_poll1_check_box` → `relay_poll2_check_box` → `check_shop_after_run` |

Same shape as the hop chain — Continue (946,433), then the card (980,515), jittered fresh-frame wait on both absent paths. Applied to all seven configs (`running` in every one; `check_box` only in `boxrun_default` and `boxrun_toggle`, the two that have that state).

#### Stage 2's threshold: 0.82 was losing ~3 relays in 4 (fixed 2026-08-04)

`relay_prompt2_marker.png` is a **text crop** — the sentence *"Tap to activate Cookie Relay Boost!"* — and the pixels behind that text are **live gameplay**, so its match score swings with whatever is on screen (coin rain, BONUSTIME flash, star trails). The config's global `match_threshold` is 0.82, which turned out to sit *inside* the score range the real prompt produces:

| measurement | prompt on screen | prompt absent |
|---|---|---|
| 83-frame offline scan (Episode 5) | 0.782 · 0.815 · 0.834 | ≤ 0.464 (80 frames) |
| three live runs, relay actually fired (11×) | 0.73 · 0.76 · 0.77 · 0.79 · 0.80 ×4 · 0.83 · 0.87 | — |

So of eleven real prompts, **0.82 would have caught two** — about four relays in five lost. The misses were silent: nothing in the log above DEBUG level, the run simply carried on without the boost. It was never a detection problem — present-vs-absent separates by ~0.27.

Every stage-2 state now pins **`"threshold": 0.62`** (37 states across the seven configs) — 0.11 below the lowest true positive observed, 0.16 above the highest false one. **Stage 1 keeps the global 0.82**: its template is the green `Continue` pill, which never scored above 0.40 on any frame or in any run, so a lower threshold would only invite false positives there.

Where the hits landed also settles whether the new poll points were redundant with the hop chain — they were not:

| state | hits | note |
|---|---|---|
| `relay_poll2_running` | **5** | added 2026-08-04; the hop chain never looks here |
| `relay_stage2_jump_2` | 5 | existing hop chain |
| `relay_stage2_check_box` | 1 | existing hop chain |

The relay prompt also **appears mid-run, not only on death** — the live hits landed while the cookie was still running (`result_marker` 0.32-0.45). An earlier note here claimed it "only appears on death"; that was wrong, and it is part of why polling from `running` matters.

#### Party Run livelock — a screen with no marker at all (fixed 2026-08-06)

The bot sat on Party Run's **"Select a Mode"** screen indefinitely. The log read as perfectly healthy — the guard chain and both relay polls kept transitioning on schedule — because every state simply *missed* and fell through, while the hop taps landed on a menu instead of a run. No template in any config could see that screen, so nothing recovered from it.

It was reachable by accident, from `probe_friendinfo`. That state fired **two blind taps back to back** — (1552,117) then (1633,107) — and only re-checked its marker after both. On any pass where the dialog was already gone, the second tap landed on **home**, where (1633,107) sits inside the Party Run / Episode banner strip.

Two fixes:

| fix | what |
|---|---|
| `probe_friendinfo` never taps **blind** | every tap is either verified (`close_popup` re-reads the frame) or template-matched inside a ROI. Superseded the original "closes once per pass" rule on 2026-08-09 — see below, one coordinate cannot clear two layers |
| new **`guard_not_partyrun`** in the guard chain | `guard_not_news` → `guard_not_partyrun` → `guard_not_inactive`. Detects `home/partyrun_marker.png`, closes at (1820,135), falls through when clear. In all eight farm configs and, since 2026-08-06, the three home-screen errand configs too |

`partyrun_marker.png` is the purple **"Select a Mode" title bar cropped with its background colour** — 1.000 on the screen itself, ≤0.403 on every other frame captured. That 0.6 margin is the difference from `relay_prompt2_marker`, a text-only crop over live gameplay whose margin collapsed to 0.02.

⚠️ **The close button is at (1820,135) — the top-right of the *screen*, not a dialog header.** The first version of this guard tapped (1638,108), measured off the Friend's Info dialog by mistake; on the Party Run frame that point is dark background (BGR 93,53,51). The guard detected the screen correctly and tapped **38 passes in a row without closing it** — a livelock inside the very guard meant to fix a livelock. Measure the button on the screen you are closing, not on a similar-looking one.

##### Both guards close with `close_popup`, not a bare tap (2026-08-06)

Those 38 passes were silent for a structural reason, not a coordinate one: the
guard was `tap_xy` + `goto` itself. A bare tap cannot tell a wrong coordinate from
a slow fade, and self-looping on it logs nothing either way — so a wrong pixel and
a working close read identically. Every other guard in these configs already used
`close_popup` + `verify`, which re-reads the frame after the settle, taps again
while the marker is still up, and `log.warning`s when it gives up.
`guard_not_partyrun` and `probe_friendinfo` now match them.

The value showed up on the first live run. A stacked Friend's dialog produced:

```text
tap (1633,108) → close_popup: 'friendinfo_marker.png' still on screen (score 1.00) — retrying
tap (1635,107) → still on screen (score 1.00) — retrying
WARNING close_popup: 'friendinfo_marker.png' still on screen after 3 attempt(s)
transition probe_friendinfo -> running
```

It said so, then moved on rather than spinning. Measuring that frame corrected a
claim this document used to make:

| dialog | its X | (1633,107) is | frames seen |
|---|---|---|---|
| **Friend's Info** alone | (1638,107), bbox (1598,68,80,78) | the button — the white glyph itself, closes in one tap, 0.974 → 0.343 | 1 |
| **Friend's Cookie** over it | (1570,127), bbox (1500,101,76,79) | covered by that card — BGR(85,85,85), a shadow | 1 (the 08-06 evidence frame) |
| **Friend's Treasure** over it | (1423,88), bbox (1368,50,80,76) | covered the same way | **11** — the common case |

So (1552,117) was never a dead coordinate; it is the *inner* layer's button, and
the earlier measurement that dismissed it was taken on a single-layer dialog where
that point lands on the card. No retry count clears two layers from one coordinate.

The third row is new on 2026-08-14 and came from scanning **all 1,401** archived
`unknown_screens/` frames for `friendinfo_marker`: 12 hits, all hashes distinct, so
11 separate events between 08-03 and 08-11 plus one on 08-14. Every one of the 11
is Friend's **Treasure** over Info at *identical* coordinates. The ROI that shipped
on 2026-08-09 was measured against the single Cookie frame in `docs/evidence/` and
covered only that layout — it scored **0.453 on Treasure, below the 0.82
threshold**, so the inner-X fallback never fired on the variant that actually keeps
happening. `roi=[1360,50,240,110]` now covers both stacked layouts (0.997 Treasure,
1.000 Cookie), ignores the single-layer frame (0.252, and `optional: true` makes
that a silent no-op), and produced **0 false positives across 178 random
non-friendinfo frames**.

⚠️ **Measure a candidate ROI by calling `perceive.find(frame, tmpl, roi=...)`, never
by slicing the frame yourself.** A first attempt at `[1350,50,240,80]` passed a
hand-written slice that padded the box by the template size; `find` crops to exactly
`(x,y,w,h)` and needs the whole 55×55 template to fit *inside* it, so that box
scored 0.169 on the Cookie layout — silently reintroducing the bug it was meant to
fix. `tests/test_run_toggle.py::test_probe_friendinfo_never_taps_blind` now asserts
the template fits around both measured centres, and that assertion is
mutant-verified against the bad box.

Do **not** re-add a second *blind* tap to "cover" the inner layer. That is exactly
the shape that opened Party Run in the first place — the inner tap is legitimate
only because it is ROI-scoped and template-matched.

##### The same popup, third time: `guard_not_friendinfo` (2026-08-14)

`probe_friendinfo`'s hit count across four hours of live log was **zero** while the
player kept reporting the dialog on screen. The reason is the 2026-07-31 News bug
verbatim, for the third popup in a row: Friend's Info opens *mid-run*, where the
loop is walking the `running` guard chain, and `probe_*` states are only reachable
from the probe side. All seven guards missed, `guard_not_inactive.on_absent`
concluded "genuinely mid-run", and the hop taps landed on the dialog.

The archived frames say so directly — the 11 Treasure hits were captured in
`running`, `jump_3`, `relay_stage2_*`: mid-run states, every one.

Fixed by the same shape as `guard_not_news`: a `guard_not_friendinfo` in the chain,
`guard_not_partyrun` → **`guard_not_friendinfo`** → `guard_not_inactive`, carrying
the identical close sequence and ROI as the probe-side state but ending at `running`
rather than `home`, because the run is still live behind the dialog. Added to all
eight farm configs.

The previous version of this section said the state "warns, hands to `running`, and
the next pass finds whichever layer is left". That was wrong about *which* pass:
mid-run there is no next probe pass, which is why the dialog survived for minutes at
a time. The guard is what makes that sentence true.

##### The errand configs got the same guard (2026-08-06)

`addfriend`, `giftdraw` and `sendlife` run on the home screen with the full
template tree, so Party Run was reachable from them for the same reason — and
`addfriend` was worse off than any farm config: `close_info` fires (1640,107) on its
**absent** path, i.e. while it does not know what is on screen at all, seven pixels
from the tap that opened Party Run. Its own note said the screen was "probably" a
Friend's Info; probably is not detected. With no watchdog configured, the
`open_find ↔ close_info` loop had nothing to end it but `--max-cycles`.

All three now check `guard_not_partyrun` on `peel_congrats`'s absent edge — the one
place that sits in front of every blind action in those configs — and carry
`no_progress_goto` (180s) with `recover_unknown` / `recover_unknown_restart`.
Live: `peel_congrats → guard_not_partyrun → tap (1820,134) → open_find`, Party Run
closed before `close_info` could fire.

`sendlife_mailbox` is deliberately excluded: it scopes itself to
`templates/cookierun/mailbox` and drives a popup, so it has no home markers to
guard with, and its chain ends in `stop` rather than looping.

⚠️ **`tools/run_toggle.py` had to change with it.** On the *most common* path of all — a box is banked and `--quit-after-boxes 0` says keep playing — `BoxQuitRunner._run_actions` returned the string `"check_shop_after_run"` directly, which jumped straight past the poll that was just spliced in front of it. It now reads `check_box`'s own absent goto (`_continue_run_target()`), so whoever owns that edge owns the routing. Same failure mode as the state-keyed Play-tap check that broke when `probe_relic` was spliced in — see the note in that method.

**Live-verified:** two runs, relay card tapped twice (`relay_prompt2_marker` 0.98 and 0.84 → `tap (977,517)` / `tap (981,514)`), zero errors. Stage 1 has not yet been caught in the wild for the reason above; its template is verified against the captured prompt frame rather than in-loop.

Applied to **every** cookierun box/coin config — `boxrun_default`, `boxrun_magnet`, `boxrun_speed`, `boxrun_noboost`, `boxrun_relay`, `coinrun`, `boxrun_toggle`. 8 hop-chain relay states each, plus the 2-4 poll states below (`boxrun_default`/`boxrun_toggle` get 4, the rest 2). ⚠️ `boxrun_relay`'s entire reason for existing was doubling the old blind tap — with that tap gone it is now identical to `boxrun_magnet`, and its launcher was deleted.

**The relay can no longer be switched off** (2026-08-04). `--relay y/n` is still *accepted* by `tools/run_toggle.py` so old scripts and `tools/run_episode_loop.py` do not break, but it is **ignored** — there is no `_strip_relay()`. The states are pure detect-then-tap, so with no prompt on screen they fall straight through; configs run through `main.py` never had a way to disable them either.

### Why no toggle-family preset ever bought a boost (fixed 2026-08-02)

Reported as "`boxrun_speed` never buys speed", then "`boxrun_magnet_hoard` never buys magnet either" — same three bugs underneath, all of them in shared code, so every `--boost` value and every preset built on `boxrun_toggle.json` was affected. `boxrun_magnet.json` (its own config, not toggle-based) was never affected.

1. **The `after_play` gate double-tapped Play and closed the shop.** `probe_relic` taps Play, then handed to `after_play`, which re-read `home_play_marker` and treated a match as "the tap missed, go back to home and retap". But Play! shows *through* the boost-shop fade at ~0.87 — so it always looked like a miss, home tapped Play a second time, and the second tap dismissed the shop. `await_shop` then scored 0.4-0.6 and fell through to `running`. `boxrun_magnet` had already removed `after_play` for exactly this reason and says so in its `home` note; toggle kept it. Now `probe_relic` goes straight to `await_shop`, and the Fast Start spam `after_play` used to carry moved to `await_shop`'s absent path (the direct-run case) — the same shape `boxrun_magnet` uses. `after_play` is deleted, not just bypassed.
2. **Every `PROFILES` banner path was missing its `boxrun/` prefix.** `apply_boost` wrote `detect: "magneticaura_banner.png"`, but the file is `templates/cookierun/boxrun/magneticaura_banner.png`. Had the chain ever been reached, it would have crashed with `PerceiveError: template not found` rather than silently skipping — which is why bug 1 hid this one completely. All three profiles were wrong the same way.
3. **The picker's tick templates were missing their `giftdraw/` prefix.** Same class again: `pick_ticked.png` / `pick_unticked.png` live in `templates/cookierun/giftdraw/`. This one *did* surface live, as a fatal after 5 retries, once bug 1 was fixed and the picker was finally reached.

Verified end-to-end afterwards with `--boost magnet` on a clean home: `home → Play → await_shop 0.89 → probe_magnet → buy_magnet (808,878 → 1647,340) → picker 1.00 → untick speed (997,413) → tick magnet (998,557) → Multi-Buy (948,880) → wait_roll → start_run → check_heart → running`. The `PICK` row coordinates were spot-checked against a live picker at the same time: every row reads its tick state correctly (matched row 0.99, others 0.98-1.00 unticked).

### Boost choice (`--boost`, default `magnet`)

The buy chain's *shape* is identical for every boost — `probe_magnet → buy_magnet → picker → wait_roll → start_run → retry_buy` — so one skeleton plus a profile covers all three instead of a config file each. `_BOOST_PROFILES` in `tools/run_toggle.py` holds what actually differs, each value lifted from the config that proved it live:

| `--boost` | banner template | buy taps | Multi-Buy | from |
|-----------|-----------------|----------|-----------|------|
| `magnet` | `boxrun/magneticaura_banner.png` | (810,875) → (1645,340) | (950,880) | `boxrun_magnet` |
| `speed` | `boxrun/speedbase17_banner.png` | (810,875) → (1645,340) | (953,899) | `boxrun_default`, corrected 2026-08-02 |
| `doublecoins` | `boxrun/doublecoins_banner.png` | (755,875) → (1678,305) | (953,899) | `coinrun` |
| `none` | — | — | — | skips the buy chain entirely |

All three open on the HP-Upgrade view and need the Random Boost cell tapped before the Multi toggle. `speed` used to be listed as reaching Multi directly with a single tap — it does not on a shop that opens on HP-Upgrade, where that tap hits HP `Upgrade` and the picker never opens (see the section above). `_apply_boost` still supports a profile with fewer taps than the baseline chain, but no shipped profile uses that path today. `none` takes the same path the old `--magnet n` did: `await_shop`/`boost_shop` route straight to `check_heart`.

`--boost` replaces the old `--magnet y/n`.

What each remaining flag strips when answered `n`:

- **Fast Start (n)** — removes the `faststart_tap` action from `check_heart`/`after_play`'s `on_absent` lists; the Play tap and trailing `goto` stay.
- **Jump (n)** — drops the `jump` action from `jump_2`/`jump_4`/`guard_not_inactive`'s `on_absent` lists, leaving only the Cookie Relay tap (960,540) + `goto`.
- **Slide (n)** — drops the `slide` action from `jump_3`'s `on_absent` list.
- **Relay (n)** — re-points each hop's `goto` past the two-stage relay chain (`relay_stage1_X` → `X`), so the relay states stay in the config but are never entered. Independent of the Jump/Slide flags. Before 2026-08-03 this instead removed a blind `tap_xy(960,540)`; see the Cookie Relay section below for why that tap never did anything.

⚠️ Turning off both Jump and Slide means the run has no obstacle avoidance — the runner will hit the first pit/bar and die almost immediately. Useful only for isolated testing (e.g. verifying the Magnet buy chain alone), not for actual farming.

**Jump=n + Slide=n warm-up burst:** community-reported game bug — a run with zero jump/slide taps the entire way through doesn't get counted by the game at all (no Mystery Box, no reward), even though the bot's blind relay taps kept it technically alive. When both flags are off, `BoxQuitRunner` (see below) fires a one-shot 10-tap alternating jump/slide burst (back-to-back, no extra wait — slide's own ~550ms hold already paces it, ~2.7-3.2s total) the first time it reaches `guard_not_inactive` in a run, then lets the normal `jump_2` loop continue as usual. This is tracked in Python (`self._warmup_done`, reset to `False` every time `run_result` fires) rather than as a config state/goto: `guard_not_inactive` is a housekeeping guard the FSM revisits every ~4 hops for the rest of the run, not a one-time entry point, so an earlier config-goto-based version of this fired the burst every single cycle instead of once — the "bot secretly keeps jumping/sliding mid-loop" bug. The static FSM has no per-run variables, so "first time this run vs. just revisiting the guard chain" can only be tracked at the Python level. Any mode where Jump or Slide is already on skips this entirely.

The patching happens in `tools/run_toggle.py` (`_strip_faststart`, `_disable_magnet`, `_strip_jump`, `_strip_slide`, `_strip_relay`), which loads the config the normal way via `src.config.load`, deep-copies `cfg.states`, mutates the copy, then hands it to `BoxQuitRunner` (a `Runner` subclass covering both this and the box-quit logic below) — the FSM engine itself (`src/fsm.py`) is untouched.

**Quit after N runs-with-a-box (`--quit-after-boxes`, default 0 = never quit early):** `check_box` detects `boxcounter_marker.png` — the `[?] xN` counter that appears once a box is collected — but there's no OCR reading the actual number N off the counter, so the config alone can't tell "1 box this run" from "3 boxes this run", and `boxcounter_marker` **stays on screen for the rest of that run** once it appears. `check_box` gets revisited every ~4 hops for the rest of the run (housekeeping sweep), so counting every match would count one run's box 4+ times in ~10s instead of once — that was a real bug (`_box_counted_this_run` fixes it). `BoxQuitRunner` (a `Runner` subclass in `run_toggle.py`) now counts **how many runs have had at least one box** — one increment per run, on the first `check_box` match after `run_result` resets the flag — and only lets the `quit_run` goto through once that count reaches `quit_after`; earlier matches are redirected to `check_shop_after_run` so the run keeps going. At the default `0` the counter is never consulted — `check_box`'s own goto to `quit_run` always fires, i.e. runs play to natural death/end instead of quitting early. Note this counts *runs*, not total boxes — a run that nets 3 boxes still only advances the counter by 1.

**Relic mode (`--relic-mode`, default `hoard`):** claims the episode's relic once its "Get!" badge appears (`claim`), leaves it un-claimed to keep farming past the badge (`hoard`), or claims it once and then exits the process entirely once home is confirmed clear (`stop` — for a rest/park session). Mutually exclusive with the older `--relic y/n` (`y`=`claim`, `n`=`hoard`); both flags default to hoarding instead of auto-claiming. `boxrun_toggle.bat` deliberately offers only two of the three — `y`→`claim`, `n`→`stop` — since hoarding and stopping both mean "don't keep farming past the badge" from the launcher's point of view; `hoard` stays available from the command line. See `docs/plans/done/PLAN_relic-stop-mode.html` for the arm/consume design and live-verify log.

Manual equivalent:

```powershell
python tools/run_toggle.py --faststart y --boost speed --jump y --slide n --relic-mode claim --quit-after-boxes 2 --launch
```

## Box Farm — No-boost/claim preset (`launchers/archive/run_boxrun_noboost_claim.bat`)

Double-click **`launchers/archive/run_boxrun_noboost_claim.bat`** — zero prompts, fixed preset: Fast Start=y, Boost=none, Jump=y, Slide=y, RelicMode=claim, QuitAfterBoxes=0, Idle=n, unlimited cycles. Same `boxrun_toggle.json` loop as above through `tools/run_toggle.py`, just hardcoded for the combination used most often instead of re-answering the prompts each launch. (It still passes `--relay y`, which is accepted and ignored — the relay is always on now.)

⚠️ Superseded by **`launchers/boxrun_noboost.bat`** for plain no-boost farming: that one runs `boxrun_noboost.json` through `main.py` (play-to-death, no relic claim, no `run_toggle.py`). Keep using this preset only if you want the relic *claimed* as well.

**Precondition**: same as `boxrun_toggle.bat` — any episode selected on home before starting.

## Box Farm — Magnet/hoard preset (`launchers/archive/boxrun_magnet_hoard.bat`)

Double-click **`launchers/archive/boxrun_magnet_hoard.bat`** — zero prompts, fixed preset: Fast Start=y, Boost=magnet, Jump=y, Slide=y, RelicMode=hoard, QuitAfterBoxes=0, Idle=n, unlimited cycles. (Its `--relay y` is accepted and ignored — the relay is always on now.) Same `boxrun_toggle.json` loop through `tools/run_toggle.py`, hardcoded for the magnet+hoard combination instead of re-answering the prompts each launch (and `hoard` is no longer offered by `boxrun_toggle.bat` at all).

**Precondition**: same as `boxrun_toggle.bat` — any episode selected on home before starting.

## Box Farm — Speed, play to death (`launchers/boxrun_speed.bat`) — live-verified 2026-08-02

Double-click **`launchers/boxrun_speed.bat`** — runs `config/cookierun/boxrun_speed.json` directly (unlimited cycles, `Ctrl+C` to stop). Same Mystery Box farm loop as `boxrun_magnet`, with the Magnetic Aura buy chain swapped for **+17% base speed**: `probe_speed`/`start_run` read `speedbase17_banner.png`, `buy_speed` opens the picker, `picker` Multi-Buys at (953,899). Plays each run to death — `boxrun_speed1.bat` is the same boost but quits at the first box.

(Archived 2026-08-03, promoted back to the active tier on 2026-08-04.)

**Precondition**: any episode selected on home before starting — the bot only taps `Play!`.

The one config-level fix this needed:

- **`buy_speed` needs the Random Boost cell tap first, contrary to `src/boost.py`.** The `speed` profile there had `buy_taps: [(1649,337)]` — Multi directly, no cell tap — and `_apply_boost` even dropped the extra tap for it. That is only correct when the shop is *already* on the Random Boost view. This account's shop opens on **HP Upgrade**, where (1649,337) lands on HP `Upgrade` instead: the Random Boost panel never appears, `picker` never matches, and `start_run` times out into `retry_buy` → `buy_speed` forever, re-rolling every ~16s (watched it burn 8 speed stacks, 728→720, before it was killed). So `buy_speed` taps **(810,875) → (1645,340)**, the same two-step magnet uses. `src/boost.py`'s profile was corrected to match — see the toggle-family section below.

(An earlier note here blamed `boxrun_toggle`'s Play tap coordinate for the missing purchases. That was wrong — (1431,963) sits inside the Play button. The real cause was the `after_play` gate, fixed separately; see below.)

Verified end-to-end on a clean home: `home → Play(1652,972) → await_shop 1.00 → probe_speed → buy_speed → picker 1.00 → Multi-Buy → wait_roll (Stop button 1.00 while the game auto-rolls) → speedbase17_banner **1.000** on the shop panel`.

CV scores for `speedbase17_banner.png` (2026-08-02, 1920x1080): equipped **1.000**, shop without it 0.348, home 0.377 — clean separation, no threshold change needed.

⚠️ If you ever point this at an account whose shop opens on the Random Boost view instead, `buy_speed`'s first tap becomes a no-op on an already-correct panel — harmless, but the `src/boost.py` profile would then be the right shape and this config the redundant one.

Manual equivalent:

```powershell
python main.py --config config/cookierun/boxrun_speed.json
```

## Box Farm — No boost (`launchers/boxrun_noboost.bat`) — added 2026-08-04

Double-click **`launchers/boxrun_noboost.bat`** — runs `config/cookierun/boxrun_noboost.json` directly through `main.py` (unlimited cycles, `Ctrl+C` to stop). Same play-to-death Mystery Box loop as `boxrun_speed` / `boxrun_magnet`, with **the entire buy chain removed**: no `probe_*`/`buy_*`/`picker`/`wait_roll` states at all, so it never opens the boost shop and **spends no coins**. Use it to farm boxes overnight without draining the coin balance.

Distinct from the two neighbours it is easy to confuse it with:

| launcher | buys | ends a run |
|---|---|---|
| `boxrun_noboost.bat` | nothing | plays to death |
| `boxrun_speed1.bat` (ex-`boxrun_default`) | +17% speed | quits at the first box |
| `archive/run_boxrun_noboost_claim.bat` | nothing | plays to death, **and claims the relic** |

**Precondition**: any episode selected on home before starting — the bot only taps `Play!`.

```powershell
python main.py --config config/cookierun/boxrun_noboost.json
```

## Box Farm — Relay (`config/cookierun/boxrun_relay.json`, no launcher)

**No `.bat` any more** — `launchers/archive/boxrun_relay.bat` was deleted on 2026-08-04. The config existed for exactly one knob: `relay_tap` fired **twice** per hop instead of once (`"taps": 2` on `jump_2`, `jump_3`, `jump_4`, `guard_not_inactive`), for a higher Cookie Relay trigger rate. That blind tap is gone entirely (see the Cookie Relay section above — it hit empty background and never worked), so the config is now **byte-for-byte equivalent in behaviour to `boxrun_magnet.json`** and there is nothing left for a separate launcher to select.

The JSON is kept only so the older log lines and plan docs that name it still resolve. Run it manually if you want:

```powershell
python main.py --config config/cookierun/boxrun_relay.json
```

**Precondition**: same as `boxrun_magnet.bat` — any episode selected on home before starting.

**STUCK-POPUP FIX (2026-08-13)** — `probe_congrats` (the "Congratulations! Episode N Stage M / 1 Cookie Relay Boost" level-up ticket popup, distinct from the mid-run Cookie Relay Boost prompt) used the engine default `popup_retries=1` (2 taps, 4s @ settle_ms=2000) then blindly went to `home` regardless of whether the close actually took. Live-caught: the marker still scored 1.00 after both attempts, `home`'s own probe missed too (Play! covered by the still-open popup), and the run fell into the 63-state probe chain for ~229s before the 160-poll livelock detector recovered it — this is the "popup takes forever to close" symptom reported live. Fixed: `retries` raised to 3 (4 taps, ~8s, matching giftdraw's rescue-chain grace), and the blind goto-home replaced with a 2-hop `congrats_recheck` / `congrats_recheck2` chain that re-verifies the marker before deciding — one more blind tap on hop 1, then bail to `home` on hop 2 regardless, so a popup that genuinely never closes still can't loop forever. `congrats_recheck`/`congrats_recheck2` are unverified live (no popup was on screen during the fix session to exercise the `on_match` branch) — confirm on the next real hit.

**Watchdog false-positive restarts** — this config's 65-state table outgrew the engine's blind-screen threshold; see [Why the blind threshold is per-config](#why-the-blind-threshold-is-per-config-and-was-160).

## Preconditions (cookierun run-grind)

- Cookie Run open and sitting on **home** (Episode banner + Play!). `start_state: "home"`.
- Resume mid-loop: add `--start-state <state>` (must be a defined state).
- `--device` not needed — the running instance is auto-detected (pin via `.env` `NETRUNNER_DEVICE` only with multiple instances).

### Heart gate (check_heart)

Every Play goes through `check_heart`: `heart_empty.png` = the `|` separator + the **leftmost** heart gray, cropped live at 0 hearts. Hearts deplete right-to-left, so slot 1 is gray only when fully out; the separator anchors the match to slot 1 (gray hearts in slots 2-5 can't false-positive). Scores: 0 hearts = 1.000, any hearts = ~0.75 (margin over the 0.82 threshold is thinner than other templates — re-verify before raising `match_threshold`). The bot **never buys hearts**.

**At 0 hearts (added 2026-08-08, all `boxrun_*`/`coinrun`/`xpstat` configs)**: instead of idling in a 30s self-loop, `check_heart` runs two errands and comes straight back — 0 hearts means 25+ min of dead air before regen, so the wait is put to use on friend-list upkeep:

1. `tap_template boxrun/boostshop_close_btn.png` with `optional: true` — closes the boost shop popup if one is open (this state is reached via `await_shop -> probe_speed` with the shop possibly still open; its own Play-tap path tolerates that because Play shows through the fade, but the errands below need a clean home screen). `optional`, not `close_popup`: this state is also reached with `--boost none` (`boost_skip_goto` skips the shop chain entirely), where no shop popup exists at all — `close_popup`'s unconditional blind tap at the shop's X coordinate would land on whatever home element happens to sit there instead.
2. `run_config config/cookierun/sendlife.json` — clears the Episode already selected on home (no episode switching, so boxrun resumes on the same Episode it left).
3. `run_config config/cookierun/sendlife_mailbox.json` — opens the Mailbox from home itself (`open_mailbox` state, added the same day — the config used to require the Mailbox already open by hand), sweeps the Lives tab, then closes the popup back to home (`close_mailbox` state, same commit — a standalone run used to end deliberately parked on the Lives tab).
4. `goto check_heart` — re-checks: still 0 hearts -> another errand pass; a heart regenerated meanwhile -> falls through to the `on_absent` Play path.

`run_config` is a generic engine action (`src/act.py`/`src/config.py`/`src/fsm.py`): it loads another config's own `Config`, drives it on a fresh `Runner` sharing this run's `device`, and returns once that config's own `stop` fires. No webhook/restarter/further-errand plumbing is passed through, so an errand can't itself schedule a session reset or chain into a nested errand.

**Bug found live during rollout**: the very first version of this chain skipped step 1 — `check_heart` never closed the shop before handing off, so on a real `await_shop -> probe_speed -> check_heart` entry the shop popup was still covering the Mailbox icon and `open_mailbox` hung retrying `tap_template` for 500+ polls. Fixed by adding the optional shop-close tap; live-verified end-to-end afterwards (0 hearts -> shop closed -> Send-Life sent live -> Mailbox opened itself, swept, closed itself -> `check_heart` re-entered clean, heart had regenerated meanwhile -> resumed the Play path) with zero errors across the full cycle.

### Coin guard (probe_dc_owned)

Multi-Buy fires **only when Double Coins is not already equipped**. On every boost-shop entry the loop routes `boost_shop -> probe_dc_owned` first: if `doublecoins_banner.png` (same template `start_run` reads) is already on the right panel — e.g. the bot restarted after a roll landed but before the run consumed it — it skips the whole buy flow and goes straight to the Play gate (`check_heart`). Banner absent -> `buy_boost` opens the Multi picker as before. Design note: banner-present vs -absent scores on the shop screen are ~1.0 vs ~0.36, comfortably split by the 0.82 threshold.

## Flags

| flag | effect |
|------|--------|
| `--adb <path>` | adb binary (default: auto-detect — PATH, then newest LDPlayer install) |
| `--dry-run` | run FSM, send no taps |
| `--max-cycles N` | stop after N poll cycles |
| `--start-state S` | override config `start_state` (resume) |
| `-v` | debug log every match (found + score) |
| `--list-devices` | list attached devices, exit |

**Stop:** `Ctrl+C` — caught, exits clean.

## Logging + Discord alerts (2026-07-10)

Every run now writes a plain-text file log alongside the console, and can push Discord alerts on trouble. Both are opt-in-by-presence — no `.env` means no alerts, but the file log always writes.

- **File log**: `logs/netrunner.log` (active file, same format as console), rotating hourly to `netrunner.log.<YYYY-MM-DD_HH>` — last 72 hours kept, older ones deleted automatically. Path is announced at startup (`logging to logs\...`).
- **Discord alerts**: set `DISCORD_WEBHOOK_URL` in `.env` (copy `.env.example`, fill in a channel webhook URL — Discord channel Settings → Integrations → Webhooks). `.env` is git-ignored; never commit it.
  - 🔴 **critical, `@here`-pinged** — the bot crashed (`FsmError`, e.g. a state timed out with no `on_absent` target). Includes the error and last state.
  - 🟡 **warning** — the FSM stayed on the exact same state for 100 consecutive polls (`_STUCK_STATE_WARN_CYCLES` in `src/fsm.py`), which usually means a livelock rather than an expected long wait (heart regen already self-limits via its own 30s-poll timeout logic, not this counter). Fires once per stuck episode — resets when the state finally changes.
  - A dead/misconfigured webhook never crashes the bot — `send_alert` swallows `requests` errors and just logs a warning.
- Design note: state-repeat tracking counts the literal FSM state string staying constant across polls, not detection score or screen content — a ping-pong between two states (A→B→A→B forever) won't trip it, only a true stuck-on-one-state loop. Threshold picked generously (100 polls × ~600ms ≈ 60s) so it doesn't fire during normal long-wait states.

**Still open**: the "Connection lost! Please check your LTE/5G or Wi-Fi connection." popup (Devsisters' own network-drop dialog, distinct from any FSM-side detection) has no dedicated state/template yet in `config/cookierun/coinrun.json` — it was reproduced live once but the screen moved on before a template could be cropped. Next time it's caught on screen, crop it straight into `templates/cookierun/connlost_marker.png` and wire a `probe_connlost` state into the safety-net probe chain (same pattern as `probe_rankingrewards`/`probe_giftdraw`) ahead of `run_result`, with its `on_match` tapping Confirm and looping back to `home`.
