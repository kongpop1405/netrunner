"""FSM loop semantics — frame reuse across pure-goto chains, re-grab after acting."""
import numpy as np
import pytest

import src.fsm as fsm
from src.config import Config
from src.perceive import Match


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start):
    return Config(
        device=None, templates_dir=".", poll_ms=1,
        match_threshold=0.8, start_state=start, states=states,
    )


@pytest.fixture
def grabs(monkeypatch):
    """Counts grab() calls; each returns a fresh dummy frame."""
    count = {"n": 0}

    def fake_grab(device, retries=2):
        count["n"] += 1
        return np.zeros((10, 10, 3), dtype=np.uint8)

    monkeypatch.setattr(fsm, "grab", fake_grab)
    return count


def _patch_find(monkeypatch, found_markers: set[str]):
    def fake_find(frame, store, name, threshold):
        hit = name in found_markers
        return Match(found=hit, score=1.0 if hit else 0.1, x=5, y=5, w=2, h=2)

    monkeypatch.setattr(fsm, "find_named", fake_find)


def test_pure_goto_chain_reuses_one_frame(monkeypatch, grabs):
    """a(match->goto b) -> b(absent->goto a) ping-pong: no taps ever run,
    so the whole chain must ride a single capture."""
    _patch_find(monkeypatch, {"a.png"})
    states = {
        "a": {"detect": "a.png", "on_match": [{"type": "goto", "state": "b"}]},
        "b": {"detect": "b.png", "on_absent": {"goto": "a"}, "timeout_ms": 99999},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)
    assert grabs["n"] == 1


def test_tap_invalidates_frame(monkeypatch, grabs):
    """Each cycle taps -> the cached frame is stale -> re-grab every cycle."""
    _patch_find(monkeypatch, {"a.png", "b.png"})
    states = {
        "a": {"detect": "a.png", "on_match": [
            {"type": "tap_xy", "x": 1, "y": 1},
            {"type": "goto", "state": "b"},
        ]},
        "b": {"detect": "b.png", "on_match": [
            {"type": "tap_xy", "x": 2, "y": 2},
            {"type": "goto", "state": "a"},
        ]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(dry_run=True, max_cycles=6)
    assert grabs["n"] == 6


def test_sleep_invalidates_frame(monkeypatch, grabs):
    """Marker absent with no on_absent -> stay + sleep -> next poll re-grabs."""
    _patch_find(monkeypatch, set())
    states = {"a": {"detect": "a.png"}}
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=4)
    assert grabs["n"] == 4


def test_timeout_redirect(monkeypatch, grabs):
    """timeout_ms=0 forces the stuck path immediately -> goto fires."""
    _patch_find(monkeypatch, {"b.png"})
    states = {
        "a": {"detect": "a.png", "on_absent": {"goto": "b"}, "timeout_ms": 0},
        "b": {"detect": "b.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)  # stop, not max


def test_stuck_without_target_raises(monkeypatch, grabs):
    _patch_find(monkeypatch, set())
    states = {"a": {"detect": "a.png", "timeout_ms": 0}}
    with pytest.raises(fsm.FsmError, match="stuck"):
        fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)
