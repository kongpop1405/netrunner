import subprocess

import pytest

from src.device import Device


class _FakeProc:
    def __init__(self, alive=True, write_raises=None):
        self._alive = alive
        self._write_raises = write_raises
        self.stdin = self
        self.writes: list[bytes] = []
        self.terminated = False
        self.closed = False

    # subprocess.Popen surface used by device.py
    def poll(self):
        return None if self._alive else 1

    def write(self, data: bytes):
        if self._write_raises is not None:
            raise self._write_raises
        self.writes.append(data)

    def flush(self):
        pass

    def close(self):
        self.closed = True

    def terminate(self):
        self.terminated = True


def test_fast_tap_writes_input_tap_command(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    device = Device(serial="emulator-5554")
    device.fast_tap(100, 200)
    assert proc.writes == [b"input tap 100 200\n"]


def test_reuses_open_shell_across_calls(monkeypatch):
    proc = _FakeProc()
    opened = {"n": 0}

    def fake_popen(*a, **k):
        opened["n"] += 1
        return proc

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    device = Device(serial="emulator-5554")
    device.fast_tap(1, 1)
    device.fast_tap(2, 2)
    assert opened["n"] == 1
    assert len(proc.writes) == 2


def test_reopens_when_shell_died(monkeypatch):
    procs = [_FakeProc(alive=False), _FakeProc(alive=True)]

    def fake_popen(*a, **k):
        return procs.pop(0)

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    device = Device(serial="emulator-5554")
    device._persistent_shell = _FakeProc(alive=False)  # simulate a stale handle
    device.fast_tap(5, 5)
    # the stale handle must not be reused — a fresh Popen call should back it
    assert device._persistent_shell is not None


def test_falls_back_to_shell_when_popen_fails(monkeypatch):
    def fake_popen(*a, **k):
        raise FileNotFoundError("no adb")

    monkeypatch.setattr(subprocess, "Popen", fake_popen)
    device = Device(serial="emulator-5554")
    calls = []
    monkeypatch.setattr(device, "shell", lambda *args: calls.append(args))
    device.fast_tap(7, 7)
    assert calls == [("input", "tap", "7", "7")]


def test_falls_back_to_shell_when_write_fails(monkeypatch):
    proc = _FakeProc(write_raises=BrokenPipeError("pipe gone"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    device = Device(serial="emulator-5554")
    calls = []
    monkeypatch.setattr(device, "shell", lambda *args: calls.append(args))
    device.fast_tap(9, 9)
    assert calls == [("input", "tap", "9", "9")]
    assert device._persistent_shell is None


def test_close_persistent_shell_terminates_and_clears(monkeypatch):
    proc = _FakeProc()
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: proc)
    device = Device(serial="emulator-5554")
    device.fast_tap(1, 1)
    device.close_persistent_shell()
    assert proc.terminated
    assert proc.closed
    assert device._persistent_shell is None


def test_close_persistent_shell_is_safe_when_never_opened():
    device = Device(serial="emulator-5554")
    device.close_persistent_shell()  # must not raise
