"""NetRunner CLI entrypoint.

    python main.py --list-devices
    python main.py --config config/example_game.json [--device 127.0.0.1:5555] [--dry-run]
"""
from __future__ import annotations

import argparse
import logging
import sys

from src import config as cfgmod
from src.device import AdbError, Device, connect, list_devices
from src.fsm import Runner


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def _resolve_device(address: str, adb: str) -> Device:
    """Connect if given a host:port, otherwise treat as an already-attached serial."""
    if ":" in address:
        return connect(address, adb=adb)
    return Device(address, adb=adb)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="netrunner", description="LDPlayer auto-farm engine")
    ap.add_argument("--config", help="path to a farm FSM config JSON")
    ap.add_argument("--device", help="adb address (127.0.0.1:5555) or serial; "
                                     "overrides config's device")
    ap.add_argument("--dry-run", action="store_true",
                    help="run the FSM but send no taps (validate a config live)")
    ap.add_argument("--max-cycles", type=int, default=None,
                    help="stop after N poll cycles (smoke-test)")
    ap.add_argument("--start-state", default=None,
                    help="override the config's start_state (resume mid-loop)")
    ap.add_argument("--adb", default="adb",
                    help="path to the adb binary (default: 'adb' on PATH). "
                         r"LDPlayer ships one, e.g. C:\LDPlayer\LDPlayer9\adb.exe")
    ap.add_argument("--list-devices", action="store_true", help="list attached devices and exit")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(argv)

    _setup_logging(args.verbose)

    if args.list_devices:
        try:
            serials = list_devices(adb=args.adb)
        except AdbError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if not serials:
            print("no devices in 'device' state. Is LDPlayer running with ADB debugging on?\n"
                  "Try:  adb connect 127.0.0.1:5555")
            return 1
        print("attached devices:")
        for s in serials:
            print(f"  {s}")
        return 0

    if not args.config:
        ap.error("--config is required (or use --list-devices)")

    try:
        cfg = cfgmod.load(args.config)
    except cfgmod.ConfigError as e:
        print(f"config error: {e}", file=sys.stderr)
        return 2

    address = args.device or cfg.device
    if not address:
        print("error: no device given (set 'device' in config or pass --device)", file=sys.stderr)
        return 2

    if args.start_state:
        if args.start_state not in cfg.states:
            print(f"error: --start-state '{args.start_state}' is not a defined state",
                  file=sys.stderr)
            return 2
        cfg.start_state = args.start_state

    try:
        device = _resolve_device(address, args.adb)
        Runner(cfg, device).run(dry_run=args.dry_run, max_cycles=args.max_cycles)
    except AdbError as e:
        print(f"adb error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted, stopping.")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
