"""Capture the current LDPlayer screen to a PNG — for building templates.

    python tools/snap.py --device 127.0.0.1:5555 --out templates/example_game/

Saves a timestamped snap_*.png. Crop the distinctive UI bits out of it (a button,
a banner) with any image editor and save those crops as the template PNGs your
config references. Tight crops match more reliably than whole screens.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import cv2

# allow running as `python tools/snap.py` from repo root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.capture import grab  # noqa: E402
from src.device import AdbError, Device, connect  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="save current emulator screen as PNG")
    ap.add_argument("--device", required=True, help="adb address or serial")
    ap.add_argument("--out", default=".", help="output directory (created if missing)")
    ap.add_argument("--adb", default="adb", help="path to adb binary (default: on PATH)")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    try:
        device = connect(args.device, adb=args.adb) if ":" in args.device else Device(args.device, adb=args.adb)
        frame = grab(device)
    except AdbError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    path = out / f"snap_{time.strftime('%Y%m%d_%H%M%S')}.png"
    cv2.imwrite(str(path), frame)
    h, w = frame.shape[:2]
    print(f"saved {path}  ({w}x{h})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
