# Utility launchers

One-off chores that are not farm runs — they do a bounded job and exit, rather
than looping until `Ctrl+C`.

| Launcher | What it does | Cycle cap |
| --- | --- | --- |
| `giftdraw.bat` | opens gift boxes; prompts for how many | `boxes*5 + 15` |
| `sendlife.bat` | sends free lives down the friend list | 300 |
| `sendlife_mailbox.bat` | claims lives from the mailbox | 250 |
| `addfriend.bat` | sends friend requests; prompts for how many | `friends*5/4 + 8` |

Double-click works as-is, and **moving a file needs no edit**: since 2026-08-06
every launcher walks up from its own location until it finds `main.py` rather
than counting `..` against how deep it sits. Anywhere inside the project works;
outside it, the launcher says so and exits.

Per-launcher detail: `docs/RUN.md`.
