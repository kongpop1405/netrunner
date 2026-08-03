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
  `no_progress_goto`. Reaching none of them for `no_progress_s` (300s) means the
  screen is something the FSM cannot name, whatever it looks like. Opt-in: configs
  without the keys behave exactly as before.
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

Double-click **`launchers/giftdraw.bat`** — prompts for how many boxes to open, then runs `config/cookierun/giftdraw.json` capped to that many draws (`boxes*5 + 15` cycles — extra headroom for the rescue path below).

Precondition: the **Gift Draw popup already open** (home → tap the Rewards gift-box icon, bottom bar). Loop: tap Draw → pick the yellow box → tap Confirm (finds it via `tap_template`, handles both reward-reveal layouts) → repeat. Auto-stops when draws run out (Draw greys → pick_box times out → closes the popup). `Ctrl+C` to abort early.

Design notes (2026-07-08):

- **Rare treasure popup** — a treasure reward pops a second "Congratulations! Treasure received!" dialog **over** the Gift Draw popup. Its Confirm matches `giftreward_confirm.png` (verified live, score 1.00 at 962,853), but the old config froze anyway: the FSM sat in `gift_draw` whose marker was covered, and its `on_absent` self-loop + `timeout_ms` combo made the engine raise `FsmError` (timeout with a self-goto has no escape target) — bot died with the popup stuck on screen.
- **Fix: absent_retries + rescue** — `gift_draw` and `reward` tolerate absence via `absent_retries`/`absent_wait_ms` (originally hand-written state chains `gift_draw_2/_3`, `reward_2..5`, collapsed 2026-07-16 when the engine got counters) and fall through to a `rescue` state: re-check the Confirm template, tap it if present, else blind-tap (962,853) as backstop for future unknown popups, then verify recovery via `rescue_check` before resuming (or stop cleanly via `done`).
- **Engine gotcha** — `on_absent` goto pointing at the state itself + `timeout_ms` = guaranteed `FsmError` crash when the timeout fires ([src/fsm.py](../src/fsm.py) `_handle_absent`). Self-loop-with-timeout only works when `on_absent` is a dict goto to a *different* state (like `pick_box` → `done`). Since 2026-07-16 the config validator **rejects the trap at load time**, so it can't reach a live run anymore.

Manual equivalent:

```powershell
python main.py --config config/cookierun/giftdraw.json --max-cycles 50
```

## Send-Life (friends list)

Double-click **`launchers/sendlife.bat`** — runs `config/cookierun/sendlife.json`, capped 300 cycles.

Precondition: **home screen, Friends tab open** (default tab — leaderboard/friends list with Send-Life icons visible). Loop: scan for any visible Send-Life icon (`tap_template`, so row position doesn't matter) → tap → Confirm the "Send a free Life?" dialog → Confirm "Message sent!" → repeat. When no icon is visible it swipes the list up and re-scans; stops automatically once two consecutive scans past a swipe find nothing (bottom of list). `Ctrl+C` to abort early.

Manual equivalent:

```powershell
python main.py --config config/cookierun/sendlife.json --max-cycles 300
```

## Mailbox Send-Life (Mailbox popup — different screen from the Friends-tab bot above)

Double-click **`launchers/sendlife_mailbox.bat`** — runs `config/cookierun/sendlife_mailbox.json`, capped 250 cycles.

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

Double-click **`launchers/addfriend.bat`** — prompts for how many friend requests to send, then runs `config/cookierun/addfriend.json` capped to `friends*5/4 + 8` cycles.

Entry automated: from **home** it taps the Friends icon (1203,465) → Find tab (851,117); if the popup is already on Find it starts straight away. Loop: **Refresh first** (fresh all-green batch), then a fixed-coordinate walk taps each of the 4 rows exactly once (y = 367/529/691/853), then Refresh again → repeat. No natural end — the cycle cap ends the run. `Ctrl+C` to abort early.

Design notes (learned live):
- Every tap raises a center-screen toast — "Friend request sent!" or "This player's friend list is full!" — visually identical cream boxes. A full player's button **stays green**, so a `tap_template` scanner would re-tap them forever; the fixed walk taps them once and moves on (= skip), and Refresh replaces the batch.
- Tapping a dark already-sent button is **not** a no-op — it opens that row's "Friend's Info" screen. Refresh-first guarantees the walk never taps a dark button; `check_find` closes a stray Friend's Info (X at 1640,107) as a safety net.

⚠️ Don't touch the emulator while any bot runs — a screen change mid-flow makes taps land on whatever's on screen (e.g. the Manage/remove-friend list).

Manual equivalent:

```powershell
python main.py --config config/cookierun/addfriend.json --max-cycles 50
```

## Box Farm — Speed (`launchers/boxrun_default.bat`)

Double-click **`launchers/boxrun_default.bat`** — runs `config/cookierun/boxrun_default.json` (device `127.0.0.1:5557`, unlimited cycles, `Ctrl+C` to stop). Farms **Mystery Boxes**: plays runs, and after each Result opens the Mystery Box screen (`?` boxes picked up mid-run) and collects the reward.

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

Double-click **`launchers/boxrun_toggle.bat`** — asks 5 questions, then runs `config/cookierun/boxrun_toggle.json` through `tools/run_toggle.py` with those actions patched in/out of the FSM in memory. The JSON on disk never changes — same Mystery Box farm loop as `boxrun_default`/`ep5`/`ep6`, just with each optional action switchable per launch instead of baked into a separate config file per combination.

The prompts (shortened 2026-08-03 — Enter accepts the bracketed default on every line):

| prompt | default | passed as |
|--------|---------|-----------|
| `Fast Start? [y]:` | `y` | `--faststart` |
| `Boost? 0=none 1=magnet 2=speed 3=coins [0]:` | `0` = none | `--boost` |
| `Relay Boost? [y]:` | `y` | `--relay` |
| `Relic? y=claim n=claim+stop [n]:` | `n` = `stop` | `--relic-mode` |
| `Quit after N boxes? 0=off [0]:` | `0` | `--quit-after-boxes` |

Boost is picked **by number**, not by name — an out-of-range answer re-asks instead of falling through to a default.

Two prompts are commented out in the `.bat` rather than deleted:

- **Jump + Slide** — merged into one `JUMPSLIDE` variable that feeds both `--jump` and `--slide`, hardcoded to `n`. Uncomment the `set /p "JUMPSLIDE=..."` pair to ask again. (With both off, the warm-up burst below is what keeps runs counting.)
- **Idle** — hardcoded to `n` (no idling between games). Uncomment the `set /p "IDLE=..."` pair to ask again.

`tools/run_toggle.py` is unchanged and still takes `--jump`/`--slide`/`--idle` separately, so any combination the launcher no longer asks for is reachable from the command line. Same for `--relic-mode hoard`: the launcher now offers only `claim`/`stop` (hoard and stop overlapped in practice), but the flag still accepts all three.

**Precondition**: any episode (3/5/6) selected on home before starting — the bot only taps `Play!`, same as the other boxrun bots.

### Cookie Relay — the blind tap never worked (fixed 2026-08-03, live-verified)

Every boxrun/coinrun config carried a blind `relay_tap` at **(960,540)**, fired once per hop. It did nothing, for a simple reason: **there is no relay button on a normal in-run screen.** Measured on live frames, (960,540) has texture 0.00% and std 2.5 — flat gameplay background. A grid scan across 78 mid-run frames from three runs found no intermittent UI element anywhere (best stillness 25.9, where a real control reads near 0), and the partner-count badge at the bottom (avatar + flag, ~521,1009) is an *indicator*, not a button — tapping it mid-run leaves the count unchanged. That badge is also what an earlier fix mistook for the button before reverting to (960,540); both coordinates were wrong.

The real Cookie Relay is a **two-stage prompt that only appears on death**:

| stage | screen | tap | template |
|-------|--------|-----|----------|
| 1 | `Tap to activate Cookie Relay Boost!` + **Continue** / Quit | **(946,433)** — Continue. **Never** Quit at (946,636), which ends the run | `boxrun/relay_prompt_marker.png` (the Continue pill: self=1.000, stage-2=0.346, everything else ≤0.35) |
| 2 | same text + the relay cookie's card | **(980,515)** — the card | `boxrun/relay_prompt2_marker.png` (self=1.000, stage-1=0.367, mid-run=0.256) |

Stage 1 is detected by the **Continue pill**, not the prompt text: both stages show the identical sentence, so a text crop scored 1.000 on stage 2 as well (margin ≤0.05) and could not tell them apart. The pill crop separates them by 0.65.

Each hop state (`guard_not_inactive`, `jump_2`, `jump_3`, `jump_4`) now routes through `relay_stage1_X → relay_stage2_X → X`, polling at hop cadence because the whole window is only ~2-3 seconds. Stage 2 is reachable directly (stage 1 absent) on purpose: by the time the FSM has walked its guard chain, the Continue tap has often already landed — from the Fast Start spam, or a hop tap — and only the card is left. That is exactly what the live runs showed.

**Live-verified:** two runs, relay card tapped twice (`relay_prompt2_marker` 0.98 and 0.84 → `tap (977,517)` / `tap (981,514)`), zero errors. Stage 1 has not yet been caught in the wild for the reason above; its template is verified against the captured prompt frame rather than in-loop.

Applied to `boxrun_magnet`, `boxrun_speed`, `boxrun_relay`, `coinrun`, `boxrun_toggle`. ⚠️ `boxrun_relay`'s entire reason for existing was doubling the old blind tap — with that tap gone it is now identical to `boxrun_magnet`.

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
python tools/run_toggle.py --faststart y --boost speed --jump y --slide n --relay y --relic-mode claim --quit-after-boxes 2 --launch
```

## Box Farm — No-boost/claim preset (`launchers/run_boxrun_noboost_claim.bat`)

Double-click **`launchers/run_boxrun_noboost_claim.bat`** — zero prompts, fixed preset: Fast Start=y, Boost=none, Jump=y, Slide=y, **Relay=y**, RelicMode=claim, QuitAfterBoxes=0, Idle=n, unlimited cycles. (Relay flipped from `n` to `y` on 2026-08-03, once the relay stopped being a blind no-op tap and became the real two-stage prompt chain — see the Cookie Relay section above.) Same `boxrun_toggle.json` loop as above through `tools/run_toggle.py`, just hardcoded for the combination used most often instead of re-answering the prompts each launch.

**Precondition**: same as `boxrun_toggle.bat` — any episode selected on home before starting.

## Box Farm — Magnet/hoard preset (`launchers/boxrun_magnet_hoard.bat`)

Double-click **`launchers/boxrun_magnet_hoard.bat`** — zero prompts, fixed preset: Fast Start=y, Boost=magnet, Jump=y, Slide=y, Relay=y, RelicMode=hoard, QuitAfterBoxes=0, Idle=n, unlimited cycles. Same `boxrun_toggle.json` loop through `tools/run_toggle.py`, hardcoded for the magnet+hoard combination instead of re-answering the prompts each launch (and `hoard` is no longer offered by `boxrun_toggle.bat` at all).

**Precondition**: same as `boxrun_toggle.bat` — any episode selected on home before starting.

## Box Farm — Speed (`launchers/boxrun_speed.bat`) — live-verified 2026-08-02

Double-click **`launchers/boxrun_speed.bat`** — runs `config/cookierun/boxrun_speed.json` directly (unlimited cycles, `Ctrl+C` to stop). Same Mystery Box farm loop as `boxrun_magnet`, with the Magnetic Aura buy chain swapped for **+17% base speed**: `probe_speed`/`start_run` read `speedbase17_banner.png`, `buy_speed` opens the picker, `picker` Multi-Buys at (953,899).

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

## Box Farm — Relay preset (`launchers/boxrun_relay.bat`)

Double-click **`launchers/boxrun_relay.bat`** — runs `config/cookierun/boxrun_relay.json` directly (not through `run_toggle.py`), unlimited cycles, `Ctrl+C` to stop. A copy of `boxrun_magnet.json` with exactly one change: **`relay_tap` fires twice per hop instead of once** (`"taps": 2` on all four call sites — `jump_2`, `jump_3`, `jump_4`, `guard_not_inactive`), for a higher Cookie Relay Boost trigger rate. Repeat taps are paced by `Act.relay_gap_s` (0.12s). Everything else — states, coords, Magnetic Aura buy chain, guard chain — is unchanged from `boxrun_magnet`; see that config's `_note` fields for the reasoning behind each state.

The relay button has no template and is a no-op when no partner is ready, so extra taps cost nothing but the ~120ms gap; `relay_taps` in `src/act.py` is the equivalent global knob for every other bot.

**Precondition**: same as `boxrun_magnet.bat` — any episode selected on home before starting.

## Preconditions (cookierun run-grind)

- Cookie Run open and sitting on **home** (Episode banner + Play!). `start_state: "home"`.
- Resume mid-loop: add `--start-state <state>` (must be a defined state).
- `--device` not needed — the running instance is auto-detected (pin via `.env` `NETRUNNER_DEVICE` only with multiple instances).

### Heart gate (check_heart)

Every Play goes through `check_heart`: `heart_empty.png` = the `|` separator + the **leftmost** heart gray, cropped live at 0 hearts. Hearts deplete right-to-left, so slot 1 is gray only when fully out; the separator anchors the match to slot 1 (gray hearts in slots 2-5 can't false-positive). Scores: 0 hearts = 1.000, any hearts = ~0.75 (margin over the 0.82 threshold is thinner than other templates — re-verify before raising `match_threshold`). At 0 hearts the bot waits 30s per poll (timeout 25 min covers regen) and **never buys hearts**. Both branches live-verified 2026-07-08: blocked at 0 hearts, played after a heart regenerated mid-wait.

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
