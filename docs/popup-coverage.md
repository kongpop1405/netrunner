# Popup coverage

What the farm loop can dismiss, and what still stalls it. An unhandled popup
costs the whole session until the livelock warning fires and someone looks.

## Fast-close for a popup with NO marker at all

Every mechanism above needs the popup identified first — a marker, a probe
state. A popup nobody has cropped yet is invisible to all of it: live
2026-08-21 a new "Friendly Run" submenu (two popups deep, no marker for
either) stalled the bot for the full `no_progress_s` window before the
watchdog even started recovering, because `recover_unknown_probe` only walks
screens the config already recognises.

**`recover_unknown_backspam_1/2/3`** sits ahead of that probe walk (or ahead
of `restart_app` in the errand configs, which have no probe walk at all — see
`sendlife.json`/`addfriend.json`/`giftdraw.json`). It presses Android BACK,
checks for `home_play_marker`, and rejoins the loop the moment it appears —
otherwise presses again, up to 3 times. `key()`'s own docstring already says
BACK "dismisses most dialogs safely," and the sendlife exit chain has relied
on exactly that for leaving the Friends panel; this is the same trick given a
name and put ahead of the expensive paths.

Recovers most unmarked popups in a few seconds instead of the full probe walk
plus a process restart. It does NOT replace cropping a marker for a popup that
recurs — BACK-closing something every single watchdog fire is a sign that
popup is common enough to deserve a real probe state (see "Missing" below);
this exists for the popup that only shows up once.

**Bounded at 3, not more**: BACK pressed on `home` itself raises the game's
own "Exit the game?" confirm — the same trap `exit_to_home_3` already guards
against in `sendlife.json`. A backspam chain that kept pressing past the point
where the unknown popup actually closed would eventually hit that dialog
instead of stopping. `exit_dismiss_exitgame` (below) is the fallback if a
future recovery path presses BACK more than 3 times and lands on it anyway.

Apply the same 3-state pattern to any other recovery-style chain that presses
BACK without knowing what is on screen: `detect: home_play_marker.png`,
`on_match: goto <the loop's real entry state>`, `on_absent: key 4 → wait →
goto <next step, or the expensive fallback on the last one>`.

## Two kinds of popup — a handler alone is not enough

A popup that **covers** the Play button makes `home_play_marker` absent, so
`home` falls through `on_absent` into the probe chain and whichever
`probe_*` state owns that popup dismisses it. That is the easy case.

A popup that **leaves Play visible** — most centred dialogs do; the button
lives in the bottom-right corner — never reaches the probe chain at all.
`home` still matches at 1.00 through the dialog, so the loop goes straight to
the pre-Play gates and, finding none of *their* markers, taps Play into the
dialog. Forever. The probe state that would have handled it is unreachable,
because it hangs off the `home`-is-absent branch.

**So every such popup needs a `verify_no_*` gate in the pre-Play chain, not
just a `probe_*` state.** The gates run in order between `home` and the Play
tap, each detecting one marker and handing the Play tap to the next:

| Gate | Marker |
| --- | --- |
| `verify_no_popup` | `inactive_marker.png` |
| `verify_no_sendlife` | `sendlife_marker.png` |
| `verify_no_prevresults` | `prevresults_marker.png` |
| `verify_no_enterleague` | `enterleague_marker.png` |

Adding one: give it `detect`, dismiss via `close_popup` + `verify` on
`on_match` then `goto: home`, and move the previous gate's `on_absent` action
list (the real Play tap) onto the new gate's `on_absent`. `tools/lint_config.py`
will not catch a missing gate — the states stay reachable either way — so check
new popups against this rule by hand.

To tell which kind a popup is, match `home_play_marker.png` against a capture
of it. Measured so far:

| Popup | Play visible behind it | Gate |
| --- | --- | --- |
| Previous Results | yes (1.00) | `verify_no_prevresults` |
| Enter League | yes (1.00) | `verify_no_enterleague` |
| Connection Lost | no (0.36) | none needed — the probe chain reaches it |

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
| Friend's … | `friendinfo_marker.png` | one verified close per pass at (1633,107). Can stack two layers, and the outer X is covered when it does — `close_popup` warns instead of spinning, the next pass takes the layer left. See RUN.md for the measured coordinates |
| Party Run "Select a Mode" | `partyrun_marker.png` | `guard_not_partyrun`, closes at (1820,135) — the top-right of the **screen**, not a dialog header |
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
| Overtake / Break Score | `OVERTAKE_BREAK_SCORE_1.png` | confirm; POST_GAME group | medium — after a record run |
| Enter League | `ENTER_LEAGUE_1.png` | confirm centre, free | medium — season start |
| League Results | `LEAGUE_RESULTS_1.png` | confirm centre, free | medium — season end |
| Too Many Treasures | `TOO_MANY_TREASURES_1.png` | confirm | medium |
| Relic Complete | `RELIC_COMPLETE_1.png` | open it | low |
| Relic Claim | `RELIC_CLAIM_1.png` | claim, close, then **wait 10–15 s** for the cutscene | low |
| Daily New | `DAILY_NEW_1.png` | X | low |
| Daily Check-in Boost Set | `DAILY_CHECKIN_BOOST_SET_1.png` | confirm; extends the daily chain | low |
| Friendly Run / Select a Mode | none — no reference either, new as of 2026-08-21 | two popups deep (Friendly Run submenu over a Select-a-Mode dialog), each with its own X; recovered live via `recover_unknown_backspam` in seconds | low unless it recurs — promote to a real probe state if it does |

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
