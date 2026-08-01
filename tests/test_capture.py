import numpy as np
import pytest

from src.capture import CaptureError, grab_band
from src.device import AdbError


class _FakeDevice:
    def __init__(self, band: np.ndarray | None = None, raise_error: Exception | None = None,
                 short_by: int = 0):
        self.band = band
        self.raise_error = raise_error
        self.short_by = short_by
        self.calls: list[str] = []

    def exec_out(self, cmd: str) -> bytes:
        self.calls.append(cmd)
        if self.raise_error is not None:
            raise self.raise_error
        raw = self.band.tobytes()
        return raw[: len(raw) - self.short_by]


def _rgba_band(height: int, width: int) -> np.ndarray:
    # Deterministic content so the BGR conversion is checkable.
    band = np.zeros((height, width, 4), dtype=np.uint8)
    band[..., 0] = 10   # R
    band[..., 1] = 20   # G
    band[..., 2] = 30   # B
    band[..., 3] = 255  # A
    return band


def test_shape_matches_requested_band():
    device = _FakeDevice(_rgba_band(26, 1920))
    out = grab_band(device, y=872, height=26, width=1920)
    assert out.shape == (26, 1920, 3)


def test_rgba_to_bgr_channel_order():
    device = _FakeDevice(_rgba_band(4, 4))
    out = grab_band(device, y=0, height=4, width=4)
    # RGBA (10,20,30,255) -> BGR (30,20,10)
    assert tuple(out[0, 0]) == (30, 20, 10)


def test_byte_offset_math_targets_the_right_row():
    device = _FakeDevice(_rgba_band(10, 1920))
    grab_band(device, y=885, height=10, width=1920)
    cmd = device.calls[0]
    expected_off = 16 + 885 * 1920 * 4
    expected_n = 10 * 1920 * 4
    assert f"+{expected_off + 1}" in cmd
    assert f"-c {expected_n}" in cmd


def test_retries_on_adb_error_then_succeeds(monkeypatch):
    calls = {"n": 0}

    class FlakyDevice:
        def exec_out(self, cmd):
            calls["n"] += 1
            if calls["n"] == 1:
                raise AdbError("transient")
            return _rgba_band(4, 4).tobytes()

    monkeypatch.setattr("time.sleep", lambda s: None)
    out = grab_band(FlakyDevice(), y=0, height=4, width=4, retries=2)
    assert out.shape == (4, 4, 3)
    assert calls["n"] == 2


def test_short_read_raises_capture_error(monkeypatch):
    device = _FakeDevice(_rgba_band(4, 4), short_by=8)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(CaptureError):
        grab_band(device, y=0, height=4, width=4, retries=1)
