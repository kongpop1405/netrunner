"""Phase 0 fixes — match_timeout, reachability warn, error wrapping, alert cooldown."""
import json
import logging
import subprocess

import numpy as np
import pytest

import src.alert as alertmod
import src.fsm as fsm
from src import config as cfgmod
from src.config import Config, unreachable_states
from src.device import AdbError, Device, connect
from src.perceive import Match


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states)


def _patch_find(monkeypatch, found: set[str]):
    monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
        found=name in found, score=1.0 if name in found else 0.1, x=5, y=5, w=2, h=2))


def _patch_grab(monkeypatch):
    monkeypatch.setattr(fsm, "grab",
                        lambda device, retries=2: np.zeros((10, 10, 3), dtype=np.uint8))


# --- match_timeout_ms -----------------------------------------------------------


class TestMatchTimeout:
    def test_stuck_match_escapes_via_on_absent_goto(self, monkeypatch):
        """Marker matched forever + match_timeout_ms 0 -> escape to the absent
        target instead of self-looping for eternity (the mb_open pattern)."""
        _patch_find(monkeypatch, {"a.png", "out.png"})
        _patch_grab(monkeypatch)
        states = {
            "a": {"detect": "a.png",
                  "on_match": [{"type": "goto", "state": "a"}],
                  "on_absent": {"goto": "out"},
                  "match_timeout_ms": 1},
            "out": {"detect": "out.png", "on_match": [{"type": "stop"}]},
        }
        monkeypatch.setattr(fsm.time, "monotonic", _ticking_clock())
        fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=50)  # stop, not max

    def test_explicit_on_match_timeout_wins(self, monkeypatch):
        _patch_find(monkeypatch, {"a.png", "esc.png"})
        _patch_grab(monkeypatch)
        states = {
            "a": {"detect": "a.png",
                  "on_match": [{"type": "goto", "state": "a"}],
                  "on_absent": {"goto": "boom"},
                  "on_match_timeout": {"goto": "esc"},
                  "match_timeout_ms": 1},
            "esc": {"detect": "esc.png", "on_match": [{"type": "stop"}]},
            "boom": {"detect": "a.png", "timeout_ms": 0},
        }
        monkeypatch.setattr(fsm.time, "monotonic", _ticking_clock())
        fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=50)  # esc stops; boom would raise

    def test_stuck_match_without_target_raises(self, monkeypatch):
        _patch_find(monkeypatch, {"a.png"})
        _patch_grab(monkeypatch)
        states = {"a": {"detect": "a.png",
                        "on_match": [{"type": "goto", "state": "a"}],
                        "match_timeout_ms": 1}}
        monkeypatch.setattr(fsm.time, "monotonic", _ticking_clock())
        with pytest.raises(fsm.FsmError, match="still matched"):
            fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=50)

    def test_timer_resets_on_state_change(self, monkeypatch):
        """A ping-pong a->b->a must NOT trip a's match_timeout — the timer is
        per continuous stay, so only a genuine self-loop accumulates."""
        _patch_find(monkeypatch, {"a.png", "b.png"})
        _patch_grab(monkeypatch)
        states = {
            "a": {"detect": "a.png",
                  "on_match": [{"type": "tap_xy", "x": 1, "y": 1}, {"type": "goto", "state": "b"}],
                  "on_absent": {"goto": "boom"},
                  "match_timeout_ms": 10_000_000},
            "b": {"detect": "b.png", "on_match": [
                {"type": "tap_xy", "x": 2, "y": 2}, {"type": "goto", "state": "a"}]},
            "boom": {"detect": "a.png", "timeout_ms": 0},
        }
        runner = fsm.Runner(_cfg(states, "a"), FakeDevice())
        runner.run(dry_run=True, max_cycles=8)  # must not raise / escape


def _ticking_clock(step: float = 1.0):
    """Monotonic clock advancing `step` seconds per call — makes a 1ms
    match_timeout expire on the second poll without real sleeping."""
    t = {"now": 0.0}

    def clock():
        t["now"] += step
        return t["now"]

    return clock


# --- _detect with no detect names -----------------------------------------------


def test_detect_without_names_survives(monkeypatch):
    """run_toggle patches states post-validation and can leave detect empty —
    the engine must treat that as a miss, not AttributeError on None."""
    _patch_find(monkeypatch, set())
    _patch_grab(monkeypatch)
    states = {"a": {"on_match": [{"type": "stop"}]}}  # no detect at all
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=3)  # must not raise


# --- reachability ---------------------------------------------------------------


def test_unreachable_states_found():
    states = {
        "a": {"on_match": [{"type": "goto", "state": "b"}]},
        "b": {"on_absent": {"goto": "a"}},
        "orphan1": {"on_match": [{"type": "goto", "state": "orphan2"}]},
        "orphan2": {},
    }
    assert unreachable_states(states, "a") == ["orphan1", "orphan2"]


def test_load_warns_on_orphans(tmp_path, tdir, caplog):
    data = {
        "templates_dir": str(tdir),
        "start_state": "a",
        "states": {
            "a": {"detect": "marker.png", "on_match": [{"type": "stop"}]},
            "island": {"detect": "marker.png", "on_match": [{"type": "stop"}]},
        },
    }
    p = tmp_path / "farm.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="netrunner.config"):
        cfgmod.load(p)  # must not raise
    assert any("unreachable" in r.message and "island" in r.message
               for r in caplog.records)


def test_match_timeout_validation(tmp_path, tdir):
    base = {
        "templates_dir": str(tdir),
        "start_state": "a",
        "states": {"a": {"detect": "marker.png", "on_match": [{"type": "stop"}]}},
    }

    def load_with(**fields):
        data = json.loads(json.dumps(base))
        data["states"]["a"].update(fields)
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return cfgmod.load(p)

    with pytest.raises(cfgmod.ConfigError, match="match_timeout_ms"):
        load_with(match_timeout_ms=0)
    with pytest.raises(cfgmod.ConfigError, match="on_match_timeout"):
        load_with(match_timeout_ms=100, on_match_timeout={"state": "a"})
    with pytest.raises(cfgmod.ConfigError, match="without 'match_timeout_ms'"):
        load_with(on_match_timeout={"goto": "a"})
    with pytest.raises(cfgmod.ConfigError, match="targets itself"):
        load_with(match_timeout_ms=100, on_absent={"goto": "a"})
    # valid: escape goto points at a different state
    base["states"]["b"] = {"detect": "marker.png", "on_match": [{"type": "stop"}]}
    load_with(match_timeout_ms=100, on_match_timeout={"goto": "b"})  # must not raise


# --- device error wrapping -------------------------------------------------------


class TestDeviceErrorWrapping:
    def test_memory_error_wrapped_as_adb_error(self, monkeypatch):
        """A MemoryError that survives every retry must surface as AdbError so
        the FSM's fail-streak tolerance engages on the tap path too."""
        def oom_run(cmd, **kw):
            raise MemoryError

        monkeypatch.setattr(subprocess, "run", oom_run)
        monkeypatch.setattr(Device, "retry_backoff_s", 0)
        with pytest.raises(AdbError, match="MemoryError"):
            Device("127.0.0.1:5555").shell("input", "tap", "1", "2")

    def test_connect_timeout_wrapped(self, monkeypatch):
        def hung_run(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 15)

        monkeypatch.setattr(subprocess, "run", hung_run)
        with pytest.raises(AdbError, match="timed out"):
            connect("127.0.0.1:5555")


# --- alert cooldown + timestamp --------------------------------------------------


class TestAlertCooldown:
    @pytest.fixture(autouse=True)
    def _fresh(self, monkeypatch):
        alertmod._last_sent.clear()
        self.posts = []
        monkeypatch.setattr(alertmod.requests, "post",
                            lambda *a, **kw: self.posts.append(kw))

    def test_same_title_muted_within_cooldown(self):
        alertmod.send_alert("http://x", "flappy", "one")
        alertmod.send_alert("http://x", "flappy", "two")
        assert len(self.posts) == 1

    def test_different_titles_not_muted(self):
        alertmod.send_alert("http://x", "a", "m")
        alertmod.send_alert("http://x", "b", "m")
        assert len(self.posts) == 2

    def test_critical_bypasses_cooldown(self):
        alertmod.send_alert("http://x", "crash", "1", critical=True)
        alertmod.send_alert("http://x", "crash", "2", critical=True)
        assert len(self.posts) == 2

    def test_resend_after_cooldown(self, monkeypatch):
        alertmod.send_alert("http://x", "flappy", "one")
        monkeypatch.setattr(alertmod.time, "monotonic",
                            lambda: alertmod._last_sent["flappy"] + alertmod._ALERT_COOLDOWN_S + 1)
        alertmod.send_alert("http://x", "flappy", "two")
        assert len(self.posts) == 2

    def test_timestamp_is_utc_tagged(self):
        alertmod.send_alert("http://x", "t", "m")
        ts = self.posts[0]["json"]["embeds"][0]["timestamp"]
        assert ts.endswith("Z")
