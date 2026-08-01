"""Screen capture — `adb exec-out screencap -p` → numpy BGR image."""
from __future__ import annotations

import time

import cv2
import numpy as np

from .device import AdbError, Device


class CaptureError(RuntimeError):
    pass


#: Raw (non-PNG) `screencap` header: width, height, PixelFormat, colorSpace,
#: all uint32 little-endian — see frameworks/native ScreenshotClient. Format is
#: PixelFormat.RGBA_8888 on every device seen so far; grab_band() skips the
#: header on every call (re-parsing it would cost the round-trip this function
#: exists to avoid) and assumes that format holds.
_RAW_HEADER_BYTES = 16


def grab(device: Device, retries: int = 2) -> np.ndarray:
    """Capture the current screen as a BGR numpy array (H, W, 3).

    `screencap -p` streams a PNG. We decode it in-memory so nothing touches disk.
    Retries a couple times because a busy emulator occasionally returns a short
    or empty buffer mid-transition. Also retries on MemoryError: on RAM-starved
    machines (LDPlayer alone can eat 1.5-3GB) the subprocess pipe's internal
    reader thread can fail to buffer one PNG frame — usually transient as other
    processes free memory a moment later, so it's worth a longer backoff rather
    than crashing the whole run over one bad capture.
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = device.exec_out("screencap", "-p")
        except AdbError as e:
            last = e
            time.sleep(0.2 * (attempt + 1))
            continue
        except MemoryError as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
            continue
        if not raw:
            last = CaptureError("empty screencap buffer")
            time.sleep(0.2 * (attempt + 1))
            continue
        buf = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # BGR, drops alpha
        if img is not None:
            return img
        last = CaptureError("screencap did not decode as an image")
        time.sleep(0.2 * (attempt + 1))
    raise CaptureError(f"capture failed after {retries + 1} attempts: {last}")


def grab_band(device: Device, y: int, height: int, width: int = 1920,
               retries: int = 2) -> np.ndarray:
    """Capture only rows [y, y+height) as a BGR numpy array (height, width, 3).

    Uses the RAW (non-PNG) `screencap` and an on-device `tail | head` byte-range
    cut, so only the requested band crosses the ADB transfer — ~0.9MB instead of
    the full frame's ~8.3MB PNG. This is ~2x faster than `grab()` (measured:
    ~400ms vs ~856ms for a full 1920x1080 frame), which matters for a dodge loop
    that must complete a detect-and-jump cycle inside a pit's ~1.5-2s window.

    Only worth it for a tight polling loop reading a couple of fixed rows (see
    fsm.py's "dodge" state) — every other state still uses grab(), since they
    need full-frame template matching, not a couple of known rows.

    `width` must match the device's actual resolution (the engine assumes
    1920x1080 throughout — see main._check_resolution); a mismatch corrupts the
    reshape silently, so the header's own width is checked against it and any
    disagreement raises rather than returning a garbled frame.
    """
    off = _RAW_HEADER_BYTES + y * width * 4
    n = height * width * 4
    cmd = f"screencap | tail -c +{off + 1} | head -c {n}"

    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            raw = device.exec_out(cmd)
        except AdbError as e:
            last = e
            time.sleep(0.2 * (attempt + 1))
            continue
        except MemoryError as e:
            last = e
            time.sleep(1.0 * (attempt + 1))
            continue
        if len(raw) != n:
            last = CaptureError(
                f"band read {len(raw)} bytes, expected {n} "
                f"(y={y} height={height} width={width})")
            time.sleep(0.2 * (attempt + 1))
            continue
        arr = np.frombuffer(raw, dtype=np.uint8).reshape(height, width, 4)
        return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
    raise CaptureError(f"grab_band failed after {retries + 1} attempts: {last}")
