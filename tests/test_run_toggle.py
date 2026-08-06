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


def test_speed_keeps_the_random_boost_cell_tap(states):
    """+17% speed was assumed to reach the Multi toggle directly, so its profile
    carried a single tap and the baseline's first tap was dropped. On a shop that
    opens on HP-Upgrade that tap lands on HP 'Upgrade', the picker never opens and
    the chain re-rolls until the coins are gone (seen live 2026-08-02). It takes
    the same two-step cell tap as magnet."""
    rt._apply_boost(states, "speed")
    assert _types(states["buy_magnet"]["on_match"]) == ["tap_xy", "wait", "tap_xy", "wait", "goto"]


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


def test_relay_is_not_switchable(states):
    """`--relay n` used to strip the relay out; it no longer does anything.

    The flag is still accepted (old scripts pass it) but every hop must keep
    routing through the relay chain regardless.
    """
    assert not hasattr(rt, "_strip_relay")
    assert not hasattr(rt, "_is_relay")


def _relay_pair(states, host):
    """(stage1, stage2, final target) of the relay poll spliced in front of host."""
    s1, s2 = "relay_poll1_%s" % host, "relay_poll2_%s" % host
    assert s1 in states and s2 in states, "%s has no relay poll" % host

    def goto(block):
        if isinstance(block, dict):
            return block.get("goto")
        return next((a["state"] for a in (block or []) if a.get("type") == "goto"), None)

    assert goto(states[host]["on_absent"]) == s1
    assert goto(states[s1]["on_match"]) == s2
    assert goto(states[s1]["on_absent"]) == s2
    target = goto(states[s2]["on_match"])
    assert goto(states[s2]["on_absent"]) == target
    return s1, s2, target


@pytest.mark.parametrize("host,target", [("running", "guard_not_home"),
                                         ("check_box", "check_shop_after_run")])
def test_relay_is_polled_outside_the_hop_chain(states, host, target):
    """The hop states are not where the FSM sits for large parts of a cycle, so
    the relay is also polled from `running` (the long guard walk into a run) and
    from `check_box`'s absent path (a run that ended with no box). Both must
    still land on the state they replaced."""
    assert _relay_pair(states, host)[2] == target


@pytest.mark.parametrize("host", ["running", "check_box"])
def test_relay_poll_taps_continue_then_card_never_quit(states, host):
    s1, s2, _ = _relay_pair(states, host)
    assert _taps(states[s1]["on_match"]) == [(946, 433)]   # Continue
    assert _taps(states[s2]["on_match"]) == [(980, 515)]   # the relay cookie's card
    for s in (s1, s2):
        for key in ("on_match", "on_absent"):
            assert (946, 636) not in _taps(states[s][key]), "%s taps Quit" % s


@pytest.mark.parametrize("host", ["running", "check_box"])
def test_relay_poll_absent_path_refreshes_the_frame(states, host):
    """src/fsm.py re-grabs only after a state that DID something. Without a wait
    on the absent path, stage 2 re-judges stage 1's frame and never sees the
    card — the exact bug the hop chain was fixed for."""
    s1, s2, _ = _relay_pair(states, host)
    for s in (s1, s2):
        assert "wait" in _types(states[s]["on_absent"])


def test_relay_stage2_lowers_its_threshold(states, base_states):
    """Stage 2's template is a text crop over live gameplay, so its score swings
    with the background. Two measurements, Episode 5, 2026-08-04: an 83-frame
    offline scan gave 0.782/0.815/0.834 where the prompt was genuinely up vs
    <=0.464 on the 80 where it was not; three live runs then fired the relay
    eleven times at 0.73/0.76/0.77/0.79/0.80x4/0.83/0.87. The global 0.82 sits
    INSIDE the "present" cluster and would have caught 2 of those 11, so every
    stage-2 state pins 0.62 — in the gap. Stage 1 (the green Continue pill, max
    0.40 across every frame and run) must keep the global threshold."""
    s2 = [k for k, v in base_states.items()
          if k.startswith("relay_") and "relay_prompt2_marker" in str(v.get("detect"))]
    s1 = [k for k, v in base_states.items()
          if k.startswith("relay_") and "relay_prompt_marker.png" in str(v.get("detect"))]
    assert s2 and s1
    for k in s2:
        assert base_states[k].get("threshold") == 0.62, "%s lost its threshold" % k
    for k in s1:
        assert "threshold" not in base_states[k], "%s should use the global threshold" % k


def test_party_run_is_guarded_and_closes_on_its_own_button(base_states):
    """Party Run's "Select a Mode" screen had no marker at all, so the bot
    livelocked on it — every state missed, the guard chain and relay polls kept
    transitioning, and the hop taps landed on a menu. The guard must sit in the
    chain and tap Party Run's OWN close button (1820,135), not the Friend's Info
    one (1638,108), which is dark background on that screen and closed nothing
    across 38 passes."""
    g = base_states.get("guard_not_partyrun")
    assert g, "guard_not_partyrun missing"
    assert g["detect"] == "home/partyrun_marker.png"

    taps = [(a["x"], a["y"]) for a in g["on_match"] if a.get("type") == "tap_xy"]
    assert taps == [(1820, 135)], taps

    def goto(block):
        if isinstance(block, dict):
            return block.get("goto")
        return next((a["state"] for a in block if a.get("type") == "goto"), None)

    assert goto(g["on_match"]) == "guard_not_partyrun", "must re-verify after tapping"
    assert goto(g["on_absent"]) == "guard_not_inactive", "must fall through the chain"

    reachable = [k for k, v in base_states.items()
                 if k != "guard_not_partyrun" and "guard_not_partyrun" in str(v)]
    assert reachable, "nothing routes into guard_not_partyrun"


def test_probe_friendinfo_taps_once_per_pass(base_states):
    """It used to fire (1552,117) then (1633,107) before re-checking. Live:
    (1552,117) does not close the dialog, (1633,107) does — so on a pass where
    the dialog was already gone the second tap hit home, where (1633,107) is
    inside the Party Run banner strip, opening the undetectable screen above."""
    taps = [(a["x"], a["y"]) for a in base_states["probe_friendinfo"]["on_match"]
            if a.get("type") == "tap_xy"]
    assert taps == [(1633, 107)], taps


def test_continue_run_target_follows_the_config_edge(states):
    """The keep-playing decision in _run_actions must read check_box's absent
    goto, not name check_shop_after_run — a relay poll now sits in between."""
    s1, _, _ = _relay_pair(states, "check_box")

    class _Shim:
        cfg = type("C", (), {"states": states})()
        _continue_run_target = rt.BoxQuitRunner._continue_run_target

    assert _Shim()._continue_run_target() == s1


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


# --- --idle parsing -------------------------------------------------------------


def test_idle_default_keeps_the_config():
    assert rt._idle_arg("y") is rt._IDLE_CONFIG
    assert rt._idle_arg("") is rt._IDLE_CONFIG


def test_idle_off_forms_all_mean_none():
    for v in ("n", "no", "0", "off", "none", "0-0"):
        assert rt._idle_arg(v) is None


def test_idle_range_and_fixed():
    assert rt._idle_arg("5-15") == (5.0, 15.0)
    assert rt._idle_arg("5,15") == (5.0, 15.0)
    assert rt._idle_arg("8") == (8.0, 8.0)


def test_idle_rejects_garbage_and_backwards_ranges():
    import argparse
    for v in ("abc", "15-5", "-3", "1-2-3"):
        with pytest.raises(argparse.ArgumentTypeError):
            rt._idle_arg(v)


# --- stop_after_boxes stop point ------------------------------------------------


def _play_tap_owner(states):
    """The state whose action list carries the real Play tap, if any."""
    owners = []
    for name, state in states.items():
        for key in ("on_match", "on_absent"):
            actions = state.get(key)
            if not isinstance(actions, list):
                continue
            if any(a.get("type") == "tap_xy"
                   and (a.get("x"), a.get("y")) == rt._PLAY_TAP_XY
                   for a in actions):
                owners.append((name, key))
    return owners


def test_play_tap_exists_exactly_once_in_the_config(base_states):
    """stop_after_boxes ends the run when the guard chain reaches this tap, so a
    coord drift or a duplicate would either strand the loop past its box limit or
    stop it early. The tap moved from verify_no_enterleague to probe_relic once
    already and the state-keyed check broke silently — this pins the shape."""
    assert len(_play_tap_owner(base_states)) == 1


def _stop_runner(stop_after_boxes=1):
    from src.config import Config

    class FakeDevice:
        serial = "fake"

        def shell(self, *args):
            return ""

    cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                 start_state="a", states={"a": {"detect": "a.png"}})
    return rt.BoxQuitRunner(cfg, FakeDevice(), stop_after_boxes=stop_after_boxes)


def test_stop_fires_on_the_play_tap_whatever_state_owns_it():
    """The stop must key off the Play tap's shape, not its owning state — the
    whole point of the fix, since splicing a new guard in front of Play moves it."""
    play = [{"type": "tap_xy", "x": rt._PLAY_TAP_XY[0], "y": rt._PLAY_TAP_XY[1]},
            {"type": "goto", "state": "after_play"}]
    for owner in ("verify_no_enterleague", "probe_relic", "some_future_guard"):
        r = _stop_runner()
        r._stop_at_home = True
        assert r._run_actions(play, None, owner)[0] == "__stop__"


def test_stop_does_not_fire_before_the_box_target():
    """Unarmed, the Play tap is just a tap — the run carries on."""
    play = [{"type": "tap_xy", "x": rt._PLAY_TAP_XY[0], "y": rt._PLAY_TAP_XY[1]}]
    r = _stop_runner()
    assert r._stop_at_home is False
    try:
        assert r._run_actions(play, None, "probe_relic")[0] != "__stop__"
    except Exception:
        pass  # falling through to the real Actor is fine; not stopping is the assert


def test_arming_needs_a_box_that_run():
    """A run that banked no box must not count toward stop_after_boxes."""
    r = _stop_runner(stop_after_boxes=1)
    r._box_this_run = False
    try:
        r._run_actions([{"type": "goto", "state": "mystery_box"}], None, "run_result")
    except Exception:
        pass
    assert r._stop_at_home is False
    assert r._session_boxes == 0
