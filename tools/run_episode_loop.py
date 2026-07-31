"""Farm Mystery Boxes across Episodes in rotation, switching Episode after each
one banks N boxes.

    python tools/run_episode_loop.py --order 4,2,7,6,5,3,1 --boxes-per-episode 3 --launch

Loops forever: switch_episode() to the next Episode in --order, run
boxrun_toggle.json (via BoxQuitRunner, same engine tools/run_toggle.py uses)
until --boxes-per-episode runs have ended with a box, then move to the next
Episode. Ctrl+C to stop; the current run finishes its natural exit points
(quit_run/run_result), it is not killed mid-tap.

Same Fast Start / boost / Jump / Slide / Relay flags as run_toggle.py, applied
identically to every Episode in the rotation — this tool does not vary them
per Episode.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import main as netrunner_main
from src import config as cfgmod
from src.device import AdbError
from src.perceive import TemplateStore
from tools.run_toggle import (
    CONFIG_PATH,
    BoxQuitRunner,
    _apply_boost,
    _strip_faststart,
    _strip_jump,
    _strip_relay,
    _strip_slide,
    _yn,
)
from tools.switch_episode import SwitchEpisodeError, switch_episode


def _episode_list(v: str) -> list[int]:
    try:
        eps = [int(p.strip()) for p in v.split(",") if p.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected comma-separated ints, got '{v}'") from None
    if not eps:
        raise argparse.ArgumentTypeError("--order must list at least one episode")
    return eps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="rotate boxrun_toggle across Episodes")
    ap.add_argument("--order", type=_episode_list, required=True,
                     help="comma-separated episode numbers to cycle through, "
                          "e.g. 4,2,7,6,5,3,1")
    ap.add_argument("--boxes-per-episode", type=int, default=3,
                     help="switch to the next episode after this many runs have "
                          "ended with a box banked (default: 3)")
    ap.add_argument("--faststart", type=_yn, required=True)
    ap.add_argument("--boost", default="none")
    ap.add_argument("--jump", type=_yn, required=True)
    ap.add_argument("--slide", type=_yn, required=True)
    ap.add_argument("--relay", type=_yn, required=True)
    ap.add_argument("--device", default=None)
    ap.add_argument("--adb", default=None)
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--templates-dir", default="templates/cookierun")
    ap.add_argument("--reveal-snaps", default="snaps/box_reveals",
                     help="directory for Mystery Box reveal screenshots, one per "
                          "mb_open pass, named ep<N>_<timestamp>_<seq>.png "
                          "(default: snaps/box_reveals; 'none' disables)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-cycles", type=int, default=None,
                     help="cap FSM cycles per episode run (debug/test only — "
                          "production use leaves this unset)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args(argv)

    if args.boxes_per_episode <= 0:
        print("error: --boxes-per-episode must be >= 1", file=sys.stderr)
        return 2

    reveal_dir = None if args.reveal_snaps.strip().lower() in ("none", "off", "")\
        else Path(args.reveal_snaps)

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

    base_states = copy.deepcopy(cfg.states)
    if not args.faststart:
        _strip_faststart(base_states)
    _apply_boost(base_states, args.boost)
    if not args.jump:
        _strip_jump(base_states)
    if not args.slide:
        _strip_slide(base_states)
    if not args.relay:
        _strip_relay(base_states)

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
    log.info("episode order: %s  boxes_per_episode: %d", args.order, args.boxes_per_episode)
    log.info("reveal snaps: %s", reveal_dir or "disabled")
    log.info("flags: faststart=%s boost=%s jump=%s slide=%s relay=%s",
              args.faststart, args.boost, args.jump, args.slide, args.relay)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    store = TemplateStore(args.templates_dir)

    try:
        device = netrunner_main._resolve_device(address, adb)
        netrunner_main._check_resolution(device)
    except AdbError as e:
        log.error("adb error: %s", e)
        print(f"adb error: {e}", file=sys.stderr)
        return 2

    try:
        for episode in itertools.cycle(args.order):
            log.info("=== switching to Episode %d ===", episode)
            try:
                switch_episode(device, store, episode)
            except SwitchEpisodeError as e:
                log.error("switch_episode(%d) failed: %s — skipping this episode", episode, e)
                continue
            log.info("Episode %d selected, farming until %d boxes banked",
                      episode, args.boxes_per_episode)

            states = copy.deepcopy(base_states)
            run_cfg = copy.deepcopy(cfg)
            run_cfg.states = states

            runner = BoxQuitRunner(
                run_cfg, device, webhook_url=webhook_url,
                warmup_burst=(not args.jump and not args.slide),
                stop_after_boxes=args.boxes_per_episode,
                reveal_snap_dir=reveal_dir,
                episode_label=f"ep{episode}",
                restarter=netrunner_main.build_restarter(run_cfg, device, adb, None),
            )
            runner.run(dry_run=args.dry_run, max_cycles=args.max_cycles)
            log.info("Episode %d done (%d/%d boxes banked)",
                      episode, runner._session_boxes, args.boxes_per_episode)
            if args.max_cycles is not None:
                log.info("--max-cycles set (debug mode) — stopping after one episode")
                return 0
    except KeyboardInterrupt:
        print("\ninterrupted, stopping.")
        return 0
    except AdbError as e:
        log.error("adb error: %s", e)
        print(f"adb error: {e}", file=sys.stderr)
        return 2
    except Exception:  # noqa: BLE001 — top-level guard so crashes reach the log file
        log.exception("unhandled crash")
        print("crashed — full traceback saved to the log file", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
