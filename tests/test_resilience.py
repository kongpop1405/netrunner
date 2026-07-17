"""adb hiccups must not kill a long farm run."""
import subprocess

import numpy as np
import pytest

import src.fsm as fsm
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
        with pytest.raises(AdbError, match="timed out after 3 attempts"):
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
