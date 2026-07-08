"""Actuation — translate an action dict into ADB input events.

The FSM hands each action here. `dry_run` logs the intended event without
sending it, so a config can be validated against a live screen safely.
"""
from __future__ import annotations

import logging
import random
import time

from .device import Device
from .perceive import PerceiveError, TemplateStore, find_named

log = logging.getLogger("netrunner.act")


class ActError(RuntimeError):
    pass


class Actor:
    def __init__(
        self,
        device: Device,
        store: TemplateStore,
        *,
        dry_run: bool = False,
        default_threshold: float = 0.85,
    ):
        self.device = device
        self.store = store
        self.dry_run = dry_run
        self.default_threshold = default_threshold

    # --- humanization ---------------------------------------------------------

    #: Gaussian std-dev (px) for tap position noise. ~3px keeps taps on a button
    #: while breaking the "same pixel every time" signature.
    spatial_sigma: float = 3.0
    #: hard cap so a rare large Gaussian draw can't fling the tap off-target.
    spatial_clip: int = 8
    #: base pre-tap delay range (seconds) — normal reaction cadence.
    delay_range: tuple[float, float] = (0.08, 0.25)
    #: chance of a longer "human hesitation" pause, and its range (seconds).
    hesitate_chance: float = 0.08
    hesitate_range: tuple[float, float] = (0.6, 1.4)

    def _jitter(self, x: int, y: int) -> tuple[int, int, float]:
        """Return (tap_x, tap_y, pre_delay_seconds) with human-like noise.

        Spatial: Gaussian offset around the true center (clipped) — a soft cloud
        of taps instead of one exact pixel. Temporal: a short randomized delay,
        occasionally a longer hesitation, so the cadence is never a metronome.
        """
        dx = int(round(random.gauss(0, self.spatial_sigma)))
        dy = int(round(random.gauss(0, self.spatial_sigma)))
        dx = max(-self.spatial_clip, min(self.spatial_clip, dx))
        dy = max(-self.spatial_clip, min(self.spatial_clip, dy))

        if random.random() < self.hesitate_chance:
            delay = random.uniform(*self.hesitate_range)
        else:
            delay = random.uniform(*self.delay_range)

        return x + dx, y + dy, delay

    # --- primitive events -----------------------------------------------------

    def tap(self, x: int, y: int) -> None:
        jx, jy, delay = self._jitter(x, y)
        if delay:
            time.sleep(delay)
        log.info("tap (%d,%d)%s", jx, jy, " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "tap", str(jx), str(jy))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300) -> None:
        log.info("swipe (%d,%d)->(%d,%d) %dms%s", x1, y1, x2, y2, ms,
                 " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "swipe", str(x1), str(y1), str(x2), str(y2), str(ms))

    #: chance a jump becomes a double-jump (second tap mid-air).
    double_jump_chance: float = 0.35
    #: gap (seconds) between the two taps of a double-jump — fast, but human.
    double_jump_gap: tuple[float, float] = (0.09, 0.18)

    def _rand_in_zone(self, cx: int, cy: int, rx: int, ry: int) -> tuple[int, int]:
        """A uniformly random point inside the button ellipse (cx,cy) radius rx,ry.
        A big finger lands anywhere on the button — uniform over the whole zone
        reads far more human than a tight Gaussian on the exact center.
        """
        while True:
            ox = random.uniform(-rx, rx)
            oy = random.uniform(-ry, ry)
            if (ox / rx) ** 2 + (oy / ry) ** 2 <= 1.0:  # inside ellipse
                return int(cx + ox), int(cy + oy)

    def jump(self, cx: int, cy: int, rx: int, ry: int) -> None:
        """Human-like jump: tap a random point inside the Jump zone, sometimes a
        double-jump (a quick second tap at a *different* random point)."""
        x, y = self._rand_in_zone(cx, cy, rx, ry)
        double = random.random() < self.double_jump_chance
        log.info("jump (%d,%d)%s%s", x, y, " x2" if double else "",
                 " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "tap", str(x), str(y))
        if double:
            time.sleep(random.uniform(*self.double_jump_gap))
            x2, y2 = self._rand_in_zone(cx, cy, rx, ry)
            if not self.dry_run:
                self.device.shell("input", "tap", str(x2), str(y2))

    def key(self, keycode: int) -> None:
        """Send an Android keyevent (4 = BACK — dismisses most dialogs safely)."""
        log.info("key %d%s", keycode, " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "keyevent", str(keycode))

    # --- action dispatch ------------------------------------------------------

    def run(self, action: dict, frame) -> str | None:
        """Execute one action dict. Returns a state name to jump to, or None.

        `frame` is the most recent screen capture, needed by tap_template.
        """
        kind = action.get("type")
        if kind == "tap_xy":
            self.tap(int(action["x"]), int(action["y"]))
            return None
        if kind == "tap_template":
            thr = float(action.get("threshold", self.default_threshold))
            m = find_named(frame, self.store, action["template"], thr)
            if not m.found:
                raise ActError(
                    f"tap_template '{action['template']}' not on screen "
                    f"(best score {m.score:.2f} < {thr:.2f})"
                )
            self.tap(m.x, m.y)
            return None
        if kind == "swipe":
            self.swipe(
                int(action["x1"]), int(action["y1"]),
                int(action["x2"]), int(action["y2"]),
                int(action.get("ms", 300)),
            )
            return None
        if kind == "wait":
            ms = int(action["ms"])
            log.info("wait %dms", ms)
            time.sleep(ms / 1000)
            return None
        if kind == "key":
            self.key(int(action["code"]))
            return None
        if kind == "jump":
            self.jump(
                int(action["cx"]), int(action["cy"]),
                int(action.get("rx", 150)), int(action.get("ry", 55)),
            )
            return None
        if kind == "goto":
            return str(action["state"])
        if kind == "stop":
            return "__stop__"
        raise ActError(f"unknown action type: {kind!r}")
