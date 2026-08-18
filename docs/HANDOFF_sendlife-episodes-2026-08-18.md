# Handoff — Send-Life across all Episodes + mailbox cap (2026-08-18)

Repo: `C:\dev\netrunner` — CookieRun OvenBreak farming bot (LDPlayer CV+ADB FSM).
Branch `main`, clean, synced with `origin/main` (`git rev-list --left-right --count origin/main...main` = `0 0`).
Tests: **405 passed** (`python -m pytest -q`).
Bot at handoff time: running `config/cookierun/boxrun_speed.json` (PID will
differ) — see *Restarting the bot* below.
Monitors: **armed overnight** (log filter + `tools/screen_watch.py`).

Everything below was verified against the live device or the repo, not recalled.
Where something is **unproven**, it says so explicitly — do not upgrade those to
"working" without running them.

---

## 1. What the user asked for, in order

1. **Send lives to friends during the heart-empty wait**, instead of only
   receiving passively via the mailbox. *(done, live-verified)*
2. **Do it for every Episode, not just the selected one** — the friend list is
   per-Episode. *(implemented; partially live-verified, see §4)*
3. **Do not auto-buy hearts with diamonds.** Explicitly refused by the user —
   the wait is filled with friend-list upkeep instead. **Do not add this.**
4. **If the mailbox has fewer than 30 items, skip collecting and go send hearts
   immediately** — don't wait for the mailbox to drain. *(done, see §3)*

Standing mandate for this session (from earlier): monitor autonomously, fix bugs
found, and prevent recurrence. Git autonomy is granted for **this repo only**
(commit/push/branch/tag without asking; destructive ops still need approval).

---

## 2. Shipped commits (all merged to `main` and pushed)

| Commit | What |
|---|---|
| `d84c6d2` | `feat(heart)`: `run_config` takes `episodes`; Runner switches per Episode and restores the original |
| `b6b357a` | `fix(guards)`: connection-lost checked on the path a *matching* home takes |
| `bef40fd` | `feat(mailbox)`: `max_visits` cap (30 confirms) + re-cropped episode label marker |
| `cba3d8d` | `fix(episode)`: `switch_episode` polls for home before tapping and after Enter |

Earlier the same day (already on `main`): raw-`screencap` capture speedup,
Send-Life timing trims, mailbox empty-list livelock fix.

---

## 3. Current behaviour of the heart-empty path

`check_heart` (present in all 8 farm configs — `boxrun_*`, `coinrun`, `xpstat`)
fires **only at 0 hearts**. `boxrun/heart_empty.png` crops the `|` separator plus
the leftmost heart, which is grey only when all 5 are spent (0 hearts scores
1.000; 1–3 hearts ~0.75 against the 0.82 threshold — the note in the config says
do not raise the threshold, the margin is thin).

On match, in order:

```
tap boostshop close (optional)
run_config sendlife_mailbox.json  (no episodes — single pass)
goto mailbox_count_gate
timeout_ms = 5,700,000  (95 min)

mailbox_count_gate  (visits_under: confirm_loop < 30)
  on_match  (drained)  -> run_config sendlife.json episodes=[1..7] -> check_heart
  on_absent (hit cap)  -> check_heart
```

**Order flipped 2026-08-19** (user request): the sweep runs first and Send-Life
only follows when it came up short. The count cannot be known before opening the
Mailbox, so it has to come from confirms actually made — see §"Why a confirm
count" below, which is now the mechanism the gate reads, not just a cap.

**The `<30` rule** lives in `config/cookierun/sendlife_mailbox.json`:
`confirm_loop` has `max_visits: 30` → `max_visits_goto: "done"`.

Why a confirm count and not a mailbox count: the Lives tab shows rows, not a
total, and the envelope badge on home counts Notices+Rewards, **not** Lives to
receive (verified against a live frame: badge read 5 while the Lives tab said
"No Lives received!"). One confirm == one row, so capping confirms is the same
quantity, one item at a time. Under 30 the loop still ends by itself exactly as
before — measured live: **3 confirms, 19s end to end** including opening and
closing the Mailbox.

`max_visits` is a new engine feature (`src/fsm.py`, validated in `src/config.py`):
counted **on state re-entry, not per poll**, because a state that polls several
times per item would otherwise cap having done far fewer than the limit. Neither
existing watchdog could express this — both ask "has the bot stopped
progressing", and a sweep working a long list is progressing on every pass.

---

## 4. What is proven and what is NOT

**Proven live:**

- Episode detector: `src/episode.py` `detect_current_episode()` — marker 1.000,
  digit read correct on 4/4 home frames.
- The errand reaches the multi-episode path:
  `errand: sendlife.json across episodes [1,2,3,4,5,6,7] (currently on 1)`.
- Episode 1 Send-Life completed in **246s**; Episode 3 in 14s.
- `switch_episode` after the fix: **3 real switches (3→2→3→1), all OK, ~25s
  each**, each landing confirmed independently by `detect_current_episode`.
  Run with the bot stopped, via `/tmp/live_switch.py`-style direct calls.
- Connection-lost guard fires on a matching home:
  `home -> verify_no_connectionlost -> restart_app`, recovery in ~3.5 min.

**NOT proven — this is the next session's job:**

- **A full 7-Episode pass has never completed.** Best so far: 3 episodes done
  across two attempts, both *before* the `switch_episode` fix.
- **`max_visits` has never fired live** (`cap_hits=0` in every log). Every real
  sweep so far had fewer than 30 items, so the cap has only been exercised by
  unit tests.
- **The episode restore has never succeeded in-flow.** It failed twice, both
  pre-fix, and the alert correctly fired:
  `errand: could NOT restore Episode 1: Episode Map did not open` — which is why
  the bot was later found sitting on Episode 3 instead of 1. The
  `switch_episode` fix addresses the cause, but no post-fix heart-empty cycle has
  run yet.

### How to verify the remaining items

Wait for a real heart-empty cycle (hearts regenerate ~25 min each; do **not**
force it by buying), then check:

```bash
cd /c/dev/netrunner
grep -E "across episodes|on Episode|Episode [0-9]+ done|restored|could NOT restore|switch to Episode .* failed|max_visits" logs/netrunner.log
```

> **Read the timestamps.** `logs/netrunner.log` still contains the **pre-fix**
> failures from **20:45–20:57** — six `switch to Episode N failed` plus two
> `could NOT restore Episode 1`. Those are the bug described in §5, already fixed
> in `cba3d8d`. The fix went live at the restart just after **21:10**, so only
> lines timestamped later than that say anything about the current code. Logs
> rotate hourly, so also check `logs/netrunner.log.2026-08-18_*` when looking
> back.

Success looks like: 7 × `on Episode N` + `Episode N done`, then
`Episode 1 restored`. A `switch to Episode N failed` **dated after 21:10** is a
real regression in `tools/switch_episode.py` — read §5 before assuming the marker
is at fault.

---

## 5. Trap: "Episode Map did not open" is usually NOT a marker problem

This message cost a lot of time today. It is emitted when the blind tap on the
Episode button doesn't land on the map — and the most common reason is that the
screen **was not home**, because a *previous* switch left the game mid-load.

Evidence from the live logs: Episode 2 raised `home_play_marker not visible after
Enter`, and then 4/5/6/7 all failed at map-open — while Episode 3, which happened
to land cleanly, switched fine. Manually tapping the same coordinate `(1280,175)`
on a settled home opened the map at **1.000 every time**.

The fix polls for home both before tapping (`HOME_BEFORE_TAP_S = 15.0`) and after
Enter (`HOME_AFTER_ENTER_S = 12.0`) instead of a single grab at a fixed 2.0s.

**Two wrong theories I burned time on — do not repeat them:**

1. *Scroll momentum from Send-Life's exit swipe swallows the tap.* I "reproduced"
   this at 0s/1s/2.5s delays — **the result was garbage**: the bot was running and
   racing me on the same device. With the bot stopped, both the control and the
   after-swipe case opened the map at 1.000.
2. *The map marker is stale like the label marker was.* It is not — it scores
   1.000 on a settled home.

**Rule that follows: stop the bot before any manual device experiment.**
`ps`/`tasklist` won't find it by name; use the PowerShell command in §7.

---

## 6. Key files

| Path | Role |
|---|---|
| `src/episode.py` | `detect_current_episode()`, label marker + digit offset constants. Shared by the Runner and `tools/run_episode_loop.py` — one definition, do not re-fork it. |
| `src/fsm.py` | `_run_errand(path, episodes)`, `_run_errand_per_episode()`, `max_visits` enforcement |
| `src/config.py` | validation for `run_config.episodes` and `max_visits` / `max_visits_goto` |
| `src/act.py` | `run_config` action forwards `episodes` |
| `tools/switch_episode.py` | the map navigation + the home-wait fix |
| `config/cookierun/sendlife.json` | Friends-tab Send-Life (19 states); timing trimmed today |
| `config/cookierun/sendlife_mailbox.json` | Mailbox Lives sweep; holds the 30-confirm cap |
| `config/cookierun/*.json` (8 farm configs) | each carries `check_heart` + `mailbox_count_gate` with the same chain |
| `tests/test_switch_episode.py` | new; the home-precondition and post-Enter polling |
| `templates/cookierun/home/episode_label_marker.png` | re-cropped today; see §8 |

`docs/reports/` is untracked on purpose (an earlier session's local HTML report).
**The user explicitly requires reports as local HTML files, never claude.ai
Artifacts.**

---

## 7. Restarting the bot

Config changes are read from disk per `run_config`, so a config-only edit needs no
restart. **Any change under `src/` does** — Python loads modules once.

The bot was switched to **`boxrun_speed`** at the end of this session (user
request, 2026-08-18 ~22:50) — it was on `coinrun` for most of the work above.
Both configs carry every fix; `check_heart` + `mailbox_count_gate` are identical across all 8.

```powershell
# find and stop (match either config — the running one may differ)
$p = Get-CimInstance Win32_Process -Filter "Name like '%python%'" |
     Where-Object { $_.CommandLine -like '*boxrun_speed*' -or $_.CommandLine -like '*coinrun*' }
if ($p) { $p | ForEach-Object { Stop-Process -Id $_.ProcessId -Force } }

# start (omit --launch when LDPlayer is already up)
Start-Process -FilePath "C:\Users\kongp\AppData\Local\Microsoft\WindowsApps\python.exe" `
  -ArgumentList "main.py","--config","config/cookierun/boxrun_speed.json" `
  -WorkingDirectory "C:\dev\netrunner" -WindowStyle Hidden
```

Device is `127.0.0.1:5555` (there is also an `emulator-5554` serial for the same
LDPlayer instance — same frames, not a bug).

Killing the bot to debug is pre-authorised by the user; just say so afterwards.

---

## 8. Conventions that bit me today

- **`cv2.imread` fails silently on the bash-style `/c/Users/...` path.** Use the
  Windows form `C:/Users/...`. Same for `imwrite`.
- **A verify script that returns 0 findings may just be broken.** Two of my
  `max_visits` tests passed against mutants because they asserted on the value
  the config echoes back rather than counting real confirms. I rewrote them to
  count `transition loop -> loop`, and both mutants were then caught. Mutant-test
  every checker before trusting a green run.
- **A marker cropped from a dimmed frame silently under-scores.** The episode
  label was cropped through a "Connection lost!" scrim → 0.690 vs the 0.82
  threshold, so `detect_current_episode` returned `None` on every real frame and
  the errand skipped itself 5 times in a row. Check strip brightness before
  cropping (the clean frame measured 66 mean, the dimmed one 25).
- **Don't trust `grep -c` for per-item counts** and don't trust a single log file
  — logs rotate hourly (`logs/netrunner.log.2026-08-18_20`), so a grep over just
  `netrunner.log` can report 0 for something that definitely happened.

---

## 9. Suggested next steps

1. Restart monitoring (log filter on `WARNING|ERROR|switch to Episode|max_visits|
   Episode .* done|restored`, plus the screen watcher) and wait for a natural
   heart-empty cycle.
2. Confirm the three unproven items in §4. Report the real per-episode timings —
   the `timeout_ms` budget currently assumes 246s/episode worst case, giving
   2.76× headroom against the 95-min ceiling.
3. If a 7-episode pass proves much slower than budgeted, the ceiling is the thing
   to revisit — a too-tight ceiling is what got Send-Life removed on 2026-08-16
   in the first place (`1,554,406ms >= 1,500,000ms`).
