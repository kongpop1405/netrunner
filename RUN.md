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

Double-click **`giftdraw.bat`** — prompts for how many boxes to open, then runs `config/cookierun/giftdraw.json` capped to that many draws (`boxes*5 + 15` cycles — extra headroom for the rescue path below).

Precondition: the **Gift Draw popup already open** (home → tap the Rewards gift-box icon, bottom bar). Loop: tap Draw → pick the yellow box → tap Confirm (finds it via `tap_template`, handles both reward-reveal layouts) → repeat. Auto-stops when draws run out (Draw greys → pick_box times out → closes the popup). `Ctrl+C` to abort early.

Design notes (2026-07-08):

- **Rare treasure popup** — a treasure reward pops a second "Congratulations! Treasure received!" dialog **over** the Gift Draw popup. Its Confirm matches `giftreward_confirm.png` (verified live, score 1.00 at 962,853), but the old config froze anyway: the FSM sat in `gift_draw` whose marker was covered, and its `on_absent` self-loop + `timeout_ms` combo made the engine raise `FsmError` (timeout with a self-goto has no escape target) — bot died with the popup stuck on screen.
- **Fix: absent_retries + rescue** — `gift_draw` and `reward` tolerate absence via `absent_retries`/`absent_wait_ms` (originally hand-written state chains `gift_draw_2/_3`, `reward_2..5`, collapsed 2026-07-16 when the engine got counters) and fall through to a `rescue` state: re-check the Confirm template, tap it if present, else blind-tap (962,853) as backstop for future unknown popups, then verify recovery via `rescue_check` before resuming (or stop cleanly via `done`).
- **Engine gotcha** — `on_absent` goto pointing at the state itself + `timeout_ms` = guaranteed `FsmError` crash when the timeout fires ([src/fsm.py](src/fsm.py) `_handle_absent`). Self-loop-with-timeout only works when `on_absent` is a dict goto to a *different* state (like `pick_box` → `done`). Since 2026-07-16 the config validator **rejects the trap at load time**, so it can't reach a live run anymore.

Manual equivalent:

```powershell
python main.py --config config/cookierun/giftdraw.json --max-cycles 50
```

## Send-Life (friends list)

Double-click **`sendlife.bat`** — runs `config/cookierun/sendlife.json`, capped 300 cycles.

Precondition: **home screen, Friends tab open** (default tab — leaderboard/friends list with Send-Life icons visible). Loop: scan for any visible Send-Life icon (`tap_template`, so row position doesn't matter) → tap → Confirm the "Send a free Life?" dialog → Confirm "Message sent!" → repeat. When no icon is visible it swipes the list up and re-scans; stops automatically once two consecutive scans past a swipe find nothing (bottom of list). `Ctrl+C` to abort early.

Manual equivalent:

```powershell
python main.py --config config/cookierun/sendlife.json --max-cycles 300
```

## Add Friends (Find tab)

Double-click **`addfriend.bat`** — prompts for how many friend requests to send, then runs `config/cookierun/addfriend.json` capped to `friends*5/4 + 8` cycles.

Entry automated: from **home** it taps the Friends icon (1203,465) → Find tab (851,117); if the popup is already on Find it starts straight away. Loop: **Refresh first** (fresh all-green batch), then a fixed-coordinate walk taps each of the 4 rows exactly once (y = 367/529/691/853), then Refresh again → repeat. No natural end — the cycle cap ends the run. `Ctrl+C` to abort early.

Design notes (learned live):
- Every tap raises a center-screen toast — "Friend request sent!" or "This player's friend list is full!" — visually identical cream boxes. A full player's button **stays green**, so a `tap_template` scanner would re-tap them forever; the fixed walk taps them once and moves on (= skip), and Refresh replaces the batch.
- Tapping a dark already-sent button is **not** a no-op — it opens that row's "Friend's Info" screen. Refresh-first guarantees the walk never taps a dark button; `check_find` closes a stray Friend's Info (X at 1640,107) as a safety net.

⚠️ Don't touch the emulator while any bot runs — a screen change mid-flow makes taps land on whatever's on screen (e.g. the Manage/remove-friend list).

Manual equivalent:

```powershell
python main.py --config config/cookierun/addfriend.json --max-cycles 50
```

## Box Farm — Speed (`boxrun_default.bat`)

Double-click **`boxrun_default.bat`** — runs `config/cookierun/boxrun_default.json` (device `127.0.0.1:5557`, unlimited cycles, `Ctrl+C` to stop). Farms **Mystery Boxes**: plays runs, and after each Result opens the Mystery Box screen (`?` boxes picked up mid-run) and collects the reward.

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

## Box Farm — Toggle (`boxrun_toggle.bat`)

Double-click **`boxrun_toggle.bat`** — asks 6 questions (Fast Start tap? Which boost to buy? Jump? Slide? Cookie Relay Boost tap? Quit after how many boxes banked?), then runs `config/cookierun/boxrun_toggle.json` through `tools/run_toggle.py` with those actions patched in/out of the FSM in memory. The JSON on disk never changes — same Mystery Box farm loop as `boxrun_default`/`ep5`/`ep6`, just with each optional action switchable per launch instead of baked into a separate config file per combination.

**Precondition**: any episode (3/5/6) selected on home before starting — the bot only taps `Play!`, same as the other boxrun bots.

### Boost choice (`--boost`, default `magnet`)

The buy chain's *shape* is identical for every boost — `probe_magnet → buy_magnet → picker → wait_roll → start_run → retry_buy` — so one skeleton plus a profile covers all three instead of a config file each. `_BOOST_PROFILES` in `tools/run_toggle.py` holds what actually differs, each value lifted from the config that proved it live:

| `--boost` | banner template | buy taps | Multi-Buy | from |
|-----------|-----------------|----------|-----------|------|
| `magnet` | `magneticaura_banner.png` | (810,875) → (1645,340) | (950,880) | `boxrun_magnet` |
| `speed` | `speedbase17_banner.png` | (1649,337) | (953,899) | `boxrun_default` |
| `doublecoins` | `doublecoins_banner.png` | (755,875) → (1678,305) | (953,899) | `coinrun` |
| `none` | — | — | — | skips the buy chain entirely |

Magnet and Double Coins open on the HP-Upgrade view and need the Random Boost cell tapped before the Multi toggle; the `+17% base speed` chain reaches Multi directly, so `_apply_boost` drops the extra tap **and** the wait that was there to let its screen settle. `none` takes the same path the old `--magnet n` did: `await_shop`/`boost_shop` route straight to `check_heart`.

`--boost` replaces the old `--magnet y/n`.

What each remaining flag strips when answered `n`:

- **Fast Start (n)** — removes the `faststart_tap` action from `check_heart`/`after_play`'s `on_absent` lists; the Play tap and trailing `goto` stay.
- **Jump (n)** — drops the `jump` action from `jump_2`/`jump_4`/`guard_not_inactive`'s `on_absent` lists, leaving only the Cookie Relay tap (960,540) + `goto`.
- **Slide (n)** — drops the `slide` action from `jump_3`'s `on_absent` list.
- **Relay (n)** — drops the Cookie Relay Boost `tap_xy(960,540)` from `jump_2`/`jump_3`/`jump_4`/`guard_not_inactive`'s `on_absent` lists, independent of the Jump/Slide flags — the relay tap is a per-hop side action, not tied to either obstacle-avoidance action.

⚠️ Turning off both Jump and Slide means the run has no obstacle avoidance — the runner will hit the first pit/bar and die almost immediately. Useful only for isolated testing (e.g. verifying the Magnet buy chain alone), not for actual farming.

**Jump=n + Slide=n warm-up burst:** community-reported game bug — a run with zero jump/slide taps the entire way through doesn't get counted by the game at all (no Mystery Box, no reward), even though the bot's blind relay taps kept it technically alive. When both flags are off, `BoxQuitRunner` (see below) fires a one-shot 10-tap alternating jump/slide burst (back-to-back, no extra wait — slide's own ~550ms hold already paces it, ~2.7-3.2s total) the first time it reaches `guard_not_inactive` in a run, then lets the normal `jump_2` loop continue as usual. This is tracked in Python (`self._warmup_done`, reset to `False` every time `run_result` fires) rather than as a config state/goto: `guard_not_inactive` is a housekeeping guard the FSM revisits every ~4 hops for the rest of the run, not a one-time entry point, so an earlier config-goto-based version of this fired the burst every single cycle instead of once — the "bot secretly keeps jumping/sliding mid-loop" bug. The static FSM has no per-run variables, so "first time this run vs. just revisiting the guard chain" can only be tracked at the Python level. Any mode where Jump or Slide is already on skips this entirely.

The patching happens in `tools/run_toggle.py` (`_strip_faststart`, `_disable_magnet`, `_strip_jump`, `_strip_slide`, `_strip_relay`), which loads the config the normal way via `src.config.load`, deep-copies `cfg.states`, mutates the copy, then hands it to `BoxQuitRunner` (a `Runner` subclass covering both this and the box-quit logic below) — the FSM engine itself (`src/fsm.py`) is untouched.

**Quit after N runs-with-a-box (`--quit-after-boxes`, default 0 = never quit early):** `check_box` detects `boxcounter_marker.png` — the `[?] xN` counter that appears once a box is collected — but there's no OCR reading the actual number N off the counter, so the config alone can't tell "1 box this run" from "3 boxes this run", and `boxcounter_marker` **stays on screen for the rest of that run** once it appears. `check_box` gets revisited every ~4 hops for the rest of the run (housekeeping sweep), so counting every match would count one run's box 4+ times in ~10s instead of once — that was a real bug (`_box_counted_this_run` fixes it). `BoxQuitRunner` (a `Runner` subclass in `run_toggle.py`) now counts **how many runs have had at least one box** — one increment per run, on the first `check_box` match after `run_result` resets the flag — and only lets the `quit_run` goto through once that count reaches `quit_after`; earlier matches are redirected to `check_shop_after_run` so the run keeps going. At the default `0` the counter is never consulted — `check_box`'s own goto to `quit_run` always fires, i.e. runs play to natural death/end instead of quitting early. Note this counts *runs*, not total boxes — a run that nets 3 boxes still only advances the counter by 1.

Manual equivalent:

```powershell
python tools/run_toggle.py --faststart y --boost speed --jump y --slide n --relay y --quit-after-boxes 2 --launch
```


```

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
