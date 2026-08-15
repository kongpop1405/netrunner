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
    across 38 passes.

    The close must also be a verified one. Those 38 passes were silent because a
    bare tap_xy cannot tell a wrong coordinate from a slow fade and self-looping
    on it logs nothing either way; close_popup re-reads the frame after the
    settle and warns when the marker never clears."""
    g = base_states.get("guard_not_partyrun")
    assert g, "guard_not_partyrun missing"
    assert g["detect"] == "home/partyrun_marker.png"

    closes = [a for a in g["on_match"] if a.get("type") == "close_popup"]
    assert len(closes) == 1, g["on_match"]
    assert (closes[0]["x"], closes[0]["y"]) == (1820, 135), closes
    assert closes[0]["verify"] == "home/partyrun_marker.png", (
        "close must be verified against the screen's own marker")
    assert closes[0].get("retries", 0) >= 1, "one blind attempt is what failed before"
    assert not [a for a in g["on_match"] if a.get("type") == "tap_xy"], (
        "a bare tap here is the shape that stayed silent for 38 passes")

    def goto(block):
        if isinstance(block, dict):
            return block.get("goto")
        return next((a["state"] for a in block if a.get("type") == "goto"), None)

    assert goto(g["on_match"]) == "home", "a verified close lands back home"

    # Falls through the chain and ends at guard_not_inactive — the state that
    # concludes "genuinely mid-run" and jumps. Walking to it rather than asserting
    # the immediate next hop leaves room for guards added between the two later
    # (guard_not_friendinfo went in on 2026-08-14) while still catching the thing
    # that matters: a guard that dead-ends, self-loops, or skips the fall-through.
    hop, walked = "guard_not_partyrun", []
    for _ in range(len(base_states)):
        nxt = goto(base_states[hop]["on_absent"])
        assert nxt, f"{hop} has no absent fall-through"
        assert nxt not in walked, f"absent chain loops: {walked} -> {nxt}"
        walked.append(nxt)
        if not nxt.startswith("guard_not_"):
            break
        hop = nxt
    assert "guard_not_inactive" in walked, (
        f"must fall through to guard_not_inactive, walked {walked}")

    reachable = [k for k, v in base_states.items()
                 if k != "guard_not_partyrun" and "guard_not_partyrun" in str(v)]
    assert reachable, "nothing routes into guard_not_partyrun"


def test_probe_friendinfo_never_taps_blind(base_states):
    """No BLIND tap in this state, ever.

    It used to fire (1552,117) then (1633,107) before re-checking. On a pass where
    the dialog was already gone the second tap hit home, where (1633,107) is inside
    the Party Run banner strip, opening the undetectable screen guarded above. Every
    tap here must therefore be either verified (close_popup re-reads the frame) or
    template-matched inside a ROI — never an unconditional tap_xy.

    This once asserted exactly ONE close_popup, on the theory that close_popup's own
    retries would clear a stacked second layer. Live logs from 2026-08-08 killed that
    theory: all retries tap the SAME coordinate, which the inner card covers (BGR
    85,85,85, a shadow), so 34 consecutive passes closed nothing. The sequence is now
    close → ROI-scoped inner tap → close, i.e. two closes by design.
    """
    on_match = base_states["probe_friendinfo"]["on_match"]
    assert not [a for a in on_match if a.get("type") == "tap_xy"], on_match

    closes = [a for a in on_match if a.get("type") == "close_popup"]
    assert closes, on_match
    for c in closes:
        assert (c["x"], c["y"]) == (1633, 107), closes
        assert c["verify"] == "friends/friendinfo_marker.png", closes

    # The inner-layer tap is what the outer coordinate cannot reach. It must stay
    # ROI-scoped (an unscoped match would fire on home) and optional (a single-layer
    # pass has no inner X, and that is not an error).
    inner = [a for a in on_match if a.get("type") == "tap_template"]
    assert len(inner) == 1, on_match
    assert inner[0].get("optional") is True, inner

    # Measured inner-X template centres: (1423,88) Friend's Treasure over Info — the
    # variant in 11 of 12 archived frames — and (1570,127) Friend's Cookie over Info.
    # The pre-2026-08-14 ROI [1520,90,120,80] covered only the second and scored 0.453
    # on the first, below threshold, so the fallback never fired on the common case.
    #
    # perceive.find crops the frame to exactly (x,y,w,h), so the whole template must
    # fit inside the box — a centre-inside-ROI check passes boxes that cannot actually
    # match, which is how [1350,50,240,80] shipped scoring 0.169 on the Cookie layout.
    x, y, w, h = inner[0]["roi"]
    tw = th = 55  # friendcookie_innerclose.png
    for cx, cy in ((1423, 88), (1570, 127)):
        assert x <= cx - tw // 2 and cx + tw // 2 <= x + w, (
            f"ROI {inner[0]['roi']} cannot fit the template around x={cx}")
        assert y <= cy - th // 2 and cy + th // 2 <= y + h, (
            f"ROI {inner[0]['roi']} cannot fit the template around y={cy}")


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


def test_sdk_connect_failure_is_guarded_on_both_sides(base_states):
    """The dialog that cost a whole day.

    On 2026-08-14 the bot banked ZERO games between 08:00 and 17:00 while calling
    restart_app 6-9x/hr: "Failed to connect to server. SDK Code:0" sat on the title
    screen, no marker matched it, the blind watchdog escalated to a restart, the client
    came back and failed the handshake again. 166 of the 313 frames archived that day
    are this dialog.

    probe_connectionlost does NOT cover it — that marker is the "Connection lost!" text
    and scores 0.648 here, below threshold. Same-looking dialog, different words.

    Both sides are required, and the mid-run one is the side that actually failed: the
    archived frames came from relay_stage2_jump_3 / jump_2 / running, where probe_*
    states are unreachable. This is the fourth screen to need that pair.
    """
    for name in ("probe_sdkfail", "guard_not_sdkfail"):
        s = base_states.get(name)
        assert s, f"{name} missing"
        assert s["detect"] == "home/sdkfail_marker.png", s["detect"]

        # Confirm drops to the title screen rather than dismissing, so the only correct
        # continuation is a restart plus a re-auth — returning to `running` or `home`
        # would resume a session that no longer exists.
        types = [a.get("type") for a in s["on_match"]]
        assert "restart_app" in types, s["on_match"]
        target = next(a["state"] for a in s["on_match"] if a.get("type") == "goto")
        assert target == "recover_login", target

        tap = next(a for a in s["on_match"] if a.get("type") == "tap_xy")
        # Green Confirm button, HSV blob bbox (744,614,431,147) on the live frame.
        assert 744 <= tap["x"] <= 744 + 431, tap
        assert 614 <= tap["y"] <= 614 + 147, tap

    def goto(block):
        if isinstance(block, dict):
            return block.get("goto")
        return next((a["state"] for a in block if a.get("type") == "goto"), None)

    # probe side must be the HEAD of the chain: nothing else in it can work offline.
    assert goto(base_states["home"]["on_absent"]) == "probe_sdkfail"
    assert goto(base_states["probe_sdkfail"]["on_absent"]) == "probe_connectionlost"

    # guard side must sit in the mid-run chain and still fall through to inactive.
    hop, walked = "guard_not_home", []
    for _ in range(len(base_states)):
        nxt = goto(base_states[hop]["on_absent"])
        if not nxt or not nxt.startswith("guard_not_"):
            break
        assert nxt not in walked, f"absent chain loops: {walked} -> {nxt}"
        walked.append(nxt)
        hop = nxt
    assert "guard_not_sdkfail" in walked, walked
    assert walked.index("guard_not_sdkfail") < walked.index("guard_not_inactive"), walked


def test_wall_clock_clears_a_long_but_healthy_game(base_states):
    """`no_progress_s` has to sit above the SLOWEST healthy game, not the average.

    Measured 2026-08-15 over 1,610 real inter-progress gaps in this repo's logs
    (arrivals at run_result / mystery_box / home / check_heart): median 64s, p90 302s,
    p99 439s. The old 300 sat exactly at the p90, so **10.8% of healthy gaps tripped
    it** — one false recovery every nine games. Seen live at 02:33:23: the wall clock
    fired on a run that was merely long, the Result popup rendered two seconds later,
    and the recovery walked the probe chain to run_result in three seconds.

    600 clears the p99 with 1.4x headroom. This asserts the config, not the engine
    default, because the gap distribution belongs to the farm loop these configs run.
    """
    cfg = cfgmod.load(CONFIG)
    p99_healthy_gap_s = 439
    assert cfg.no_progress_s > p99_healthy_gap_s, (
        f"{cfg.no_progress_s}s would fire during the slowest healthy games")
    # Still has to be a watchdog, not a no-op: the blind detector's reach at the
    # measured 0.48 polls/s is ~1250s, and the wall clock should speak before that.
    assert cfg.no_progress_s < 1250, (
        "slower than the blind detector makes the wall clock pointless")


def test_relay_stage1_does_not_wait_for_a_marker_that_never_matches(base_states):
    """Stage 1 must cost one poll, not five seconds.

    The two-stage relay chain assumes a Continue/Quit dialog. This game build's mid-run
    relay prompt has no such pair — it shows the text plus the partner cookie's card, and
    tapping the CARD is what fires the relay, which is stage 2's job. Evidence: across
    1,414 archived frames and every log in the repo, relay_prompt_marker has **zero**
    matches, best 0.673 — and that best frame is the Mailbox "Send a free Life" dialog.
    The commit that added the chain recorded the same thing ("its green Continue pill
    never passed 0.40").

    With absent_retries=2 + absent_wait_ms=400 each of those five states burned ~5s per
    visit on a guaranteed miss. The relay-check lap measured ~13s while the prompt window
    is only 2-3s, so the retries were spending the very budget the relay needed.

    Stage 2 is the opposite case and must KEEP its retries: it matches, it fires the
    relay, and a marginal frame is worth a second look.
    """
    stage1 = {k: v for k, v in base_states.items()
              if "relay" in k and ("stage1" in k or "poll1" in k)}
    stage2 = {k: v for k, v in base_states.items()
              if "relay" in k and ("stage2" in k or "poll2" in k)}
    assert stage1 and stage2, sorted(base_states)

    for name, s in stage1.items():
        assert "absent_retries" not in s, f"{name} waits for a marker that never matches"
        assert "absent_wait_ms" not in s, name
        # The state itself stays — a future build could restore the two-button dialog.
        assert s["detect"] == "boxrun/relay_prompt_marker.png", name

    for name, s in stage2.items():
        assert s.get("absent_retries") == 2, f"{name} lost the retry that catches relays"
        assert s.get("threshold") == 0.62, (
            f"{name}: 0.82 sits inside the prompt-present cluster and caught 2 of 11")


def test_mystery_box_is_reachable_from_both_chains(base_states):
    """The reward screen that stalled a run for ten minutes.

    On 2026-08-15 21:38 the screen sat on Mystery Box "Open all" while the log walked
    the guard chain and the jump chain normally — the bot believed it was mid-run and
    was tapping jump/slide into a reward screen. tools/screen_watch.py reported it at
    214s; the wall clock only fired at 601s.

    The state table already had `mystery_box` and `mb_open`, and mb_open taps exactly
    the right buttons. The bug was reachability: `mystery_box` hangs off `run_result`
    and `mb_open` only, so once the loop was in the run chain there was no path back,
    and recover_unknown's twelve-probe walk returned to `running` without touching it.

    Fifth screen to need both halves (news, partyrun, friendinfo, sdkfail, mysterybox).
    Both entry points hand to the SAME mb_open so there is one dismiss implementation.
    """
    for name in ("probe_mysterybox", "guard_not_mysterybox"):
        s = base_states.get(name)
        assert s, f"{name} missing"
        assert s["detect"] == "boxrun/mysterybox_marker.png", s["detect"]
        target = next(a["state"] for a in s["on_match"] if a.get("type") == "goto")
        assert target == "mb_open", f"{name} must reuse mb_open, not reimplement it"

    def goto(block):
        if isinstance(block, dict):
            return block.get("goto")
        return next((a["state"] for a in block if a.get("type") == "goto"), None)

    # probe side: reachable by walking absent edges from the probe chain head.
    hop, walked = "probe_sdkfail", []
    for _ in range(len(base_states)):
        nxt = goto(base_states[hop].get("on_absent") or {})
        if not nxt or nxt in walked or nxt not in base_states:
            break
        walked.append(nxt)
        hop = nxt
    assert "probe_mysterybox" in walked, walked

    # guard side: in the mid-run chain, ahead of the state that concludes "mid-run".
    hop, walked = "guard_not_home", []
    for _ in range(len(base_states)):
        nxt = goto(base_states[hop]["on_absent"])
        if not nxt or not nxt.startswith("guard_not_"):
            break
        assert nxt not in walked, f"absent chain loops: {walked} -> {nxt}"
        walked.append(nxt)
        hop = nxt
    assert "guard_not_mysterybox" in walked, walked
    assert walked.index("guard_not_mysterybox") < walked.index("guard_not_inactive"), walked
