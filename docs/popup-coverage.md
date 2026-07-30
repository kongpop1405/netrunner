# Popup coverage

What the farm loop can dismiss, and what still stalls it. Every popup that
covers `home` blocks the Play button, so an unhandled one costs the whole
session until the livelock warning fires and someone looks.

## Handled

Each of these has a probe state whose `detect` is the popup's own marker and
whose dismiss goes through `close_popup` — the tap is repeated while the marker
is still on screen instead of assumed to have landed.

| Popup | Marker | Notes |
| --- | --- | --- |
| Daily Check-in | `dailycheckin_marker.png` | once per day at launch |
| Power+ Treasure Rewards | `treasurereward_marker.png` | queues right after check-in |
| Congratulations | `congrats_marker.png` | level-up ticket |
| Level Up | `levelup_marker.png` | separate from Congratulations |
| Send \<friend> a Life? | `sendlife_marker.png` | Cancel, never Confirm |
| Gift Draw | `giftdraw_marker.png` | X only — never auto-consume a draw |
| Ranking Rewards | `rankingrewards_marker.png` | season popup from a stray tap |
| Friend's … | `friendinfo_marker.png` | two-layer X, left blind (two taps) |
| Game Settings | `gamesettings_marker.png` | user can open it at any time |
| Fortune Bakery | `fortunebakery_marker.png` | X coord not yet CV-verified |
| Previous Results | `prevresults_marker.png` | after a run cut short |
| Not enough Coins | `nocoins_marker.png` | Cancel — Confirm spends gems |
| Mystery Box | `mysterybox_marker.png` | `mb_open`, self-loop + `match_timeout_ms` |
| Inactive → restart | `inactive_marker.png` | confirm, then the GAME restarts itself |

## Missing — blocked on crops

cookierun-classic-bot handles these; netrunner has no marker for any of them, so
they currently stall the loop. Their templates exist in that project but are
cropped at 1280×720 while netrunner runs 1920×1080 — `matchTemplate` is
single-scale, so those files are a **visual reference for what to crop**, not
something to copy in.

Capture with `python tools/snap.py --device 127.0.0.1:5555 --out snaps/` when the
popup appears, crop the title ribbon (tight crops match best), drop it in
`templates/cookierun/`, then add a probe state to the chain.

| Popup | Reference @720p | Handling to port | Priority |
| --- | --- | --- | --- |
| Connection Lost | `CONNECTION_LOST_1.png`, `_2.png` | **not a dismiss** — the reload button often lands back on the same dead screen, so cycle the process: `restart_app` action (already implemented) then the existing `recover_login` chain | high — random, and it strands the bot |
| Party Run | `PARTY_RUN_1.png` | X top-right, then back to home | high — follows announcements |
| Overtake / Break Score | `OVERTAKE_BREAK_SCORE_1.png` | confirm; POST_GAME group | medium — after a record run |
| Enter League | `ENTER_LEAGUE_1.png` | confirm centre, free | medium — season start |
| League Results | `LEAGUE_RESULTS_1.png` | confirm centre, free | medium — season end |
| Too Many Treasures | `TOO_MANY_TREASURES_1.png` | confirm | medium |
| Relic Complete | `RELIC_COMPLETE_1.png` | open it | low |
| Relic Claim | `RELIC_CLAIM_1.png` | claim, close, then **wait 10–15 s** for the cutscene | low |
| Daily New | `DAILY_NEW_1.png` | X | low |
| Daily Check-in Boost Set | `DAILY_CHECKIN_BOOST_SET_1.png` | confirm; extends the daily chain | low |

### Where a new probe goes

The chain is a fallthrough: each probe hands to the next on absent. Insert
between `probe_fortunebakery` and `probe_prevresults` unless the popup can cover
a run, in which case it also needs a `guard_not_*` twin on the in-run side (see
`guard_not_sendlife` / `guard_not_levelup` for the pattern).

Connection Lost is the exception — it belongs at the head of the chain, since
nothing else can proceed while the connection is gone.

## Collecting the missing ones automatically

The Phase 7 collector already does this work: when a loop stalls, the frame is
saved to `unknown_screens/<ts>_<state>.png` and pushed to Discord. Running the
bot unattended for a few days should surface most of the list above without
anyone watching for them.
