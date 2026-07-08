# RUN — cookierun bot cheatsheet

Quick-run commands for this machine. `adb` is **not** on PATH here, so every command passes `--adb` explicitly.

## Verified environment (2026-07-07)

- Python 3.10.11, `opencv-python` 4.13, `numpy` 2.2.6 — installed.
- LDPlayer9 running, `127.0.0.1:5555` in `device` state.
- Bundled adb: `C:\LDPlayer\LDPlayer9\adb.exe`
- Dry-run smoke test passed: `home` marker score 0.95.

## cd into repo first

```powershell
cd "c:\Users\kongp\OneDrive\เอกสาร\Yggdrasil System\netrunner"
```

## Commands

**Run live, continuous** (long farm — stop with `Ctrl+C`):

```powershell
python main.py --config config/cookierun.json --adb "C:\LDPlayer\LDPlayer9\adb.exe"
```

**Run live, capped 20 cycles** (short trial):

```powershell
python main.py --config config/cookierun.json --adb "C:\LDPlayer\LDPlayer9\adb.exe" --max-cycles 20 -v
```

**Dry-run** (no taps, log only — validate FSM):

```powershell
python main.py --config config/cookierun.json --adb "C:\LDPlayer\LDPlayer9\adb.exe" --dry-run -v
```

## Gift Draw (box opener)

Double-click **`run_giftdraw.bat`** — prompts for how many boxes to open, then runs `config/giftdraw.json` capped to that many draws (`boxes*3 + 5` cycles).

Precondition: the **Gift Draw popup already open** (home → tap the Rewards gift-box icon, bottom bar). Loop: tap Draw → pick the yellow box → tap Confirm (finds it via `tap_template`, handles both reward-reveal layouts) → repeat. Auto-stops when draws run out (Draw greys → pick_box times out → closes the popup). `Ctrl+C` to abort early.

Manual equivalent:

```powershell
python main.py --config config/giftdraw.json --adb "C:\LDPlayer\LDPlayer9\adb.exe" --max-cycles 50
```

## Send-Life (friends list)

Double-click **`run_sendlife.bat`** — runs `config/sendlife.json`, capped 300 cycles.

Precondition: **home screen, Friends tab open** (default tab — leaderboard/friends list with Send-Life icons visible). Loop: scan for any visible Send-Life icon (`tap_template`, so row position doesn't matter) → tap → Confirm the "Send a free Life?" dialog → Confirm "Message sent!" → repeat. When no icon is visible it swipes the list up and re-scans; stops automatically once two consecutive scans past a swipe find nothing (bottom of list). `Ctrl+C` to abort early.

Manual equivalent:

```powershell
python main.py --config config/sendlife.json --adb "C:\LDPlayer\LDPlayer9\adb.exe" --max-cycles 300
```

## Add Friends (Find tab)

Double-click **`run_addfriend.bat`** — prompts for how many friend requests to send, then runs `config/addfriend.json` capped to `friends*5/4 + 8` cycles.

Entry automated: from **home** it taps the Friends icon (1203,465) → Find tab (851,117); if the popup is already on Find it starts straight away. Loop: **Refresh first** (fresh all-green batch), then a fixed-coordinate walk taps each of the 4 rows exactly once (y = 367/529/691/853), then Refresh again → repeat. No natural end — the cycle cap ends the run. `Ctrl+C` to abort early.

Design notes (learned live):
- Every tap raises a center-screen toast — "Friend request sent!" or "This player's friend list is full!" — visually identical cream boxes. A full player's button **stays green**, so a `tap_template` scanner would re-tap them forever; the fixed walk taps them once and moves on (= skip), and Refresh replaces the batch.
- Tapping a dark already-sent button is **not** a no-op — it opens that row's "Friend's Info" screen. Refresh-first guarantees the walk never taps a dark button; `check_find` closes a stray Friend's Info (X at 1640,107) as a safety net.

⚠️ Don't touch the emulator while any bot runs — a screen change mid-flow makes taps land on whatever's on screen (e.g. the Manage/remove-friend list).

Manual equivalent:

```powershell
python main.py --config config/addfriend.json --adb "C:\LDPlayer\LDPlayer9\adb.exe" --max-cycles 50
```

## Preconditions (cookierun run-grind)

- Cookie Run open and sitting on **home** (Episode banner + Play!). `start_state: "home"`.
- Resume mid-loop: add `--start-state <state>` (must be a defined state).
- `--device` not needed — config already has `127.0.0.1:5555`.

### Heart gate (check_heart)

Every Play goes through `check_heart`: `heart_empty.png` = the `|` separator + the **leftmost** heart gray, cropped live at 0 hearts. Hearts deplete right-to-left, so slot 1 is gray only when fully out; the separator anchors the match to slot 1 (gray hearts in slots 2-5 can't false-positive). Scores: 0 hearts = 1.000, any hearts = ~0.75 (margin over the 0.82 threshold is thinner than other templates — re-verify before raising `match_threshold`). At 0 hearts the bot waits 30s per poll (timeout 25 min covers regen) and **never buys hearts**. Both branches live-verified 2026-07-08: blocked at 0 hearts, played after a heart regenerated mid-wait.

### Coin guard (probe_dc_owned)

Multi-Buy fires **only when Double Coins is not already equipped**. On every boost-shop entry the loop routes `boost_shop -> probe_dc_owned` first: if `doublecoins_banner.png` (same template `start_run` reads) is already on the right panel — e.g. the bot restarted after a roll landed but before the run consumed it — it skips the whole buy flow and goes straight to the Play gate (`check_heart`). Banner absent -> `buy_boost` opens the Multi picker as before. Design note: banner-present vs -absent scores on the shop screen are ~1.0 vs ~0.36, comfortably split by the 0.82 threshold.

## Flags

| flag | effect |
|------|--------|
| `--adb <path>` | adb binary (required here — not on PATH) |
| `--dry-run` | run FSM, send no taps |
| `--max-cycles N` | stop after N poll cycles |
| `--start-state S` | override config `start_state` (resume) |
| `-v` | debug log every match (found + score) |
| `--list-devices` | list attached devices, exit |

**Stop:** `Ctrl+C` — caught, exits clean.
