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

#: Digit box relative to the marker's top-left (dx, dy, w, h) — measured live off
#: a 1920x1080 frame at Episode 4 (marker top-left (352,113), digit ink at
#: x 492-520, y 113-142).
EPISODE_DIGIT_OFFSET = (140, 0, 28, 29)

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
