"""Run Send-Life across Episodes 1-6 in order, switching Episode once each
one's friend list is exhausted.

    python tools/run_sendlife_loop.py --launch

sendlife.json's own FSM already scans/sends/scrolls a single Episode's
friend list to the bottom and stops (see config/cookierun/sendlife.json).
This wrapper is what repeats that per Episode: switch_episode() to the next
number in --order, run sendlife.json with a fresh Runner until its FSM hits
`stop`, then move on. Unlike tools/run_episode_loop.py (which cycles box
farming forever), this stops for good after the last Episode in --order —
Send-Life has no "keep going" mode, there's just a fixed list of Episodes to
clear once.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import main as netrunner_main
from src import config as cfgmod
from src.device import AdbError
from src.fsm import Runner
from src.perceive import TemplateStore
from tools.switch_episode import SwitchEpisodeError, switch_episode

CONFIG_PATH = "config/cookierun/sendlife.json"


def _episode_list(v: str) -> list[int]:
    try:
        eps = [int(p.strip()) for p in v.split(",") if p.strip()]
    except ValueError:
        raise argparse.ArgumentTypeError(f"expected comma-separated ints, got '{v}'") from None
    if not eps:
        raise argparse.ArgumentTypeError("--order must list at least one episode")
    return eps


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="run Send-Life across Episodes 1-6")
    ap.add_argument("--order", type=_episode_list, default=[1, 2, 3, 4, 5, 6],
                     help="comma-separated episode numbers to clear in order "
                          "(default: 1,2,3,4,5,6)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--adb", default=None)
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--templates-dir", default="templates/cookierun")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-cycles", type=int, default=None,
                     help="cap FSM cycles per episode run (debug/test only)")
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
    log.info("episode order: %s", args.order)

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
        for i, episode in enumerate(args.order):
            log.info("=== switching to Episode %d ===", episode)
            # One retry before giving up on this episode: a failed switch is
            # usually the map not having settled yet (grab() raced a swipe's
            # scroll animation), not a genuinely missing banner — a fresh
            # attempt from home commonly succeeds where the first one timed
            # out mid-swipe (see docs/RUN.md Send-Life section).
            switched = False
            for attempt in range(2):
                try:
                    switch_episode(device, store, episode)
                    switched = True
                    break
                except SwitchEpisodeError as e:
                    verb = "retrying once" if attempt == 0 else "skipping this episode"
                    log.warning("switch_episode(%d) failed: %s — %s", episode, e, verb)
            if not switched:
                continue

            log.info("Episode %d selected, sending Life to every friend", episode)
            Runner(
                cfg, device, webhook_url=webhook_url,
                restarter=netrunner_main.build_restarter(cfg, device, adb, None),
            ).run(dry_run=args.dry_run, max_cycles=args.max_cycles)
            log.info("Episode %d done", episode)

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

    log.info("all %d episodes done", len(args.order))
    print(f"done — sent Life across Episodes {args.order}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
