"""Launch boxrun_toggle.json with Fast Start / boost / Jump / Slide / Relay chosen per run.

    python tools/run_toggle.py --faststart y --boost magnet --jump y --slide y --relay y --launch

Patches the loaded Config's states dict in memory before handing it to the
same Runner main.py uses — the JSON on disk (config/cookierun/boxrun_toggle.json)
never changes. See RUN.md for what each flag does to the FSM.
"""
from __future__ import annotations

import argparse
import copy
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import main as netrunner_main
from src import boost as boostmod
from src import config as cfgmod
from src.device import AdbError
from src.fsm import Runner
from src.perceive import PerceiveError, find_named, read_counter

CONFIG_PATH = "config/cookierun/boxrun_toggle.json"

# (cx, cy) of the Fast Start spam tap — must match check_heart/after_play in
# boxrun_toggle.json exactly, since we strip these actions out by (x, y) match.
_FASTSTART_XY = (985, 515)


#: warmup_burst jump/slide zone coords — must match jump_2/jump_3's zones exactly
#: (same Jump/Slide buttons).
_JUMP_ZONE = dict(cx=238, cy=940, rx=175, ry=55)
_SLIDE_ZONE = dict(cx=1671, cy=937, rx=175, ry=55)


class BoxQuitRunner(Runner):
    """Runner that quits a run early only after N total boxes have been banked,
    and (in jump=n+slide=n mode) fires a one-shot warm-up burst at the very
    start of each run instead of never tapping jump/slide at all.

    check_box's on_match goes straight to quit_run every time boxcounter_marker
    is seen (i.e. on the run that collects box #1), so this subclass decides
    whether to let that goto through.

    It prefers reading the "[?] xN" pill: OCR gives the run's actual box count,
    so quit_after means "quit at the Nth box of THIS run", which is what the
    flag reads like. When OCR is unavailable or unreadable it falls back to
    counting runs-that-had-a-box across the session — the only thing the engine
    could do before, and still correct, just coarser. Either way quit_after=0
    (the default) means never quit early.

    warmup_burst (only when both jump and slide are stripped, see main()):
    community-reported game bug — a run with ZERO jump/slide taps the whole
    way through doesn't get counted by the game (no box, no reward), even
    though blind relay taps kept it alive. guard_not_inactive is a HOUSEKEEPING
    guard the FSM revisits every ~4 hops for the rest of the run (it's not a
    one-time entry point) — an earlier version patched its goto in the config
    itself and ended up firing the 10-tap burst every single cycle instead of
    once, which is the "bot secretly keeps jumping/sliding mid-loop" bug this
    fixes. Tracking the one-shot in Python (self._warmup_done, reset per run
    in run_result) is the only way to tell "first time this run" from "just
    revisiting the guard chain" — the static FSM has no per-run variables.
    """

    #: Where the box-count digits sit relative to the counter marker's match:
    #: (dx, dy, w, h) from the marker's top-left. The pill draws "[?] xN"; this
    #: box covers N only — measured off live 1920x1080 frames (marker top-left
    #: (118,360), digit ink at x 300-324, y 360-415), not estimated.
    #:
    #: The previous (70, 0, 90, 90) started inside the "[?]" glyph and ran past
    #: the digits, which read as a confident 25 on a pill showing x1 — worse than
    #: unreadable, since --quit-after-boxes would act on it. This box either reads
    #: the digit or returns None, and None correctly falls back to counting runs.
    #: Reads ~half the frames: the digits are white with a heavy black outline, so
    #: Otsu splits them into a hollow ring that tesseract often rejects.
    COUNTER_OFFSET = (176, -4, 60, 64)

    def __init__(self, *args, quit_after: int = 0, warmup_burst: bool = False,
                 counter_template: str = "boxcounter_marker.png", **kwargs):
        super().__init__(*args, **kwargs)
        self.quit_after = quit_after
        self.boxes_seen = 0
        self.warmup_burst = warmup_burst
        self.counter_template = counter_template
        self._warmup_done = False
        self._box_counted_this_run = False
        self._ocr_available = True  # flipped off after the first failure

    def _read_box_count(self, frame) -> int | None:
        """The run's box count from the counter pill, or None if unreadable.

        Locates the pill by its own marker rather than a fixed rectangle, so the
        region follows the marker instead of assuming where the HUD sits. One
        failure disables OCR for the session: pytesseract missing or a missing
        tesseract binary will not fix itself mid-run, and retrying every few
        seconds would just spam the log.
        """
        if frame is None or not self._ocr_available:
            return None
        try:
            m = find_named(frame, self.store, self.counter_template,
                           self.cfg.match_threshold)
            if not m.found:
                return None
            dx, dy, w, h = self.COUNTER_OFFSET
            x = m.x - m.w // 2 + dx
            y = m.y - m.h // 2 + dy
            return read_counter(frame, (max(0, x), max(0, y), w, h))
        except PerceiveError as e:
            logging.getLogger("netrunner").warning(
                "box-count OCR unavailable, falling back to counting runs: %s", e)
            self._ocr_available = False
            return None

    def _run_actions(self, actions, frame, state):
        if state == "check_box":
            is_quit_goto = any(
                a.get("type") == "goto" and a.get("state") == "quit_run" for a in actions
            )
            if is_quit_goto:
                log = logging.getLogger("netrunner")
                in_run = self._read_box_count(frame)
                if in_run is not None:
                    if self.quit_after <= 0 or in_run < self.quit_after:
                        log.info("check_box: box %d this run (quit_after=%d) — continuing run",
                                 in_run, self.quit_after)
                        return "check_shop_after_run", False
                    log.info("check_box: box %d/%d this run — quitting run",
                             in_run, self.quit_after)
                else:
                    # boxcounter_marker.png stays on screen for the rest of the run
                    # once a box is collected (see the state's own _note) — check_box
                    # gets revisited every ~4 hops for the REST of that same run, so
                    # without this guard boxes_seen was incrementing once per revisit
                    # (4 hits in ~10s, all one run's box) instead of once per run.
                    if not self._box_counted_this_run:
                        self._box_counted_this_run = True
                        self.boxes_seen += 1
                    if self.quit_after <= 0 or self.boxes_seen < self.quit_after:
                        log.info("check_box: %d run(s) with a box so far (quit_after=%d) "
                                 "— continuing run [no OCR]",
                                 self.boxes_seen, self.quit_after)
                        return "check_shop_after_run", False
                    log.info("check_box: %d/%d runs-with-a-box reached — quitting run [no OCR]",
                             self.boxes_seen, self.quit_after)

        # run_result marks the run as over -> the NEXT time we reach
        # guard_not_inactive is a new run and needs its own burst, and the
        # next box seen (if any) belongs to a new run and should count again.
        if state == "run_result":
            self._warmup_done = False
            self._box_counted_this_run = False

        if (self.warmup_burst and not self._warmup_done
                and state == "guard_not_inactive"
                and any(a.get("type") == "goto" and a.get("state") == "jump_2" for a in actions)):
            self._warmup_done = True
            logging.getLogger("netrunner").info(
                "warmup_burst: one-shot 10-tap jump/slide burst (jump=n+slide=n run start)")
            for _ in range(5):
                self.actor.jump(**_JUMP_ZONE)
                self.actor.slide(**_SLIDE_ZONE)
            return "jump_2", True

        return super()._run_actions(actions, frame, state)


def _strip_faststart(states: dict) -> None:
    """Drop every Fast Start tap from on_absent lists.

    Handles both shapes: the shared `faststart_tap` action, and the older inline
    tap_xy(985,515)+wait ladder that configs carried before the migration
    (tools/migrate_action_types.py) — configs may be in either state.
    """
    for state in states.values():
        absent = state.get("on_absent")
        if not isinstance(absent, list):
            continue
        kept = []
        skip_next_wait = False
        for action in absent:
            if skip_next_wait and action.get("type") == "wait":
                skip_next_wait = False
                continue
            skip_next_wait = False
            if action.get("type") == "faststart_tap":
                continue
            if action.get("type") == "tap_xy" and (action.get("x"), action.get("y")) == _FASTSTART_XY:
                skip_next_wait = True
                continue
            kept.append(action)
        state["on_absent"] = kept


def _apply_boost(states: dict, choice: str) -> None:
    """Retarget the buy chain via src.boost, which owns the profiles now.

    Wraps a states dict in a throwaway Config because apply_boost works on one —
    the profiles used to live here, which meant only this launcher could pick a
    boost and only for this one config.
    """
    from src.config import Config

    shim = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.85,
                  start_state=next(iter(states)), states=states)
    boostmod.apply_boost(shim, choice)


def _strip_jump(states: dict) -> None:
    for name in ("jump_2", "jump_4", "guard_not_inactive"):
        state = states[name]
        state["on_absent"] = [a for a in state["on_absent"] if a.get("type") != "jump"]


def _strip_slide(states: dict) -> None:
    state = states["jump_3"]
    state["on_absent"] = [a for a in state["on_absent"] if a.get("type") != "slide"]


_RELAY_XY = (960, 540)


def _is_relay(action: dict) -> bool:
    """True for either shape of the relay tap — the shared `relay_tap` action or
    the pre-migration inline tap_xy(960,540)."""
    if action.get("type") == "relay_tap":
        return True
    return (action.get("type") == "tap_xy"
            and (action.get("x"), action.get("y")) == _RELAY_XY)


def _strip_relay(states: dict) -> None:
    """Drop the Cookie Relay Boost tap from the in-run hop states."""
    for name in ("jump_2", "jump_3", "jump_4", "guard_not_inactive"):
        state = states[name]
        state["on_absent"] = [a for a in state["on_absent"] if not _is_relay(a)]


def _yn(v: str) -> bool:
    return v.strip().lower() in ("y", "yes", "1", "true")


#: sentinel for --idle "keep whatever the config says" (the default)
_IDLE_CONFIG = object()


def _idle_arg(v: str):
    """Parse --idle: y/'' = keep the config's range, n/0/off = no idle,
    'MIN-MAX' (or 'MIN,MAX') = custom range, a single number = fixed delay."""
    s = v.strip().lower()
    if s in ("", "y", "yes", "config"):
        return _IDLE_CONFIG
    if s in ("n", "no", "0", "none", "off"):
        return None
    sep = "-" if "-" in s.lstrip("-") else ","
    try:
        if sep in s.lstrip("-"):
            lo, hi = (float(p) for p in s.split(sep, 1))
        else:
            lo = hi = float(s)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"expected y, n, a number, or MIN-MAX (got '{v}')") from None
    if lo < 0 or hi < lo:
        raise argparse.ArgumentTypeError(
            f"idle range must be 0 <= MIN <= MAX (got '{v}')")
    if (lo, hi) == (0.0, 0.0):
        return None
    return (lo, hi)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="boxrun_toggle launcher")
    ap.add_argument("--faststart", type=_yn, required=True)
    ap.add_argument("--boost", choices=boostmod.CHOICES, required=True,
                    help="which boost to Multi-Buy before each run "
                         "('none' skips the buy chain). "
                         # argparse %-formats help text; boost labels carry literal
                         # % ("+17% base speed") that would raise ValueError.
                         + boostmod.describe_choices().replace("%", "%%"))
    ap.add_argument("--jump", type=_yn, required=True)
    ap.add_argument("--slide", type=_yn, required=True)
    ap.add_argument("--relay", type=_yn, required=True)
    ap.add_argument("--quit-after-boxes", type=int, default=0,
                    help="quit a run once this many total boxes have been banked "
                         "this session (0 = never quit early, default)")
    ap.add_argument("--idle", type=_idle_arg, default=_IDLE_CONFIG,
                    help="random idle between games: y = the config's range "
                         "(default), n = none, MIN-MAX = custom seconds, or a "
                         "single number for a fixed delay")
    ap.add_argument("--device", default=None)
    ap.add_argument("--adb", default=None)
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--max-cycles", type=int, default=None)
    ap.add_argument("--start-state", default=None,
                    help="override the config's start_state (resume mid-loop, or "
                         "stage a screen and prove one state's routing)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    load_dotenv()
    netrunner_main._setup_logging(args.verbose)
    log = logging.getLogger("netrunner")

    adb = args.adb or netrunner_main._find_adb()

    try:
        cfg = cfgmod.load(CONFIG_PATH)
    except cfgmod.ConfigError as e:
        log.error("config error: %s", e)
        print(f"config error: {e}", file=sys.stderr)
        return 2

    states = copy.deepcopy(cfg.states)
    if not args.faststart:
        _strip_faststart(states)
    _apply_boost(states, args.boost)
    if not args.jump:
        _strip_jump(states)
    if not args.slide:
        _strip_slide(states)
    if not args.relay:
        _strip_relay(states)
    cfg.states = states

    if args.idle is None:
        # inter_game_state without a delay fails config validation on load,
        # so clear both when idling is switched off
        cfg.inter_game_delay_s = None
        cfg.inter_game_state = None
    elif args.idle is not _IDLE_CONFIG:
        cfg.inter_game_delay_s = args.idle
        if cfg.inter_game_state is None:
            cfg.inter_game_state = cfg.start_state

    if args.start_state:
        if args.start_state not in states:
            log.error("unknown --start-state '%s'", args.start_state)
            print(f"error: unknown --start-state '{args.start_state}'", file=sys.stderr)
            return 2
        cfg.start_state = args.start_state

    address = args.device or os.environ.get("NETRUNNER_DEVICE")
    if args.launch:
        from src.launcher import LauncherError, ensure_ready, resolve_index
        try:
            index = resolve_index(adb, None, address)
            address = ensure_ready(index, adb, boot_timeout=120.0)
        except LauncherError as e:
            log.error("launch failed: %s", e)
            print(f"launch failed: {e}", file=sys.stderr)
            return 2

    if not address:
        try:
            address = netrunner_main._detect_device(adb, hint=cfg.device)
        except AdbError as e:
            log.error("%s", e)
            print(f"error: {e}", file=sys.stderr)
            return 2
    if not address:
        msg = ("no running emulator found. Start LDPlayer (ADB debugging on), "
               "or pass --device / set NETRUNNER_DEVICE in .env")
        log.error("%s", msg)
        print(f"error: {msg}", file=sys.stderr)
        return 2
    log.info("device: %s  adb: %s", address, adb)
    idle_desc = ("config" if args.idle is _IDLE_CONFIG
                 else "off" if args.idle is None else f"{args.idle[0]:g}-{args.idle[1]:g}s")
    log.info("flags: faststart=%s boost=%s jump=%s slide=%s relay=%s quit_after_boxes=%d idle=%s",
              args.faststart, args.boost, args.jump, args.slide, args.relay,
              args.quit_after_boxes, idle_desc)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    try:
        device = netrunner_main._resolve_device(address, adb)
        netrunner_main._check_resolution(device)
        BoxQuitRunner(
            cfg, device, webhook_url=webhook_url, quit_after=args.quit_after_boxes,
            warmup_burst=(not args.jump and not args.slide),
            restarter=netrunner_main.build_restarter(cfg, device, adb, None),
        ).run(dry_run=args.dry_run, max_cycles=args.max_cycles)
    except AdbError as e:
        log.error("adb error: %s", e)
        print(f"adb error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted, stopping.")
        return 0
    except Exception:  # noqa: BLE001 — top-level guard so crashes reach the log file
        log.exception("unhandled crash")
        print("crashed — full traceback saved to the log file", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
