"""Read which Episode the home screen currently has selected.

Cookie Run's home screen carries an "Episode N — <name>" label above the
friends panel. The number is the only reliable way to know what a Play! tap is
about to farm, since the farm configs never navigate the Episode picker
themselves — they run against whatever is already selected.

Lives here rather than in perceive.py because it needs a capture as well as a
match, and perceive.py deliberately takes frames rather than devices.
"""
from __future__ import annotations

from .capture import grab
from .perceive import PerceiveError, TemplateStore, find_named, read_counter

#: Home screen's "Episode N" label — cropped from the word "Episode" itself,
#: which sits BEFORE the episode name and so does not shift as the name's length
#: changes between episodes (the mistake that made an earlier home marker
#: episode-specific and silently broke the whole bot once the account advanced).
EPISODE_LABEL_MARKER = "home/episode_label_marker.png"

#: Digit box relative to the marker's top-left (dx, dy, w, h).
#: Re-measured 2026-08-18 off a clean home frame: the marker crops the word
#: "Episode" at (386,118)-(488,148) and the digit ink sits at x 492-508 — an
#: HSV mask of the label's yellow text put the seven letter-runs at strip x
#: 49-145 and the digit alone at 155-163, so the box starts past that gap and is
#: wide enough for two digits.
#:
#: The previous values were cropped from a frame dimmed by a "Connection lost!"
#: scrim and were also offset right, so the marker scored 0.690 against the 0.82
#: threshold on every real home frame — detect_current_episode returned None
#: every time, and Runner._run_errand_per_episode correctly refused to switch
#: with no way back. Net effect: 5 live attempts, 5 skips, Send-Life never ran.
EPISODE_DIGIT_OFFSET = (106, 0, 22, 30)

#: Episodes the game has. A read outside this range is OCR noise, not an answer.
EPISODE_RANGE = range(1, 8)


def detect_current_episode(device, store: TemplateStore,
                           threshold: float = 0.82) -> int | None:
    """Read the Episode number off the home screen's "Episode N" label.

    Returns None when home isn't showing cleanly (a popup is up) or the digit
    can't be read. Callers must treat None as "unknown" and refuse to act on a
    guess: a wrong episode number farms the wrong content silently.
    """
    frame = grab(device)
    if not find_named(frame, store, "home/home_play_marker.png",
                      threshold=threshold).found:
        return None
    m = find_named(frame, store, EPISODE_LABEL_MARKER, threshold=threshold)
    if not m.found:
        return None
    dx, dy, w, h = EPISODE_DIGIT_OFFSET
    x = m.x - m.w // 2 + dx
    y = m.y - m.h // 2 + dy
    try:
        n = read_counter(frame, (max(0, x), max(0, y), w, h))
    except PerceiveError:
        return None
    if n is None or n not in EPISODE_RANGE:
        return None
    return n
