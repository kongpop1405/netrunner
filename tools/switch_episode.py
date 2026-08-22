"""Switch the currently-selected Episode on Cookie Run's home screen.

    python tools/switch_episode.py --device 127.0.0.1:5555 --episode 5

A box-farm config only taps Play! — it never navigates the Episode picker
(the box-farm configs only tap Play!, so they farm whichever episode is on
home BEFORE starting"). Switching episodes has been a manual snap/tap/swipe
dance each time; this scripts the same steps end to end:

  1. From home, tap the Episode button (top-right) to open the map.
  2. Verify the map actually opened (episodemap_marker) — never blind-swipe.
  3. Swipe left until the map's leftmost episode is on screen, checking after
     each swipe rather than counting a fixed number: swipe distance in the live
     game is not pixel-exact, so a counted reset can stop short and leave the
     rightward search starting past its target.
  4. Swipe right one step at a time, checking for the target episode's banner
     after each step, up to a generous cap.
  5. Tap the found banner, then Enter on the confirm dialog.

Episodes 1-7 all have banner templates. Note the map is NOT ordered 1..7 left
to right — measured live, left to right: ep7, ep5, ep4, ep3, ep2, ep1, with ep6
sharing a screen with ep5 and Special/Event episodes interleaved.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.act import Actor  # noqa: E402
from src.capture import grab  # noqa: E402
from src.device import AdbError, Device, connect  # noqa: E402
from src.perceive import TemplateStore, find_named  # noqa: E402

EPISODE_BUTTON = (1280, 175)
MAP_SWIPE_LEFT = ((1500, 540), (400, 540))   # drags map content rightward
MAP_SWIPE_RIGHT = ((400, 540), (1700, 540))  # drags map content leftward

OPEN_MAP_ATTEMPTS = 3  # home may still be fading in when the first tap lands

#: How long to wait for home to come back after entering an Episode. Generous
#: because the screen genuinely reloads and the cost is not fixed; a single grab
#: at 2.0s reported failure on switches that had actually succeeded.
HOME_AFTER_ENTER_S = 12.0

#: How long to wait for home BEFORE tapping the Episode button. The map tap is
#: blind, so a caller arriving on any other screen (a previous switch still
#: loading, a popup) burns all OPEN_MAP_ATTEMPTS against the wrong screen and
#: reports "Episode Map did not open" — which reads as a marker problem and is
#: not one.
HOME_BEFORE_TAP_S = 15.0
RESET_SWIPES = 12      # upper bound only — the reset stops when the edge settles

#: How far LEFT_EDGE_MARKER may drift between reads and still count as "not
#: moving". A swipe that actually scrolls the map moves the banner hundreds of
#: px; template matching on a settled map wobbles by a couple.
EDGE_SETTLE_PX = 8

#: Consecutive settled reads required before the reset is believed. One is not
#: enough: a swipe that under-travels can leave two frames looking similar.
EDGE_SETTLE_READS = 2
MAX_STEP_SWIPES = 6    # generous: more than the farthest episode is steps away
MATCH_THRESHOLD = 0.82

#: The game's own "Exit the game?" confirm. Play! scores 1.000 through it, so
#: the home guard below has to rule it out separately or it taps into a modal.
EXIT_DIALOG_MARKER = "home/exitgame_marker.png"

#: The Episode Map's own X, top-right. Measured live 2026-08-20 on the frame this
#: function left stranded: tapping it took episodemap 1.000 -> 0.173 and brought
#: home_play 0.308 -> 1.000 in one go. Used only to undo a map this call opened —
#: a failure past that point otherwise hands the map to whatever runs next, and
#: everything after it then fails on the map rather than on its own problem.
MAP_CLOSE = (1841, 75)

#: The leftmost episode on the map, used as the reset landmark. Counting a fixed
#: number of left-swipes was not enough: swipe distance is not pixel-exact, so a
#: reset starting from the right edge sometimes stopped short, and the rightward
#: search then began PAST the target and could never reach it — Episode 5 sits at
#: step 1, yet switch_episode(5) failed with "not found after 6 swipes" while
#: parked at Episode 4. Swiping until this marker is on screen makes the reset
#: deterministic regardless of how far each swipe happens to travel.
LEFT_EDGE_MARKER = "episode/ep7_banner.png"


class SwitchEpisodeError(Exception):
    """Raised by switch_episode() on any step failure — message is user-facing."""


def _close_map(device, store, actor, threshold: float) -> None:
    """Drop the Episode Map if it is still up. Best-effort and quiet.

    Called on the way out of a failure that happened after the map opened. A map
    left open stops being this call's problem and becomes everyone else's: live
    2026-08-20 the Episode 6 banner search gave up, the map stayed, and Episode 7
    plus the Episode-2 restore then both failed with "not on home" rather than on
    anything to do with themselves — the farm loop ran against the wrong Episode
    until the progress watchdog fired 1619s later.
    """
    try:
        if not find_named(grab(device), store, "episode/episodemap_marker.png",
                          threshold=threshold).found:
            return
        actor.tap(*MAP_CLOSE)
        time.sleep(1.0)
    except Exception:
        # Cleanup must never replace the error actually being raised.
        pass


def switch_episode(device, store: TemplateStore, episode: int,
                    threshold: float = MATCH_THRESHOLD) -> None:
    """Navigate Cookie Run's home screen to the given Episode. Raises
    SwitchEpisodeError on any step failure (map didn't open, banner not found,
    confirm dialog didn't appear). Caller must already be on/near home."""
    banner_name = f"episode/ep{episode}_banner.png"
    if not (store.dir / banner_name).exists():
        raise SwitchEpisodeError(f"no {banner_name} — crop one first (see module docstring)")

    actor = Actor(device, store, default_threshold=threshold)

    # Wait for home before tapping anything. The Episode-button tap is blind, so
    # arriving on any other screen (a previous switch's home reload still in
    # flight, a popup that queued while Send-Life ran) spends every attempt
    # tapping the wrong screen and then blames the map marker.
    #
    # Seeing Play! is not enough on its own. Snapped live 2026-08-20 09:13:55 on
    # a frame where this guard passed and all three map taps then failed: the
    # game's own "Exit the game?" dialog was centred over home (raised by the
    # BACK presses Send-Life uses to leave the Friends panel) and Play! scored
    # 1.000 straight through it, because Play! is bottom-right and the dialog is
    # centred. Both markers at 1.000 is the ambiguous case, so the dialog is
    # checked too rather than trusting one marker to mean "nothing is in the way".
    # Measured that day: dialog frame exitgame 1.000, clean Episode-2 home 0.399.
    blocked_by = None
    for _ in range(int(HOME_BEFORE_TAP_S / 0.5)):
        frame = grab(device)
        if find_named(frame, store, EXIT_DIALOG_MARKER, threshold=threshold).found:
            blocked_by = "the \"Exit the game?\" dialog is up"
            time.sleep(0.5)
            continue
        if find_named(frame, store, "home/home_play_marker.png",
                      threshold=threshold).found:
            break
        blocked_by = None
        time.sleep(0.5)
    else:
        detail = f" ({blocked_by})" if blocked_by else ""
        raise SwitchEpisodeError(
            f"not on home after {HOME_BEFORE_TAP_S:.0f}s{detail} — refusing to "
            f"tap the Episode button blind")

    # A tap landing while home is still fading in (right after a previous switch,
    # say) is swallowed, so re-tap rather than failing on the first miss.
    for attempt in range(OPEN_MAP_ATTEMPTS):
        actor.tap(*EPISODE_BUTTON)
        time.sleep(1.5)
        frame = grab(device)
        m = find_named(frame, store, "episode/episodemap_marker.png", threshold=threshold)
        if m.found:
            break
    else:
        raise SwitchEpisodeError("Episode Map did not open (episodemap_marker not found)")

    # The map is open from here on, so any failure has to put it away or the
    # caller inherits a modal it never opened (see _close_map).
    try:
        # Reset to the map's left edge, verified rather than counted (see
        # LEFT_EDGE_MARKER). Already-there is the common case when the previous
        # switch left us near the start, so check before the first swipe.
        #
        # Seeing the marker is not the same as being AT the edge: ep7's banner
        # matches as soon as any part of it scrolls in, so the reset used to stop
        # with the map still short and the rightward search then started past its
        # target and walked away from it. Measured live 2026-08-20 by counting
        # swipes per attempt — ep2 and ep3 reset with 4 left-swipes and found
        # their banner in 3 right-steps, ep4 with 3 and 2, ep5 with 3 and 1, but
        # ep6 stopped after 2 and then burned all 6 right-steps without ever
        # matching. The frame it stranded on had ep1 at 1.000 and ep2 at 0.946 —
        # the far right of the map, the opposite end from ep7. Episode 5 failed
        # the same way on a restore an hour later.
        #
        # So keep swiping until the marker's x stops changing: an edge that no
        # longer moves under a swipe is the actual edge.
        settled = 0
        last_x = None
        for _ in range(RESET_SWIPES):
            m = find_named(grab(device), store, LEFT_EDGE_MARKER, threshold=threshold)
            if m.found and last_x is not None and abs(m.x - last_x) <= EDGE_SETTLE_PX:
                settled += 1
                if settled >= EDGE_SETTLE_READS:
                    break
            else:
                settled = 0
            last_x = m.x if m.found else None
            (x1, y1), (x2, y2) = MAP_SWIPE_LEFT
            actor.swipe(x1, y1, x2, y2, ms=400)
            time.sleep(1.0)  # see the step-search loop below for why 1.0s, not 0.6s
        else:
            raise SwitchEpisodeError(
                f"map did not reach its left edge ({LEFT_EDGE_MARKER} never "
                f"settled) after {RESET_SWIPES} swipes")

        found = False
        for step in range(MAX_STEP_SWIPES + 1):
            frame = grab(device)
            m = find_named(frame, store, banner_name, threshold=threshold)
            if m.found:
                found = True
                break
            if step == MAX_STEP_SWIPES:
                break
            (x1, y1), (x2, y2) = MAP_SWIPE_RIGHT
            actor.swipe(x1, y1, x2, y2, ms=400)
            # 0.6s left one live 6-episode run undercounted: the scroll had not
            # fully settled when the frame was grabbed, so a single step's match
            # came back low, the loop swiped past the target with no way to back
            # up, and it walked all the way to the map's left edge (Episode 1)
            # instead — switch_episode(6) failed "not found after 6 swipes" while
            # Episode 6 sat one step away the whole time. Measured live
            # 2026-08-07: the same walk with 1.0s per step matched cleanly.
            time.sleep(1.0)

        if not found:
            raise SwitchEpisodeError(f"{banner_name} not found after {MAX_STEP_SWIPES} swipes")

        actor.tap(m.x, m.y)
        time.sleep(1.5)
        # The confirm dialog re-draws the episode name on its own ribbon, so the map
        # banner no longer matches — the Enter button is what's unique to the dialog.
        frame = grab(device)
        enter = find_named(frame, store, "episode/episodeenter_marker.png", threshold=threshold)
        if not enter.found:
            raise SwitchEpisodeError(f"confirm dialog for {banner_name} did not open as expected")

        actor.tap(enter.x, enter.y)

        # Poll rather than grabbing once after a fixed 2.0s wait. Entering an Episode
        # reloads the home screen and that is not a fixed cost: live 2026-08-18 a
        # switch that had actually WORKED raised here anyway because home was still
        # loading at the 2.0s mark. The caller then treated the episode as failed —
        # and worse, the game was left mid-load, so the NEXT switch tapped the Episode
        # button on a screen that was not home and failed with "Episode Map did not
        # open", cascading to every remaining episode (observed: Episode 2 raised
        # here, then 4/5/6/7 all failed at map-open while Episode 3, which happened to
        # land cleanly, switched fine).
        for _ in range(int(HOME_AFTER_ENTER_S / 0.5)):
            time.sleep(0.5)
            if find_named(grab(device), store, "home/home_play_marker.png",
                          threshold=threshold).found:
                return
        raise SwitchEpisodeError(
            f"home_play_marker not visible {HOME_AFTER_ENTER_S:.0f}s after Enter — "
            f"check manually")
    except SwitchEpisodeError:
        _close_map(device, store, actor, threshold)
        raise


def main() -> int:
    ap = argparse.ArgumentParser(description="switch Cookie Run's selected Episode")
    ap.add_argument("--device", required=True, help="adb address or serial")
    ap.add_argument("--episode", required=True, type=int, help="target episode number, e.g. 5")
    ap.add_argument("--templates-dir", default="templates/cookierun")
    ap.add_argument("--adb", default="adb", help="path to adb binary (default: on PATH)")
    args = ap.parse_args()

    store = TemplateStore(args.templates_dir)
    try:
        device = connect(args.device, adb=args.adb) if ":" in args.device else Device(args.device, adb=args.adb)
    except AdbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        switch_episode(device, store, args.episode)
    except SwitchEpisodeError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(f"switched to Episode {args.episode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
