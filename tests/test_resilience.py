"""adb hiccups must not kill a long farm run."""
import subprocess

import numpy as np
import pytest

import src.fsm as fsm
from src.act import ActError
from src.config import Config
from src.device import AdbError, Device
from src.perceive import Match


class _Proc:
    def __init__(self, returncode=0, stdout="ok", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestDeviceRetry:
    def test_transient_timeout_then_success(self, monkeypatch):
        calls = {"n": 0}

        def fake_run(cmd, **kw):
            calls["n"] += 1
            if calls["n"] == 1:
                raise subprocess.TimeoutExpired(cmd, 15)
            return _Proc()

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(Device, "retry_backoff_s", 0)
        assert Device("127.0.0.1:5555").shell("input", "tap", "1", "2") == "ok"
        assert calls["n"] == 2

    def test_gives_up_after_all_retries(self, monkeypatch):
        calls = {"n": 0}

        def fake_run(cmd, **kw):
            calls["n"] += 1
            raise subprocess.TimeoutExpired(cmd, 15)

        monkeypatch.setattr(subprocess, "run", fake_run)
        monkeypatch.setattr(Device, "retry_backoff_s", 0)
        d = Device("127.0.0.1:5555")
        # attempt count derived from Device.retries — a hardcoded "3 attempts"
        # here went stale when the retry budget was widened for low-RAM hosts.
        with pytest.raises(AdbError, match=f"timed out after {d.retries + 1} attempts"):
            d.shell("input", "tap", "1", "2")
        assert calls["n"] == d.retries + 1

    def test_nonzero_exit_retried_then_raised(self, monkeypatch):
        monkeypatch.setattr(subprocess, "run",
                            lambda cmd, **kw: _Proc(returncode=1, stderr="device offline"))
        monkeypatch.setattr(Device, "retry_backoff_s", 0)
        with pytest.raises(AdbError, match="device offline"):
            Device("127.0.0.1:5555").shell("input", "tap", "1", "2")

    def test_missing_binary_not_retried(self, monkeypatch):
        calls = {"n": 0}

        def fake_run(cmd, **kw):
            calls["n"] += 1
            raise FileNotFoundError

        monkeypatch.setattr(subprocess, "run", fake_run)
        with pytest.raises(AdbError, match="adb not found"):
            Device("127.0.0.1:5555", adb="nope.exe").shell("input", "tap", "1", "2")
        assert calls["n"] == 1  # a missing binary will never appear on a retry


class _FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states)


def _patch_find(monkeypatch, found):
    monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
        found=name in found, score=1.0 if name in found else 0.1, x=5, y=5, w=2, h=2))


class TestFsmTolerance:
    """A timed-out tap mid-farm must cost one cycle, not the whole run."""

    def test_survives_transient_adb_failures(self, monkeypatch):
        _patch_find(monkeypatch, {"a.png"})
        calls = {"n": 0}

        def flaky_grab(device, retries=2):
            calls["n"] += 1
            if calls["n"] in (2, 3):  # two bad cycles in the middle
                raise AdbError("adb timed out: input tap 83 938")
            return np.zeros((10, 10, 3), dtype=np.uint8)

        monkeypatch.setattr(fsm, "grab", flaky_grab)
        states = {"a": {"detect": "a.png", "on_match": [{"type": "wait", "ms": 0}]}}
        runner = fsm.Runner(_cfg(states, "a"), _FakeDevice())
        runner.run(max_cycles=5)  # must not raise
        assert calls["n"] >= 4  # kept going past the two failures

    def test_gives_up_once_adb_stays_broken(self, monkeypatch):
        _patch_find(monkeypatch, {"a.png"})

        def dead_grab(device, retries=2):
            raise AdbError("device offline")

        monkeypatch.setattr(fsm, "grab", dead_grab)
        states = {"a": {"detect": "a.png", "on_match": [{"type": "wait", "ms": 0}]}}
        runner = fsm.Runner(_cfg(states, "a"), _FakeDevice())
        with pytest.raises(AdbError, match="device offline"):
            runner.run(max_cycles=50)

    def test_tap_template_miss_does_not_crash(self, monkeypatch):
        """A prompt that vanishes between detect and tap costs the action, not the run."""
        _patch_find(monkeypatch, {"a.png"})
        monkeypatch.setattr(fsm, "grab",
                            lambda device, retries=2: np.zeros((10, 10, 3), dtype=np.uint8))

        class BoomActor:
            def __init__(self, *a, **kw):
                pass

            def run(self, action, frame):
                if action["type"] == "tap_template":
                    raise ActError(
                        "tap_template 'gone.png' not on screen (best score 0.11 < 0.82)"
                    )
                return action["state"] if action["type"] == "goto" else None

        monkeypatch.setattr(fsm, "Actor", BoomActor)
        states = {"a": {
            "detect": "a.png",
            "on_match": [
                {"type": "tap_template", "template": "gone.png"},
                {"type": "goto", "state": "a"},
            ],
        }}
        runner = fsm.Runner(_cfg(states, "a"), _FakeDevice())
        runner.run(max_cycles=3)  # must not raise

    def test_streak_resets_after_a_good_cycle(self, monkeypatch):
        """Scattered failures below the tolerance must never accumulate into a stop."""
        _patch_find(monkeypatch, {"a.png"})
        calls = {"n": 0}

        def alternating_grab(device, retries=2):
            calls["n"] += 1
            if calls["n"] % 2 == 0:
                raise AdbError("adb timed out")
            return np.zeros((10, 10, 3), dtype=np.uint8)

        monkeypatch.setattr(fsm, "grab", alternating_grab)
        states = {"a": {"detect": "a.png", "on_match": [{"type": "wait", "ms": 0}]}}
        runner = fsm.Runner(_cfg(states, "a"), _FakeDevice())
        runner.run(max_cycles=20)  # 10 failures total, never 5 in a row


class TestCaptureWireFormat:
    """grab() asks for the uncompressed screencap first — the device PNG-encoding
    every frame cost 149ms/grab against LDPlayer (629ms median PNG vs 479ms raw,
    interleaved n=8, 2026-08-18), and grab is the engine's most frequent call:
    once per poll plus once per close_popup verify. PNG is lossless, so the two
    wire formats decode to identical pixels and the compression bought nothing.

    What these tests protect is the fallback: a device whose header describes
    something the raw decoder doesn't recognise must quietly get PNG rather than
    a wrong-shaped array or a crash.
    """

    #: RGBA_8888, the format LDPlayer reports (verified live 2026-08-18).
    RGBA_8888 = 1

    def _raw(self, w, h, fmt=1, pixel=(10, 20, 30, 255), header=16):
        import struct
        body = bytes(pixel) * (w * h)
        head = struct.pack("<III", w, h, fmt) + b"\x00" * (header - 12)
        return head + body

    def _device(self, responses):
        """Device whose exec_out replays `responses` keyed by the args it gets."""
        class D:
            serial = "fake"
            calls = []

            def exec_out(self, *args):
                D.calls.append(args)
                out = responses.get(args)
                if isinstance(out, Exception):
                    raise out
                return out
        D.calls = []
        return D()

    def test_raw_buffer_decodes_without_asking_for_png(self):
        from src.capture import grab
        dev = self._device({("screencap",): self._raw(4, 3)})
        img = grab(dev)
        assert img.shape == (3, 4, 3)
        # RGBA (10,20,30) -> BGR (30,20,10); alpha dropped
        assert tuple(img[0][0]) == (30, 20, 10)
        assert type(dev).calls == [("screencap",)], type(dev).calls

    def test_unknown_pixel_format_falls_back_to_png(self):
        import cv2
        from src.capture import grab
        png = cv2.imencode(".png", np.zeros((3, 4, 3), dtype=np.uint8))[1].tobytes()
        dev = self._device({
            ("screencap",): self._raw(4, 3, fmt=99),  # not RGBA/RGBX
            ("screencap", "-p"): png,
        })
        assert grab(dev).shape == (3, 4, 3)
        assert ("screencap", "-p") in type(dev).calls

    def test_short_buffer_falls_back_to_png(self):
        """Header says 4x3 but the payload is truncated — reshape would raise, so
        the size check must catch it and route to PNG instead."""
        import cv2
        from src.capture import grab
        truncated = self._raw(4, 3)[:-9]
        png = cv2.imencode(".png", np.zeros((3, 4, 3), dtype=np.uint8))[1].tobytes()
        dev = self._device({
            ("screencap",): truncated,
            ("screencap", "-p"): png,
        })
        assert grab(dev).shape == (3, 4, 3)
        assert ("screencap", "-p") in type(dev).calls

    def test_memory_error_retries_on_the_smaller_png_wire(self):
        """The raw buffer is ~8MB against PNG's ~1.7MB, so the one failure mode
        where PNG genuinely helps is a RAM-starved pipe — that retry must not ask
        for raw again."""
        import cv2
        from src.capture import grab
        png = cv2.imencode(".png", np.zeros((3, 4, 3), dtype=np.uint8))[1].tobytes()
        dev = self._device({
            ("screencap",): MemoryError("pipe buffer"),
            ("screencap", "-p"): png,
        })
        monkey = getattr(__import__("src.capture", fromlist=["time"]), "time")
        orig_sleep = monkey.sleep
        monkey.sleep = lambda s: None
        try:
            assert grab(dev).shape == (3, 4, 3)
        finally:
            monkey.sleep = orig_sleep
        assert type(dev).calls[-1] == ("screencap", "-p"), type(dev).calls
