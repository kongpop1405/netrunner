"""Actuation — translate an action dict into ADB input events.

The FSM hands each action here. `dry_run` logs the intended event without
sending it, so a config can be validated against a live screen safely.
"""
from __future__ import annotations

import logging
import random
import time

from .capture import CaptureError, grab
from .device import AdbError, Device
from .perceive import PerceiveError, TemplateStore, find_named, odd_cells_out

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
            x = round(cx + random.uniform(-rx, rx))
            y = round(cy + random.uniform(-ry, ry))
            # test the ellipse on the QUANTIZED point: int()/round() on the raw
            # sample can shift an edge hit by up to 1px and land outside the zone
            if ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2 <= 1.0:
                return x, y

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

    #: how long a slide is held (ms) when the action doesn't say. Long enough to
    #: clear a typical low bar, short enough not to eat the next jump cue.
    slide_hold_ms: int = 550
    #: jitter (ms) added to the hold so the duration isn't a constant.
    slide_hold_jitter_ms: int = 90

    def slide(self, cx: int, cy: int, rx: int, ry: int, hold_ms: int | None = None) -> None:
        """Hold the Slide button: an `input swipe` whose start and end are the same
        point acts as a press-and-hold for `hold_ms`. Cookie stays crouched for the
        whole hold, so the duration — not the tap — is what clears the obstacle.
        """
        x, y = self._rand_in_zone(cx, cy, rx, ry)
        ms = hold_ms if hold_ms is not None else self.slide_hold_ms
        ms += random.randint(-self.slide_hold_jitter_ms, self.slide_hold_jitter_ms)
        ms = max(120, ms)
        log.info("slide (%d,%d) hold %dms%s", x, y, ms, " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "swipe", str(x), str(y), str(x), str(y), str(ms))

    def key(self, keycode: int) -> None:
        """Send an Android keyevent (4 = BACK — dismisses most dialogs safely)."""
        log.info("key %d%s", keycode, " [dry]" if self.dry_run else "")
        if not self.dry_run:
            self.device.shell("input", "keyevent", str(keycode))

    #: Restarter for the `restart_app` action, injected by the Runner. None means
    #: the action degrades to a no-op with a warning rather than crashing.
    restarter: object = None

    #: Callback for the `run_config` action, injected by the Runner as
    #: Runner._run_errand — takes a config path, runs it to completion (that
    #: config's own `stop` action ends it), and returns. None means the action
    #: degrades to a no-op with a warning rather than crashing, same as
    #: restart_app with no restarter wired.
    errand_runner: object = None

    def run_config(self, path: str, episodes: list[int] | None = None) -> None:
        """Run another config's FSM to completion, then return control here.

        For a detour that is really a whole separate bot — Send-Life, the
        mailbox sweep — rather than a few taps this config could own itself.
        Those already end in their own `stop` action, so nothing here needs
        to know when they are "done"; the sub-run simply returns.

        With `episodes`, the errand is run once per episode in that list,
        switching the home screen's selected Episode in between — Send-Life's
        friend list is per-Episode, so one pass only ever reaches the friends
        of whichever Episode happened to be selected. The caller's own episode
        is restored afterwards; see Runner._run_errand.
        """
        if self.dry_run:
            log.info("run_config '%s'%s [dry]", path,
                     f" episodes={episodes}" if episodes else "")
            return
        if self.errand_runner is None:
            log.warning("run_config '%s' requested but no errand_runner is "
                        "wired — running via main.py without going through "
                        "a Runner (e.g. a unit test) skips it", path)
            return
        log.info("run_config: %s%s", path, f" episodes={episodes}" if episodes else "")
        self.errand_runner(path, episodes)

    def restart_app(self) -> None:
        """Force-stop and relaunch the game, verifying it stays up.

        For screens the game cannot recover from on its own. The inactive popup
        is not one of these — confirming it makes the GAME restart itself, and
        the existing recover_login chain re-auths. A lost connection is: the
        dialog's reload button often lands back on the same dead screen, so the
        process has to be cycled from outside.
        """
        if self.dry_run:
            log.info("restart_app [dry]")
            return
        if self.restarter is None:
            log.warning("restart_app requested but no restarter is wired — "
                        "pass --launch or set session_reset_s to enable it")
            return
        log.info("restart_app: cycling the game process")
        self.restarter.restart()

    # --- shared game actions --------------------------------------------------
    # Behaviour every bot shares lives here, not copy-pasted into each config, so
    # a tuning fix reaches every config that names the action without touching
    # any JSON. Coordinates default to the live-verified values but stay
    # overridable per action for a future screen whose button sits elsewhere.

    #: Cookie Relay Boost button — screen centre, verified live.
    relay_xy: tuple[int, int] = (960, 540)
    #: taps per relay action. The button is a no-op when no partner is ready, so
    #: a repeat costs nothing; >1 covers a tap lost to a mid-fade frame.
    relay_taps: int = 1
    #: gap (seconds) between repeated relay taps.
    relay_gap_s: float = 0.12

    def relay_tap(self, x: int | None = None, y: int | None = None,
                  taps: int | None = None) -> None:
        """Tap the Cookie Relay Boost button.

        Blind by design: the relay icon has no template of its own and only
        appears for part of a run, so there is nothing to verify against — but
        tapping it when it is absent is harmless (the centre of an in-run screen
        holds no other control). Raising `relay_taps` is the single knob that
        fixes "the relay sometimes doesn't fire" for every bot at once.
        """
        cx = self.relay_xy[0] if x is None else x
        cy = self.relay_xy[1] if y is None else y
        n = self.relay_taps if taps is None else taps
        for i in range(max(1, n)):
            if i:
                time.sleep(self.relay_gap_s)
            self.tap(cx, cy)

    #: Fast Start prompt button — the blue arrow on "Tap to activate Fast Start".
    faststart_xy: tuple[int, int] = (985, 515)
    #: how many times to tap across the prompt window. The prompt opens a second
    #: or two after Play and auto-dismisses a few seconds later, so the spam
    #: covers a window rather than a moment.
    faststart_taps: int = 14
    #: gap (ms) between spam taps — total window ≈ taps × gap.
    faststart_gap_ms: int = 400

    def faststart_tap(self, x: int | None = None, y: int | None = None,
                      taps: int | None = None, gap_ms: int | None = None) -> None:
        """Spam-tap the Fast Start prompt across its open window.

        Replaces the hand-written tap_xy/wait ladder (24 actions per state) that
        every boxrun config carried inline. Detect-then-tap was tried and lost
        taps whenever the prompt window was shorter than one poll, so the blind
        spam is deliberate; what matters is that its length is tunable in one
        place instead of by editing pairs of JSON entries in every config.
        """
        cx = self.faststart_xy[0] if x is None else x
        cy = self.faststart_xy[1] if y is None else y
        n = self.faststart_taps if taps is None else taps
        gap = self.faststart_gap_ms if gap_ms is None else gap_ms
        log.info("faststart spam %d taps @ (%d,%d) every %dms", n, cx, cy, gap)
        for i in range(max(1, n)):
            if i:
                time.sleep(gap / 1000)
            self.tap(cx, cy)

    #: settle wait (ms) after a popup-close tap, before anything re-reads the screen.
    popup_settle_ms: int = 1500
    #: extra close attempts when `verify` names a template that is still on screen.
    popup_retries: int = 1

    def close_popup(self, x: int, y: int, *, settle_ms: int | None = None,
                    verify: str | None = None, retries: int | None = None,
                    threshold: float | None = None) -> None:
        """Tap a popup's close/confirm button and wait for it to go away.

        With `verify` naming the popup's own marker template, the close is
        confirmed rather than assumed: a fresh frame is captured after the settle
        wait and the tap is repeated while the marker is still matching. That is
        the fix for "the close sometimes doesn't take" — a tap that lands while
        the dialog is still fading in does nothing, and the old blind tap+wait
        pair had no way to notice.
        """
        settle = self.popup_settle_ms if settle_ms is None else settle_ms
        attempts = (self.popup_retries if retries is None else retries) + 1
        thr = self.default_threshold if threshold is None else threshold

        for attempt in range(attempts):
            self.tap(x, y)
            time.sleep(settle / 1000)
            if verify is None or self.dry_run:
                return
            try:
                frame = grab(self.device)
                m = find_named(frame, self.store, verify, thr)
            except (CaptureError, PerceiveError, AdbError) as e:
                # Verification is best-effort: a failed re-read must not turn a
                # working close into a crash. The FSM re-reads the screen next
                # poll anyway and will route from whatever is actually there.
                log.warning("close_popup could not verify '%s': %s", verify, e)
                return
            if not m.found:
                return
            if attempt + 1 < attempts:
                log.info("close_popup: '%s' still on screen (score %.2f) — retrying",
                         verify, m.score)
        log.warning("close_popup: '%s' still on screen after %d attempt(s)",
                    verify, attempts)

    #: Returned instead of a state name when a card puzzle cannot be read
    #: confidently. The FSM turns it into the action's `bail_goto`.
    UNSURE = "__unsure__"

    #: gap (seconds) between taps on separate cards — a person does not tap two
    #: things in the same instant.
    card_tap_gap: tuple[float, float] = (0.35, 0.9)
    #: pause before Confirm, as if checking the picks.
    card_confirm_pause: tuple[float, float] = (0.6, 1.4)

    def solve_cards(self, frame, cells, size, *, pick=2, gap_min=0.04,
                    confirm_xy=None) -> str | None:
        """Tap the odd cards out of a grid, then Confirm.

        Returns None on success, or UNSURE when the puzzle could not be read
        confidently — in which case nothing is tapped at all. A wrong answer here
        risks the account, so refusing to answer is the cheaper mistake: the
        caller routes to a bail state that stops and alerts for a human.
        """
        picked = odd_cells_out(frame, cells, size, pick=pick, gap_min=gap_min)
        if picked is None:
            log.warning("solve_cards: the odd cards are not clearly separated — "
                        "tapping nothing")
            return self.UNSURE
        log.info("solve_cards: odd cards %s of %d%s",
                 [i + 1 for i in picked], len(cells), " [dry]" if self.dry_run else "")
        for n, idx in enumerate(picked):
            if n:
                time.sleep(random.uniform(*self.card_tap_gap))
            cx, cy = cells[idx]
            # Land anywhere on the card, like a finger would.
            self.tap(*self._rand_in_zone(cx, cy, size[0] // 3, size[1] // 3))
        if confirm_xy is not None:
            time.sleep(random.uniform(*self.card_confirm_pause))
            self.tap(int(confirm_xy[0]), int(confirm_xy[1]))
        return None

    #: per-character delay (seconds) when typing — `input text` blasts the whole
    #: string instantly, which some IMEs drop characters from. Typing char by char
    #: at a human cadence is slower but lands every keystroke.
    type_delay_range: tuple[float, float] = (0.06, 0.14)

    def text(self, value: str) -> None:
        """Type a string into the focused field, one character at a time.

        The field must already be focused (tap it first). Space is sent as `%s`
        — `input text` treats a literal space as an argument separator and would
        otherwise drop everything after it. Config validation guarantees `value`
        holds only characters this can carry.
        """
        log.info("text %r%s", value, " [dry]" if self.dry_run else "")
        if self.dry_run:
            return
        for ch in value:
            self.device.shell("input", "text", "%s" if ch == " " else ch)
            time.sleep(random.uniform(*self.type_delay_range))

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
            roi = action.get("roi")
            m = find_named(frame, self.store, action["template"], thr,
                           roi=tuple(roi) if roi else None)
            if not m.found:
                if action.get("optional"):
                    # The template is a state we may or may not need to change
                    # — a picker row that is already ticked, say. Absent is a
                    # legitimate outcome, not a failure.
                    log.debug("tap_template '%s' absent (optional), skipping",
                              action["template"])
                    return None
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
            spec = action["ms"]
            # A pair asks for a fresh draw every time: a fixed wait repeated
            # thousands of times is the metronome half of a bot's signature —
            # tap POSITION was already jittered, the gaps between taps were not.
            if isinstance(spec, (list, tuple)):
                ms = int(random.uniform(float(spec[0]), float(spec[1])))
                log.info("wait %dms (jittered %s)", ms, list(spec))
            else:
                ms = int(spec)
                log.info("wait %dms", ms)
            time.sleep(ms / 1000)
            return None
        if kind == "key":
            self.key(int(action["code"]))
            return None
        if kind == "text":
            self.text(str(action["value"]))
            return None
        if kind == "jump":
            self.jump(
                int(action["cx"]), int(action["cy"]),
                int(action.get("rx", 150)), int(action.get("ry", 55)),
            )
            return None
        if kind == "slide":
            hold = action.get("hold_ms")
            self.slide(
                int(action["cx"]), int(action["cy"]),
                int(action.get("rx", 150)), int(action.get("ry", 55)),
                hold_ms=int(hold) if hold is not None else None,
            )
            return None
        if kind == "relay_tap":
            self.relay_tap(
                action.get("x"), action.get("y"),
                taps=action.get("taps"),
            )
            return None
        if kind == "faststart_tap":
            self.faststart_tap(
                action.get("x"), action.get("y"),
                taps=action.get("taps"), gap_ms=action.get("gap_ms"),
            )
            return None
        if kind == "solve_cards":
            return self.solve_cards(
                frame,
                [tuple(c) for c in action["cells"]],
                tuple(action["cell_size"]),
                pick=int(action.get("pick", 2)),
                gap_min=float(action.get("gap_min", 0.04)),
                confirm_xy=action.get("confirm_xy"),
            )
        if kind == "restart_app":
            self.restart_app()
            return None
        if kind == "run_config":
            self.run_config(str(action["config"]), episodes=action.get("episodes"))
            return None
        if kind == "close_popup":
            self.close_popup(
                int(action["x"]), int(action["y"]),
                settle_ms=action.get("settle_ms"),
                verify=action.get("verify"),
                retries=action.get("retries"),
                threshold=action.get("threshold"),
            )
            return None
        if kind == "goto":
            return str(action["state"])
        if kind == "stop":
            return "__stop__"
        raise ActError(f"unknown action type: {kind!r}")
