# SETUP — new machine onboarding

Checklist for getting NetRunner running on a fresh machine. Generic engine docs live in
[README.md](README.md); day-to-day bot commands in [RUN.md](RUN.md).

## 1. Clone location — ASCII path, no OneDrive

⚠️ **Clone to a plain-ASCII path, e.g. `C:\dev\netrunner`.**

- OpenCV (`cv2.imread`/`imwrite`) **fails silently** on paths containing non-ASCII
  characters (e.g. a Thai `เอกสาร`/Documents folder) — templates just never match,
  with no error.
- OneDrive-synced folders churn on `logs/` and `snaps/` writes and can lock files
  mid-run. Keep the repo outside any synced folder.

## 2. Python

- Python **3.10+**
- `pip install -r requirements.txt` (opencv-python, numpy, requests, python-dotenv)

## 3. LDPlayer

1. Install **LDPlayer** (LDPlayer9 and LDPlayer14 both work; adb ships bundled at
   `C:\LDPlayer\LDPlayer<version>\adb.exe`).
2. Create an instance and set resolution **1920x1080, dpi 240** (templates are cropped
   at this resolution — anything else won't match). Instance must be stopped first:

   ```
   ldconsole modify --index <N> --resolution 1920,1080,240
   ```

3. Enable ADB: LDPlayer → Settings → Other → ADB debugging → **Open local connection**.
4. Port formula: `5555 + 2*instance_index` (index 0 → 5555, index 1 → 5557, …).

## 4. `.env` — optional, usually skip this

adb and the emulator are **auto-detected**: the engine finds adb (`PATH`, then newest
`C:\LDPlayer\LDPlayer*\adb.exe`) and scans ports 5555/5557/5559/5561 for the one
running instance. With LDPlayer started, the bots just work — no `.env` needed.

Create `.env` (copy [.env.example](.env.example)) only for these cases:

| key | when |
|-----|------|
| `NETRUNNER_DEVICE` | several instances running at once — pin which one |
| `ADB_PATH` | adb in a non-standard location |
| `DISCORD_WEBHOOK_URL` | want crash/livelock alerts in your Discord channel |

`.env` is git-ignored — never commit it. Precedence: CLI flag > `.env` > auto-detect > config JSON.

## 5. Verify before first run (gate)

```
python -m pytest tests/          # all 57 must pass
python main.py --list-devices    # your instance shows as 'device'
python main.py --config config/cookierun/coinrun.json --dry-run -v --max-cycles 5
```

Dry-run sends no taps — it only proves capture + template matching + FSM wiring work.

## 6. Game-side preconditions

Each bot expects a specific screen before launch — see the per-bot sections in
[RUN.md](RUN.md) (Gift Draw popup open, Episode selected on home, Friends tab, …).

If you play on a **different game account**, template match scores can shift.
Most templates score ~1.0 present vs ~0.35 absent, but `heart_empty.png` has a thin
margin (1.0 vs ~0.75 against the 0.82 threshold) — if the heart gate misbehaves,
re-crop templates from your own screen with `tools/snap.py` (see README "Add a new game").

## 7. House rules (learned the hard way)

- **First live run of any bot = smoke test**: cap it with `--max-cycles`, watch it.
- **Never touch the emulator while a bot runs** — taps land on whatever's on screen.
- **adb stuck `offline` > 1 minute** despite reconnects: don't debug it. Create a fresh
  LDPlayer instance and set resolution — auto-detect picks up the new port by itself
  (clear `NETRUNNER_DEVICE` from `.env` if you had pinned it). (Root cause never
  isolated; two incidents, only a Windows restart or a new instance cleared it.)
- Known open item: the "Connection lost!" popup has no template/state yet — see the
  bottom of [RUN.md](RUN.md) for the crop-and-wire recipe when it's caught on screen.
