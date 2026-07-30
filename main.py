"""NetRunner CLI entrypoint.

    python main.py --list-devices
    python main.py --config config/example_game.json [--device 127.0.0.1:5555] [--dry-run]
"""
from __future__ import annotations

import argparse
import glob
import logging
import os
import re
import shutil
import sys

from dotenv import load_dotenv

from src import config as cfgmod
from src.alert import setup_file_logging
from src.device import AdbError, Device, connect, list_devices
from src.fsm import Runner

_LDPLAYER_ADB_GLOBS = (
    r"C:\LDPlayer\LDPlayer*\adb.exe",
    r"C:\Program Files\LDPlayer\LDPlayer*\adb.exe",
    r"D:\LDPlayer\LDPlayer*\adb.exe",
)

# LDPlayer instance ports: 5555 + 2*index
_PROBE_PORTS = (5555, 5557, 5559, 5561)


def _find_adb() -> str:
    """Locate adb: ADB_PATH from .env > adb on PATH > newest LDPlayer install."""
    env_path = os.environ.get("ADB_PATH")
    if env_path:
        return env_path
    if shutil.which("adb"):
        return "adb"

    def version_key(path: str) -> int:
        m = re.search(r"LDPlayer(\d+)", path, re.IGNORECASE)
        return int(m.group(1)) if m else 0

    hits = [p for pattern in _LDPLAYER_ADB_GLOBS for p in glob.glob(pattern)]
    if hits:
        return max(hits, key=version_key)
    return "adb"  # let the first adb call raise with a clear error


def _detect_device(adb: str, hint: str | None) -> str | None:
    """Find the one running LDPlayer instance; None if none, AdbError if ambiguous.

    LDPlayer dual-lists each instance as both `emulator-NNNN` and `127.0.0.1:NNNN+1`,
    so prefer the TCP entries to avoid counting one instance twice.
    """
    probe = [hint] if hint and ":" in hint else []
    probe += [f"127.0.0.1:{p}" for p in _PROBE_PORTS]
    serials = list_devices(adb=adb)
    if not serials:
        for address in dict.fromkeys(probe):
            try:
                connect(address, adb=adb)
            except AdbError:
                continue
        serials = list_devices(adb=adb)
    tcp = [s for s in serials if s.startswith("127.0.0.1:")]
    candidates = tcp or serials
    if not candidates:
        return None
    if len(candidates) > 1:
        raise AdbError(
            "multiple devices found: " + ", ".join(candidates)
            + " — pick one with --device or NETRUNNER_DEVICE in .env"
        )
    return candidates[0]


def _check_resolution(device: Device) -> None:
    """Warn loudly if the emulator isn't 1920x1080 — templates are cropped at that
    size and match near-zero at any other resolution, which looks like a 'bot does
    nothing / taps randomly' bug rather than a config problem."""
    log = logging.getLogger("netrunner")
    try:
        w, h = device.resolution()
    except AdbError as e:
        log.warning("could not read screen resolution: %s", e)
        return
    if (w, h) != (1920, 1080):
        log.warning(
            "emulator resolution is %dx%d, NOT 1920x1080. Templates are cropped at "
            "1920x1080 and will NOT match at other sizes — the bot will appear to do "
            "nothing or tap randomly. Fix: set the LDPlayer instance to 1920x1080 "
            "(dpi 240) and restart it.", w, h,
        )
    else:
        log.info("resolution 1920x1080 OK")


def _setup_logging(verbose: bool) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    log_path = setup_file_logging(verbose=verbose)
    logging.getLogger("netrunner").info("logging to %s", log_path)


def _resolve_device(address: str, adb: str) -> Device:
    """Connect if given a host:port, otherwise treat as an already-attached serial."""
    if ":" in address:
        return connect(address, adb=adb)
    return Device(address, adb=adb)


def build_restarter(cfg, device: Device, adb: str, instance: int | None):
    """A Restarter for the config's session resets, or None if it wants none.

    Prefers ldconsole runapp (same path --launch uses) when the LDPlayer install
    can be found, because `am start` needs a resolvable launcher activity and
    some builds don't expose one. Falls back to plain adb otherwise, which is
    all a bare `--device` connection can do.
    """
    if cfg.session_reset_s is None:
        return None
    from src.session import DEFAULT_PACKAGE, Restarter

    package = cfg.package or DEFAULT_PACKAGE
    start_app = None
    try:
        from src.launcher import _ldconsole_path, _start_app, resolve_index
        ldconsole = _ldconsole_path(adb)
        idx = resolve_index(adb, instance, device.serial)
        start_app = lambda: _start_app(ldconsole, idx, device, package)  # noqa: E731
        logging.getLogger("netrunner").info(
            "session resets will relaunch via ldconsole (instance %d)", idx)
    except Exception as e:  # noqa: BLE001 — any LDPlayer lookup failure is non-fatal
        logging.getLogger("netrunner").info(
            "session resets will relaunch via am start (%s)", e)
    return Restarter(device=device, package=package, start_app=start_app)


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
    ap.add_argument("--adb", default=None,
                    help="path to the adb binary (default: ADB_PATH from .env, "
                         "else 'adb' on PATH). LDPlayer ships one, e.g. "
                         r"C:\LDPlayer\LDPlayer14\adb.exe")
    ap.add_argument("--list-devices", action="store_true", help="list attached devices and exit")
    ap.add_argument("--launch", action="store_true",
                    help="auto-launch: bring the LDPlayer instance up and start Cookie Run "
                         "before farming (idempotent — safe on every run)")
    ap.add_argument("--instance", type=int, default=None,
                    help="LDPlayer instance index to --launch (adb port = 5555 + 2*index). "
                         "Default: derive from --device/NETRUNNER_DEVICE, else 0")
    ap.add_argument("--boot-timeout", type=float, default=120.0,
                    help="seconds to wait for a launched instance to finish booting (default 120)")
    ap.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    args = ap.parse_args(argv)

    load_dotenv()
    _setup_logging(args.verbose)

    # machine-specific bits live in .env; CLI flag > .env > auto-detect
    adb = args.adb or _find_adb()

    if args.list_devices:
        try:
            _detect_device(adb, hint=None)  # probe common ports so a fresh boot shows up
        except AdbError:
            pass  # multiple devices is fine when just listing
        try:
            serials = list_devices(adb=adb)
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
        logging.getLogger("netrunner").error("config error: %s", e)
        print(f"config error: {e}", file=sys.stderr)
        return 2

    address = args.device or os.environ.get("NETRUNNER_DEVICE")

    if args.launch:
        from src.launcher import LauncherError, ensure_ready, resolve_index
        try:
            index = resolve_index(adb, args.instance, address)
            address = ensure_ready(index, adb, boot_timeout=args.boot_timeout)
        except LauncherError as e:
            logging.getLogger("netrunner").error("launch failed: %s", e)
            print(f"launch failed: {e}", file=sys.stderr)
            return 2

    if not address:
        try:
            address = _detect_device(adb, hint=cfg.device)
        except AdbError as e:
            logging.getLogger("netrunner").error("%s", e)
            print(f"error: {e}", file=sys.stderr)
            return 2
    if not address:
        msg = ("no running emulator found. Start LDPlayer (ADB debugging on), "
               "or pass --device / set NETRUNNER_DEVICE in .env")
        logging.getLogger("netrunner").error("%s", msg)
        print(f"error: {msg}", file=sys.stderr)
        return 2
    logging.getLogger("netrunner").info("device: %s  adb: %s", address, adb)

    if args.start_state:
        if args.start_state not in cfg.states:
            print(f"error: --start-state '{args.start_state}' is not a defined state",
                  file=sys.stderr)
            return 2
        cfg.start_state = args.start_state

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")

    try:
        device = _resolve_device(address, adb)
        _check_resolution(device)
        Runner(
            cfg, device, webhook_url=webhook_url,
            restarter=build_restarter(cfg, device, adb, args.instance),
        ).run(dry_run=args.dry_run, max_cycles=args.max_cycles)
    except AdbError as e:
        logging.getLogger("netrunner").error("adb error: %s", e)
        print(f"adb error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\ninterrupted, stopping.")
        return 0
    except Exception:  # noqa: BLE001 — top-level guard so crashes reach the log file
        logging.getLogger("netrunner").exception("unhandled crash")
        print("crashed — full traceback saved to the log file", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
