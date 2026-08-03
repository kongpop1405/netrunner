# Utility launchers

One-off chores that are not farm runs — they do a bounded job and exit, rather
than looping until `Ctrl+C`.

| Launcher | What it does | Cycle cap |
| --- | --- | --- |
| `giftdraw.bat` | opens gift boxes; prompts for how many | `boxes*5 + 15` |
| `sendlife.bat` | sends free lives down the friend list | 300 |
| `sendlife_mailbox.bat` | claims lives from the mailbox | 250 |
| `addfriend.bat` | sends friend requests; prompts for how many | `friends*5/4 + 8` |

Double-click works as-is. Each file's `cd /d "%~dp0..\.."` climbs two levels to
the repo root — one deeper than the launchers at `launchers/`, which use
`"%~dp0.."`. **Move a file back up and its `cd` has to change back too.**

Per-launcher detail: `docs/RUN.md`.
