"""Screen capture — `adb exec-out screencap` → numpy BGR image."""
from __future__ import annotations

import struct
import time

import cv2
import numpy as np

from .device import AdbError, Device


class CaptureError(RuntimeError):
    pass


#: screencap's raw header: width, height, format as little-endian uint32, then a
#: 4-byte field (colorSpace since Android 9) before the pixels — 16 bytes total.
_RAW_HEADER = 16

#: Pixel formats we can decode from a raw screencap. Values are Android's
#: PixelFormat constants; both are 4 bytes per pixel, differing only in whether
#: the 4th channel carries alpha, which we drop either way.
_RAW_RGBA_8888 = 1
_RAW_RGBX_8888 = 2
_RAW_DECODABLE = {_RAW_RGBA_8888, _RAW_RGBX_8888}


def _decode_raw(buf: bytes) -> np.ndarray | None:
    """Decode an uncompressed `screencap` buffer, or None if it isn't one we know.

    Returning None (rather than raising) lets grab() fall back to the PNG wire
    format on any surprise — an unexpected pixel format, a short buffer, a header
    that doesn't describe the payload — so an emulator we haven't seen degrades to
    "slower" instead of "broken".
    """
    if len(buf) < _RAW_HEADER:
        return None
    width, height, fmt = struct.unpack("<III", buf[:12])
    if fmt not in _RAW_DECODABLE:
        return None
    expected = width * height * 4
    if not expected or len(buf) - _RAW_HEADER != expected:
        return None
    arr = np.frombuffer(buf, dtype=np.uint8, count=expected,
                        offset=_RAW_HEADER).reshape(height, width, 4)
    return cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)


def grab(device: Device, retries: int = 2) -> np.ndarray:
    """Capture the current screen as a BGR numpy array (H, W, 3).

    Plain `screencap` streams uncompressed RGBA plus a 16-byte header; `-p` makes
    the device PNG-encode it first. Both arrive over the same adb pipe and decode
    to identical pixels (PNG is lossless), so the compression is pure overhead:
    measured 2026-08-18 against LDPlayer at 1920x1080, the raw wire format ran
    479ms median against PNG's 629ms — 149ms/grab, and grab is the single most
    frequent operation in the engine (every poll, plus every close_popup verify).
    So raw is tried first and PNG is the fallback for any device whose header
    describes something we don't recognise.

    Retries a couple times because a busy emulator occasionally returns a short
    or empty buffer mid-transition. Also retries on MemoryError: on RAM-starved
    machines (LDPlayer alone can eat 1.5-3GB) the subprocess pipe's internal
    reader thread can fail to buffer one frame — usually transient as other
    processes free memory a moment later, so it's worth a longer backoff rather
    than crashing the whole run over one bad capture. The raw buffer is ~8MB
    against PNG's ~1.7MB, which is the one thing PNG had going for it, so a
    MemoryError drops straight to the PNG path for that attempt.
    """
    last: Exception | None = None
    for attempt in range(retries + 1):
        prefer_png = isinstance(last, MemoryError)
        try:
            if prefer_png:
                raw = device.exec_out("screencap", "-p")
            else:
                raw = device.exec_out("screencap")
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
        if not prefer_png:
            img = _decode_raw(raw)
            if img is not None:
                return img
            # Not a raw buffer we understand — ask for PNG instead of burning a
            # whole retry, since the device will keep answering the same way.
            try:
                raw = device.exec_out("screencap", "-p")
            except (AdbError, MemoryError) as e:
                last = e
                time.sleep(0.2 * (attempt + 1))
                continue
        buf = np.frombuffer(raw, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # BGR, drops alpha
        if img is not None:
            return img
        last = CaptureError("screencap did not decode as an image")
        time.sleep(0.2 * (attempt + 1))
    raise CaptureError(f"capture failed after {retries + 1} attempts: {last}")
