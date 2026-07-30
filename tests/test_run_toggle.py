"""Launcher patching — boost profiles and the on/off strips.

These run against the real boxrun_toggle.json, so a coordinate that drifts out of
sync with the config the profile was lifted from fails here rather than mid-farm.
"""
from __future__ import annotations

import copy

import pytest

from src import boost as boostmod
from src import config as cfgmod
from tools import run_toggle as rt

CONFIG = "config/cookierun/boxrun_toggle.json"


@pytest.fixture(scope="module")
def base_states():
    return cfgmod.load(CONFIG).states


@pytest.fixture
def states(base_states):
    return copy.deepcopy(base_states)


def _taps(actions):
    return [(a["x"], a["y"]) for a in actions if a.get("type") == "tap_xy"]


def _types(actions):
    return [a.get("type") for a in actions]


def _count(states, atype):
    n = 0
    for state in states.values():
        for key in ("on_match", "on_absent"):
            block = state.get(key)
            if isinstance(block, list):
                n += sum(1 for a in block if a.get("type") == atype)
    return n


# --- boost profiles -----------------------------------------------------------


@pytest.mark.parametrize("choice", ["magnet", "speed", "doublecoins"])
def test_boost_points_both_guards_at_its_banner(states, choice):
    """probe_magnet and start_run must read the SAME banner — start_run is the
    enforcement point that decides whether the roll actually landed."""
    rt._apply_boost(states, choice)
    banner = boostmod.PROFILES[choice]["banner"]
    assert states["probe_magnet"]["detect"] == banner
    assert states["start_run"]["detect"] == banner


@pytest.mark.parametrize("choice", ["magnet", "speed", "doublecoins"])
def test_boost_buy_taps_match_the_profile(states, choice):
    rt._apply_boost(states, choice)
    profile = boostmod.PROFILES[choice]
    assert _taps(states["buy_magnet"]["on_match"]) == profile["buy_taps"]
    assert _taps(states["picker"]["on_match"]) == [profile["multibuy"]]


def test_speed_drops_the_random_boost_cell_and_its_wait(states):
    """The +17% speed chain reaches Multi directly (boxrun_speed), so the baseline's
    first tap AND the wait that let its screen settle must both go — a leftover
    wait would just stall the buy for no reason."""
    rt._apply_boost(states, "speed")
    assert _types(states["buy_magnet"]["on_match"]) == ["tap_xy", "wait", "goto"]


def test_boost_none_skips_the_buy_chain(states):
    rt._apply_boost(states, "none")
    for name in ("await_shop", "boost_shop"):
        targets = [a["state"] for a in states[name]["on_match"] if a.get("type") == "goto"]
        assert targets == ["check_heart"]


def test_boost_none_leaves_the_buy_states_untouched(states, base_states):
    """'none' routes around the chain; it must not mangle states it skips."""
    rt._apply_boost(states, "none")
    assert states["buy_magnet"] == base_states["buy_magnet"]
    assert states["probe_magnet"]["detect"] == base_states["probe_magnet"]["detect"]


def test_every_boost_choice_still_validates_as_a_config(states):
    """Patched states must keep every goto target defined — a typo in a profile
    would otherwise only surface as an FsmError mid-run.

    Only the ready profiles: the eight still waiting on a banner crop are
    rejected on purpose (see test_pending_boosts_are_refused).
    """
    names = set(states)
    for choice in (*boostmod.ready(), "none"):
        patched = copy.deepcopy(states)
        rt._apply_boost(patched, choice)
        for state in patched.values():
            for key in ("on_match", "on_absent"):
                block = state.get(key)
                if isinstance(block, list):
                    for a in block:
                        if a.get("type") == "goto":
                            assert a["state"] in names


# --- strips -------------------------------------------------------------------


def test_strip_faststart_removes_the_shared_action(states):
    assert _count(states, "faststart_tap") > 0
    rt._strip_faststart(states)
    assert _count(states, "faststart_tap") == 0


def test_strip_faststart_still_handles_the_pre_migration_ladder(states):
    """Configs may not have been migrated yet — both shapes must strip."""
    states["check_heart"]["on_absent"] = [
        {"type": "tap_xy", "x": 1365, "y": 931},
        {"type": "tap_xy", "x": 985, "y": 515},
        {"type": "wait", "ms": 400},
        {"type": "goto", "state": "running"},
    ]
    rt._strip_faststart(states)
    assert _types(states["check_heart"]["on_absent"]) == ["tap_xy", "goto"]


def test_strip_relay_clears_the_hop_states(states):
    rt._strip_relay(states)
    for name in ("jump_2", "jump_3", "jump_4", "guard_not_inactive"):
        assert not any(rt._is_relay(a) for a in states[name]["on_absent"])


def test_strip_relay_matches_the_pre_migration_tap(states):
    states["jump_2"]["on_absent"] = [
        {"type": "jump", "cx": 238, "cy": 940, "rx": 175, "ry": 55},
        {"type": "tap_xy", "x": 960, "y": 540},
        {"type": "goto", "state": "jump_3"},
    ]
    rt._strip_relay(states)
    assert _types(states["jump_2"]["on_absent"]) == ["jump", "goto"]


def test_strip_jump_and_slide_leave_the_goto(states):
    rt._strip_jump(states)
    rt._strip_slide(states)
    assert "jump" not in _types(states["jump_2"]["on_absent"])
    assert "slide" not in _types(states["jump_3"]["on_absent"])
    assert "goto" in _types(states["jump_2"]["on_absent"])
    assert "goto" in _types(states["jump_3"]["on_absent"])


@pytest.mark.parametrize("choice", [k for k, p in boostmod.PROFILES.items()
                                    if not p.get("banner")])
def test_pending_boosts_are_refused(states, choice):
    """A profile with no banner has no measured coordinates either — sending taps
    at guesses is worse than refusing, so it must fail loudly at launch."""
    with pytest.raises(cfgmod.ConfigError, match="crop the equipped pill"):
        rt._apply_boost(copy.deepcopy(states), choice)
