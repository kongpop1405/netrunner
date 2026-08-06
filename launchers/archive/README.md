# Archived launchers

Box-farm `.bat` files that are no longer part of the day-to-day set. They still
work — nothing here is broken — they were moved out to keep `launchers/` down to
what actually gets double-clicked.

The active set at the root is `boxrun_toggle.bat` (flags asked at run time),
`boxrun_magnet.bat`, and `coinrun.bat`.

| Launcher | What it does | Why archived |
| --- | --- | --- |
| `boxrun_default.bat` | speed +17%, quits at the first box | `boxrun_speed` + `--quit-after-boxes 1` covers it; the name says "default" but the behaviour is not |
| `boxrun_speed.bat` | speed +17%, plays to death | `boxrun_toggle` + `--boost speed` covers it |
| `boxrun_relay.bat` | Magnetic Aura, played to death | existed only to double the old blind relay tap — that tap was proven a no-op on 2026-08-03, so this is now identical to `boxrun_magnet` |
| `boxrun_magnet_hoard.bat` | preset: magnet + relic=hoard | preset over `boxrun_toggle.json`; still the only one-click way to get `--relic-mode hoard` |
| `run_boxrun_noboost_claim.bat` | preset: no boost + relic=claim | preset over `boxrun_toggle.json`, reachable from `boxrun_toggle.bat` prompts |

## Running one from here

Double-click works as-is, and **moving a file needs no edit**: since 2026-08-06
every launcher walks up from its own location until it finds `main.py`, instead
of counting `..` against how deep it sits. Put one of these anywhere inside the
project and it still runs; put it outside and it says so and exits rather than
failing on a missing `config/`.

(Before that, each file hardcoded its depth — `"%~dp0..\.."` here versus
`"%~dp0.."` at `launchers/` — and every folder move silently broke one until
somebody double-clicked it.)

Bot comparison including these: `docs/flow/COMPARE_bots.html`. Per-launcher
detail: `docs/RUN.md`.
