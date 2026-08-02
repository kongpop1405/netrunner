# Archived box-farm configs

Kept for reference, not in active use. As of 2026-07-31 the active box-farm set
is just three: **`boxrun_toggle`** (flags asked at run time), **`boxrun_speed`**,
and **`boxrun_magnet`** — everything else lives here.

These are complete, working configs (they lint clean and were live-tested); they
were archived to trim the active set, not because anything is wrong with them.

| Config | What it does | Why archived |
| --- | --- | --- |
| `boxrun_speed_quit2.json` | +17% Speed, jump-hop, quit after 2 boxes | superseded by `boxrun_speed` + `--quit-after-boxes` |
| `boxrun_speed_noquit.json` | +17% Speed, no relay, never quits early | rarely used long-run variant |
| `boxrun_passive.json` | no boost, passive guard-loop run | covered by toggle (jump/slide/relay off) |
| `boxrun_passive_3boost.json` | buys 3 shop-tile boosts, passive run (was `magnet_v2`) | niche 3-boost setup |
| `boxrun_magnet_quit3.json` | Magnetic Aura, passive run, quit at 3 boxes | ep6-counter-bound; use `boxrun_magnet` instead |

`launchers/` holds the `.bat` files that pointed at these; `tools/` holds
`run_boxrun_speed_quit2.py` (the quit-after-2 launcher script). Move a config
back up to `config/cookierun/` to reactivate it — nothing else needs changing,
the engine finds it by path.

The bot comparison — including these archived configs and the `guard loop`
in-run shape they use — is in `docs/flow/COMPARE_bots.html`. Per-state SVG
graphs: `python tools/lint_config.py --svg docs/graphs <config>.json`.
