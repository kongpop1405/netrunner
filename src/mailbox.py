"""Read how many Lives are waiting in the Mailbox's Lives tab.

The Send-Life sweep needs the count BEFORE it starts draining, because the
decision it feeds (drain only, versus drain plus a Send-Life pass across every
Episode) is about how much idle heart-wait time is worth spending — and once the
sweep has run, the list is empty either way.

Measured 2026-08-20: the home screen's envelope badge is NOT this number. It read
55 while the Lives tab read 53 and Rewards read 4, i.e. the home badge totals
every tab's notices. Reading it instead of the tab's own badge picks up Rewards
and Notices as if they were Lives.

Lives here rather than in perceive.py for the same reason episode.py does: it
needs a capture as well as a match, and perceive.py deliberately takes frames.
"""
from __future__ import annotations

from .capture import grab
from .perceive import (PerceiveError, TemplateStore, find_named,
                       read_counter_voted)

#: The Mailbox's Lives tab. Already used as a detect marker by
#: sendlife_mailbox.json, and scores 1.000 on a clean Lives-tab frame, so it
#: doubles as the anchor for the badge that sits on its top-right corner.
LIVES_TAB_MARKER = "lives_tab_marker.png"

#: Badge box relative to the marker's top-left (dx, dy, w, h) — the pill itself,
#: no padding. Measured 2026-08-20 off a live Lives-tab frame: the marker matched
#: at centre (900,215) size 200x100, so its top-left is (800,165); an HSV red mask
#: over the tab strip put the badge's pill at x 1016-1071, y 159-199, identical on
#: all four badge frames since.
#:
#: This was 4px padded until the padding turned out to be the bug. Padded, psm 7
#: read nothing at all for 18, 16, and 14 — three live sweeps in a row logged "no
#: readable Lives badge" and the gate skipped Send-Life every time — while the
#: same pixels flush read all three. But flush is what misread the neighbouring
#: single-digit Rewards badge as 47. Neither crop wins, so read_counter_voted
#: tries both (and both psm modes) and takes the majority; the box stays flush
#: because that is the pill, and the padding is the reader's business now.
LIVES_BADGE_OFFSET = (216, -6, 55, 40)

#: A Lives list longer than this is OCR noise, not an answer: the badge is a
#: friend-list count and the game caps the friend list well under it.
LIVES_MAX = 300


def read_lives_waiting(device, store: TemplateStore,
                       threshold: float = 0.85, *,
                       keep_unreadable_in: str | None = None) -> int | None:
    """Read the Lives-tab badge count off an open Mailbox.

    Returns None when the Lives tab isn't showing, when the badge is absent, or
    when the digits can't be read. An absent badge and an unreadable badge are
    deliberately the same answer: the tab drops the badge entirely at zero, so
    None means "don't decide from this", never "zero".

    Those two cases look identical in a log, though, and they mean opposite
    things — one is the list being empty, the other is a read to go fix. Pass
    `keep_unreadable_in` (a directory) to save the frame whenever the tab is up
    but no count comes out, so the next occurrence can be told apart after the
    fact instead of needing to be caught live while mail is still waiting.
    """
    frame = grab(device)
    m = find_named(frame, store, LIVES_TAB_MARKER, threshold=threshold)
    if not m.found:
        return None
    dx, dy, w, h = LIVES_BADGE_OFFSET
    x = m.x - m.w // 2 + dx
    y = m.y - m.h // 2 + dy
    try:
        n = read_counter_voted(frame, (max(0, x), max(0, y), w, h))
    except PerceiveError:
        n = None
    if n is not None and 0 < n <= LIVES_MAX:
        return n
    if keep_unreadable_in:
        _keep(frame, keep_unreadable_in, n)
    return None


def _keep(frame, dirname: str, got) -> None:
    """Save a frame the badge could not be read from. Best-effort: a diagnostic
    that raises would fail the sweep it is only meant to explain."""
    try:
        import time
        from pathlib import Path

        import cv2

        d = Path(dirname)
        d.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d_%H%M%S")
        cv2.imwrite(str(d / f"lives_badge_{stamp}_got{got}.png"), frame)
    except Exception:
        pass
