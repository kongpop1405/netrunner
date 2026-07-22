"""Screen capture — `adb exec-out screencap -p` → numpy BGR image."""
from __future__ import annotations

import time

import cv2
import numpy as np

from .device import AdbError, Device


class CaptureError(RuntimeError):
    pass


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
