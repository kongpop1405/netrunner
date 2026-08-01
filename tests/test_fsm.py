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


def test_linear_goto_chain_reuses_one_frame(monkeypatch, grabs):
    """a -> b -> c pure-goto probe chain: no taps ever run and no state repeats,
    so the whole chain must ride a single capture."""
    _patch_find(monkeypatch, {"a.png", "b.png", "c.png"})
    states = {
        "a": {"detect": "a.png", "on_match": [{"type": "goto", "state": "b"}]},
        "b": {"detect": "b.png", "on_match": [{"type": "goto", "state": "c"}]},
        "c": {"detect": "c.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)
    assert grabs["n"] == 1


def test_goto_pingpong_forces_regrab(monkeypatch, grabs):
    """a <-> b goto cycle with no actions: on ONE cached frame the matching is
    deterministic, so without a forced re-grab the loop would spin on a stale
    frame forever. The engine must re-capture once the chain revisits a state."""
    _patch_find(monkeypatch, {"a.png"})
    states = {
        "a": {"detect": "a.png", "on_match": [{"type": "goto", "state": "b"}]},
        "b": {"detect": "b.png", "on_absent": {"goto": "a"}, "timeout_ms": 99999},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=12)
    assert 1 < grabs["n"] < 12  # re-grabs, but still amortizes the chain


def test_no_act_pingpong_alerts_livelock(monkeypatch, grabs):
    """States keep flipping (same-state counter never trips) but nothing is
    ever acted on -> the no-act livelock warning must fire."""
    monkeypatch.setattr(fsm, "_STUCK_STATE_WARN_CYCLES", 5)
    alerts = []
    monkeypatch.setattr(fsm, "send_alert", lambda *a, **k: alerts.append(a))
    _patch_find(monkeypatch, {"a.png"})
    states = {
        "a": {"detect": "a.png", "on_match": [{"type": "goto", "state": "b"}]},
        "b": {"detect": "b.png", "on_absent": {"goto": "a"}, "timeout_ms": 99999},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=30)
    assert any("livelock" in a[1].lower() for a in alerts)


def test_absent_retries_delays_on_absent(monkeypatch, grabs):
    """absent_retries=2: the first two absent polls stay put; the third follows
    on_absent. Replaces the old hand-written state_2/_3 retry chains."""
    _patch_find(monkeypatch, {"b.png"})
    states = {
        "a": {"detect": "a.png", "absent_retries": 2, "on_absent": {"goto": "b"}},
        "b": {"detect": "b.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)
    # poll 1+2 = retries (each re-grabs after the sleep), poll 3 = goto b,
    # b rides the same frame -> stop. 3 grabs total, run ends before max_cycles.
    assert grabs["n"] == 3


def test_detect_any_of_picks_matching_branch(monkeypatch, grabs):
    """detect list + dict on_match: the branch of the template actually found
    must run — here b.png is on screen, so the b-branch stops the run. The
    a-branch routes to a state that would raise FsmError if ever reached."""
    _patch_find(monkeypatch, {"b.png"})
    states = {
        "s": {
            "detect": ["a.png", "b.png"],
            "on_match": {
                "a.png": [{"type": "goto", "state": "boom"}],
                "b.png": [{"type": "stop"}],
            },
        },
        "boom": {"detect": "a.png", "timeout_ms": 0},
    }
    fsm.Runner(_cfg(states, "s"), FakeDevice()).run(max_cycles=10)  # no FsmError
    assert grabs["n"] == 1


def test_per_state_threshold_overrides_global(monkeypatch, grabs):
    """Global threshold 0.8 would miss a 0.5-score match; the state's own
    threshold 0.4 must win and accept it."""
    def fake_find(frame, store, name, threshold):
        return Match(found=0.5 >= threshold, score=0.5, x=5, y=5, w=2, h=2)

    monkeypatch.setattr(fsm, "find_named", fake_find)
    states = {
        "a": {"detect": "a.png", "threshold": 0.4, "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=5)
    assert grabs["n"] == 1  # found on the first poll -> stop


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


def _dodge_state(**overrides):
    base = {
        "dodge": True,
        "until": "result.png",
        "on_until": {"goto": "done"},
        "check_until_every": 2,
        "max_ms": 50,
        "on_max_ms": {"goto": "stuck"},
        "ground_y": 885,
        "platform_y": 675,
        "probe_x": [1150, 1500],
        "edge_min": 100,
        "on_pit": {"type": "jump", "cx": 238, "cy": 940, "rx": 175, "ry": 55},
        "cooldown_ms": 0,
    }
    base.update(overrides)
    return base


@pytest.fixture
def dodge_env(monkeypatch):
    """Stubs grab_band (always returns a dummy band) and lets each test control
    ground_present's answers and find_named's until-marker hit via closures."""
    monkeypatch.setattr(fsm, "grab_band",
                        lambda device, y, h: np.zeros((h, 10, 3), dtype=np.uint8))
    return {}


def test_dodge_exits_via_until_marker(monkeypatch, grabs, dodge_env):
    """until marker found on a periodic full-frame check -> on_until's goto."""
    monkeypatch.setattr(fsm, "ground_present", lambda *a, **k: True)  # never a pit
    _patch_find(monkeypatch, {"result.png"})
    states = {
        "run": _dodge_state(),
        "done": {"detect": "done.png", "on_match": [{"type": "stop"}]},
        "stuck": {"detect": "stuck.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "run"), FakeDevice()).run(dry_run=True, max_cycles=1)


def test_dodge_exits_via_max_ms_when_until_never_found(monkeypatch, grabs, dodge_env):
    monkeypatch.setattr(fsm, "ground_present", lambda *a, **k: True)
    _patch_find(monkeypatch, set())  # until marker never appears
    states = {
        "run": _dodge_state(max_ms=1),
        "stuck": {"detect": "stuck.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "run"), FakeDevice()).run(dry_run=True, max_cycles=1)


def test_dodge_jumps_when_ground_absent(monkeypatch, grabs, dodge_env):
    """No ground in the probe band -> on_pit action runs (a jump)."""
    calls = []
    monkeypatch.setattr(fsm, "ground_present", lambda *a, **k: False)  # always a pit
    _patch_find(monkeypatch, set())  # until marker never appears this run

    class RecordingActor:
        UNSURE = object()

        def __init__(self, *a, **k):
            pass

        def run(self, action, frame):
            calls.append(action)
            return None

    monkeypatch.setattr(fsm, "Actor", RecordingActor)
    states = {
        "run": _dodge_state(max_ms=30),
        "stuck": {"detect": "stuck.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "run"), FakeDevice()).run(dry_run=True, max_cycles=1)
    jump_calls = [c for c in calls if c.get("type") == "jump"]
    assert jump_calls, "expected at least one jump action when ground is absent"


def test_dodge_config_rejects_tap_template_on_pit():
    from pathlib import Path

    from src.config import ConfigError, _validate_dodge_state
    state = _dodge_state(
        until="boxrun/result_marker.png",
        on_pit={"type": "tap_template", "template": "boxrun/result_marker.png"},
    )
    with pytest.raises(ConfigError, match="jump or tap_xy"):
        _validate_dodge_state("run", state, {"done", "stuck"}, Path("templates/cookierun"))


def test_dodge_config_requires_all_fields():
    from pathlib import Path

    from src.config import ConfigError, _validate_dodge_state
    state = {"dodge": True}
    with pytest.raises(ConfigError, match="missing field"):
        _validate_dodge_state("run", state, {"done", "stuck"}, Path("templates/cookierun"))
