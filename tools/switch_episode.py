"""Switch the currently-selected Episode on Cookie Run's home screen.

    python tools/switch_episode.py --device 127.0.0.1:5555 --episode 5

A box-farm config only taps Play! — it never navigates the Episode picker
(the box-farm configs only tap Play!, so they farm whichever episode is on
home BEFORE starting"). Switching episodes has been a manual snap/tap/swipe
dance each time; this scripts the same steps end to end:

  1. From home, tap the Episode button (top-right) to open the map.
  2. Verify the map actually opened (episodemap_marker) — never blind-swipe.
  3. Swipe hard left repeatedly to reach the map's leftmost edge (Episode 1),
     a deterministic landmark, since swipe distance in the live game is not
     pixel-exact and cumulative drift would otherwise strand us between nodes.
  4. Swipe right one step at a time, checking for the target episode's banner
     after each step, up to a generous cap.
  5. Tap the found banner, then Enter on the confirm dialog.

Only episodes 3-6 have banner templates cropped so far (the box-farm configs
that need switching). Add ep<N>_banner.png the same way to extend this.
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
RESET_SWIPES = 6       # generous: more than enough to hit the leftmost edge
MAX_STEP_SWIPES = 6    # generous: more than the farthest episode is steps away
MATCH_THRESHOLD = 0.82


def main() -> int:
    ap = argparse.ArgumentParser(description="switch Cookie Run's selected Episode")
    ap.add_argument("--device", required=True, help="adb address or serial")
    ap.add_argument("--episode", required=True, type=int, help="target episode number, e.g. 5")
    ap.add_argument("--templates-dir", default="templates/cookierun")
    ap.add_argument("--adb", default="adb", help="path to adb binary (default: on PATH)")
    args = ap.parse_args()

    banner_name = f"ep{args.episode}_banner.png"
    store = TemplateStore(args.templates_dir)
    if not (Path(args.templates_dir) / banner_name).exists():
        print(f"error: no {banner_name} — crop one first (see module docstring)", file=sys.stderr)
        return 2

    try:
        device = connect(args.device, adb=args.adb) if ":" in args.device else Device(args.device, adb=args.adb)
    except AdbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    actor = Actor(device, store, default_threshold=MATCH_THRESHOLD)

    # A tap landing while home is still fading in (right after a previous switch,
    # say) is swallowed, so re-tap rather than failing on the first miss.
    for attempt in range(OPEN_MAP_ATTEMPTS):
        actor.tap(*EPISODE_BUTTON)
        time.sleep(1.5)
        frame = grab(device)
        m = find_named(frame, store, "episodemap_marker.png", threshold=MATCH_THRESHOLD)
        if m.found:
            break
    else:
        print("error: Episode Map did not open (episodemap_marker not found)", file=sys.stderr)
        return 1

    for _ in range(RESET_SWIPES):
        (x1, y1), (x2, y2) = MAP_SWIPE_LEFT
        actor.swipe(x1, y1, x2, y2, ms=400)
        time.sleep(0.6)

    found = False
    for step in range(MAX_STEP_SWIPES + 1):
        frame = grab(device)
        m = find_named(frame, store, banner_name, threshold=MATCH_THRESHOLD)
        if m.found:
            found = True
            break
        if step == MAX_STEP_SWIPES:
            break
        (x1, y1), (x2, y2) = MAP_SWIPE_RIGHT
        actor.swipe(x1, y1, x2, y2, ms=400)
        time.sleep(0.6)

    if not found:
        print(f"error: {banner_name} not found after {MAX_STEP_SWIPES} swipes", file=sys.stderr)
        return 1

    actor.tap(m.x, m.y)
    time.sleep(1.5)
    # The confirm dialog re-draws the episode name on its own ribbon, so the map
    # banner no longer matches — the Enter button is what's unique to the dialog.
    frame = grab(device)
    enter = find_named(frame, store, "episodeenter_marker.png", threshold=MATCH_THRESHOLD)
    if not enter.found:
        print(f"error: confirm dialog for {banner_name} did not open as expected", file=sys.stderr)
        return 1

    actor.tap(enter.x, enter.y)
    time.sleep(2.0)

    frame = grab(device)
    m3 = find_named(frame, store, "home_play_marker.png", threshold=MATCH_THRESHOLD)
    if not m3.found:
        print("warning: home_play_marker not visible after Enter — check manually", file=sys.stderr)
        return 1

    print(f"switched to Episode {args.episode}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
