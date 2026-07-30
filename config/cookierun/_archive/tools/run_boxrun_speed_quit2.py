"""Launch boxrun_speed_quit2.json — box farm on any episode, +17% base speed boost,
quits a run early once 2 total boxes have been banked this session.

    python tools/boxrun_speed_quit2.py --launch

check_box/quit_run (ported into boxrun_speed_quit2.json from boxrun_speed.json) bail a
run via the pause menu the instant a Mystery Box is collected — the config
alone can't tell "this is the 1st box run" from "this is the 2nd", since the
static FSM has no per-run variables (see boxrun_toggle's BoxQuitRunner in
run_toggle.py, same pattern). This script reuses that same Runner subclass,
fixed at quit_after=2 — no prompts, just run it.
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

import main as netrunner_main
from src import config as cfgmod
from src.device import AdbError
from tools.run_toggle import BoxQuitRunner

CONFIG_PATH = "config/cookierun/boxrun_speed_quit2.json"
QUIT_AFTER_BOXES = 2


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="boxrun_speed_quit2 launcher (fixed quit-after-2-boxes)")
    ap.add_argument("--device", default=None)
    ap.add_argument("--adb", default=None)
    ap.add_argument("--launch", action="store_true")
    ap.add_argument("--max-cycles", type=int, default=None)
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
    log.info("boxrun_speed_quit2: quit_after_boxes=%d", QUIT_AFTER_BOXES)

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    try:
        device = netrunner_main._resolve_device(address, adb)
        netrunner_main._check_resolution(device)
        BoxQuitRunner(
            cfg, device, webhook_url=webhook_url, quit_after=QUIT_AFTER_BOXES,
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
