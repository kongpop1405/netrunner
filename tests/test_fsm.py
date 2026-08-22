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


def test_run_config_action_drives_a_sub_runner_then_resumes(monkeypatch, grabs):
    """run_config: loads the target config, runs it to completion on a fresh
    Runner (same device), then the parent's own loop continues."""
    _patch_find(monkeypatch, {"a.png", "b.png"})
    sub_cfg = _cfg({"x": {"detect": "x.png", "on_match": [{"type": "stop"}]}}, "x")
    monkeypatch.setattr(fsm, "load_config", lambda path: sub_cfg)

    sub_runs = []
    real_run = fsm.Runner.run

    def spy_run(self, **kwargs):
        if self.cfg is sub_cfg:
            sub_runs.append(kwargs)
            return  # pretend the errand's own `stop` ended it immediately
        return real_run(self, **kwargs)

    monkeypatch.setattr(fsm.Runner, "run", spy_run)

    states = {
        "a": {"detect": "a.png",
              "on_match": [{"type": "run_config", "config": "errand.json"},
                           {"type": "goto", "state": "b"}]},
        "b": {"detect": "b.png", "on_match": [{"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)
    assert len(sub_runs) == 1


def test_entered_at_resets_for_the_state_a_goto_lands_on(monkeypatch, grabs, caplog):
    """A goto after a slow blocking action (restart_app, run_config) must stamp
    entered_at for the NEW state, not leave the old state's stamp behind.

    Live 2026-08-17: probe_connectionlost's on_match ran tap -> wait -> restart_app
    (relaunch + 3 stability checks, ~93s wall clock) -> goto recover_login.
    entered_at was set once at the top of the match branch, before those blocking
    actions ran, and never re-stamped for recover_login on arrival. The very next
    poll computed recover_login's own timeout_ms (30,000ms) against that 93-second-
    old stamp and fired immediately: "state 'recover_login' stuck 93406ms >= timeout
    30000ms" the instant it arrived, observed identically three separate times
    (93375ms, 93406ms, 93531ms — the same restart_app duration each time, not
    noise). The fallback target happened to also work, which is why this went
    unnoticed for a day: the log line was lying about what actually happened.

    Reproduced here with run_config as the slow action: advance the fake clock by
    93s inside the mocked sub-run, then land on a state with its own short
    timeout_ms. If entered_at still carried the pre-action stamp, that state's
    very first poll would already be "stuck" and log the same false warning.
    """
    _patch_find(monkeypatch, {"a.png"})  # "landed" never matches -> stays on on_absent
    sub_cfg = _cfg({"x": {"detect": "x.png", "on_match": [{"type": "stop"}]}}, "x")
    monkeypatch.setattr(fsm, "load_config", lambda path: sub_cfg)

    clock = {"t": 1_000_000.0}
    monkeypatch.setattr(fsm.time, "monotonic", lambda: clock["t"])

    real_run = fsm.Runner.run

    def slow_sub_run(self, **kwargs):
        if self.cfg is sub_cfg:
            clock["t"] += 93.4  # the measured restart_app+stability duration
            return
        return real_run(self, **kwargs)

    monkeypatch.setattr(fsm.Runner, "run", slow_sub_run)

    states = {
        "a": {"detect": "a.png",
              "on_match": [{"type": "run_config", "config": "errand.json"},
                           {"type": "goto", "state": "landed"}]},
        "landed": {"detect": "landed.png",
                   "on_absent": {"goto": "escaped"}, "timeout_ms": 30_000},
        "escaped": {"detect": "escaped.png", "on_match": [{"type": "stop"}]},
    }
    with caplog.at_level("WARNING"):
        fsm.Runner(_cfg(states, "a"), FakeDevice()).run(max_cycles=10)

    stuck_warnings = [r.message for r in caplog.records if "stuck" in r.message]
    assert not stuck_warnings, (
        f"'landed' should read as freshly-entered, not already stuck: {stuck_warnings}"
    )


def test_run_config_is_a_noop_in_dry_run(monkeypatch, grabs):
    """dry_run must never trigger a real sub-run — same guard as tap/swipe/etc."""
    _patch_find(monkeypatch, {"a.png"})
    load_calls = []
    monkeypatch.setattr(fsm, "load_config", lambda path: load_calls.append(path))

    states = {
        "a": {"detect": "a.png",
              "on_match": [{"type": "run_config", "config": "errand.json"},
                           {"type": "stop"}]},
    }
    fsm.Runner(_cfg(states, "a"), FakeDevice()).run(dry_run=True, max_cycles=5)
    assert load_calls == []


class TestErrandPerEpisode:
    """Send-Life's friend list is per-Episode: one pass only ever reaches the
    friends of whichever Episode home had selected, so `episodes` on run_config
    clears each in turn. The farm loop that called it never picks an Episode
    itself — it taps Play! and farms whatever is selected — so the Episode in
    effect when control returns decides what gets farmed for the rest of the
    session. That makes restoring it part of the feature, not a nicety.
    """

    def _runner(self, monkeypatch, *, detected, switch_fails=()):
        """Runner with switch_episode/detect stubbed, recording the call order."""
        events = []
        sub_cfg = _cfg({"x": {"detect": "x.png", "on_match": [{"type": "stop"}]}}, "x")
        monkeypatch.setattr(fsm, "load_config", lambda path: sub_cfg)
        monkeypatch.setattr(fsm, "detect_current_episode",
                            lambda device, store: detected)
        monkeypatch.setattr(fsm.time, "sleep", lambda s: None)

        import tools.switch_episode as se

        def fake_switch(device, store, episode, **kw):
            if episode in switch_fails:
                raise se.SwitchEpisodeError(f"map did not open for {episode}")
            events.append(("switch", episode))

        monkeypatch.setattr(se, "switch_episode", fake_switch)

        real_run = fsm.Runner.run

        def spy_run(self, **kwargs):
            if self.cfg is sub_cfg:
                events.append(("run", None))
                return
            return real_run(self, **kwargs)

        monkeypatch.setattr(fsm.Runner, "run", spy_run)

        parent = _cfg({"a": {"detect": "a.png"}}, "a")
        runner = fsm.Runner(parent, FakeDevice())
        # run() normally sets this; these tests drive _run_errand directly.
        runner._errand_dry_run = False
        return runner, events

    def test_clears_each_episode_then_restores_the_original(self, monkeypatch):
        runner, events = self._runner(monkeypatch, detected=3)
        runner._run_errand("errand.json", [1, 2])
        assert events == [
            ("switch", 1), ("run", None),
            ("switch", 2), ("run", None),
            ("switch", 3),          # back to where the farm loop left off
        ], events

    def test_refuses_to_switch_when_the_episode_cannot_be_read(self, monkeypatch, caplog):
        """Switching with no way back would silently change what the farm loop
        farms — skipping the errand is the lesser harm."""
        runner, events = self._runner(monkeypatch, detected=None)
        with caplog.at_level("WARNING"):
            runner._run_errand("errand.json", [1, 2])
        assert events == [], events
        assert any("cannot read the current Episode" in r.message for r in caplog.records)

    def test_one_failed_switch_does_not_abandon_the_rest(self, monkeypatch, caplog):
        runner, events = self._runner(monkeypatch, detected=5, switch_fails={2})
        with caplog.at_level("WARNING"):
            runner._run_errand("errand.json", [1, 2, 3])
        # episode 2 never runs, 1 and 3 still do, 5 is still restored
        assert events == [
            ("switch", 1), ("run", None),
            ("switch", 3), ("run", None),
            ("switch", 5),
        ], events

    def test_alerts_when_the_original_episode_cannot_be_restored(self, monkeypatch):
        alerts = []
        monkeypatch.setattr(fsm, "send_alert", lambda *a, **k: alerts.append(a))
        runner, events = self._runner(monkeypatch, detected=6, switch_fails={6})
        runner._run_errand("errand.json", [1])
        assert ("run", None) in events
        assert alerts, "a farm loop left on the wrong Episode must not be silent"
        assert any("episode" in str(a).lower() for a in alerts), alerts

    def test_without_episodes_the_errand_runs_once_and_never_switches(self, monkeypatch):
        """The original behaviour has to stay the default: the mailbox sweep and
        every other errand must not start navigating the Episode picker."""
        runner, events = self._runner(monkeypatch, detected=4)
        runner._run_errand("errand.json")
        assert events == [("run", None)], events


class TestMaxVisits:
    """A cap in ITEMS, which neither watchdog can express: both ask whether the
    bot has stopped progressing, and the mailbox sweep confirming one friend's
    Life per pass is progressing on every single pass — it would drain a
    200-friend list before the Send-Life run ever started.
    """

    def _states(self, cap, target="escaped"):
        return {
            "loop": {"detect": "a.png", "max_visits": cap, "max_visits_goto": target,
                     "on_match": [{"type": "tap_xy", "x": 1, "y": 1},
                                  {"type": "goto", "state": "loop"}]},
            "escaped": {"detect": "esc.png", "on_match": [{"type": "stop"}]},
        }

    def test_the_cap_fires_after_exactly_that_many_passes(self, monkeypatch, grabs, caplog):
        """Count the loop's own passes, not the number echoed in the log line:
        asserting on "max_visits 3" only re-reads the configured value back, so a
        >-vs->= slip and a count-every-poll slip both survive it (both mutants
        did). The confirms are the thing that must be capped.
        """
        _patch_find(monkeypatch, {"a.png", "esc.png"})
        with caplog.at_level("INFO"):
            fsm.Runner(_cfg(self._states(3), "loop"),
                       FakeDevice()).run(dry_run=True, max_cycles=40)
        msgs = [r.message for r in caplog.records]
        passes = sum("transition loop -> loop" in m for m in msgs)
        assert passes == 3, f"expected 3 confirms before the cap, got {passes}"
        fired = [m for m in msgs if "max_visits" in m]
        assert fired and "goto 'escaped'" in fired[0], fired

    def test_a_pass_only_counts_when_the_state_is_re_entered(self, monkeypatch, grabs, caplog):
        """The counter has to tick on transitions, not on polls: a state that
        polls several times per item (waiting for the dialog to re-open) would
        otherwise hit the cap having confirmed far fewer than `cap` friends."""
        # absent for two polls, so the state is re-polled without transitioning
        _patch_find(monkeypatch, {"esc.png"})
        states = self._states(2)
        states["loop"]["absent_retries"] = 2
        states["loop"]["absent_wait_ms"] = 1
        states["loop"]["on_absent"] = {"goto": "escaped"}
        with caplog.at_level("INFO"):
            fsm.Runner(_cfg(states, "loop"),
                       FakeDevice()).run(dry_run=True, max_cycles=20)
        assert not [r for r in caplog.records if "max_visits" in r.message], \
            "polls without a transition must not count toward the cap"

    def test_a_short_list_still_ends_on_its_own(self, monkeypatch, grabs, caplog):
        """Under the cap nothing changes: the dialog stops reappearing and
        on_absent takes it to `done` exactly as before."""
        _patch_find(monkeypatch, {"esc.png"})  # dialog never present
        with caplog.at_level("INFO"):
            fsm.Runner(_cfg(self._states(30), "loop"),
                       FakeDevice()).run(dry_run=True, max_cycles=20)
        assert not [r for r in caplog.records if "max_visits" in r.message], \
            "the cap fired on a list that was already empty"

    def test_uncapped_states_are_untouched(self, monkeypatch, grabs, caplog):
        _patch_find(monkeypatch, {"a.png", "esc.png"})
        states = self._states(3)
        del states["loop"]["max_visits"], states["loop"]["max_visits_goto"]
        with caplog.at_level("INFO"):
            fsm.Runner(_cfg(states, "loop"),
                       FakeDevice()).run(dry_run=True, max_cycles=12)
        assert not [r for r in caplog.records if "max_visits" in r.message]


class TestLivesUnderGate:
    """The Mailbox sweep drains the whole list, so how long that list was cannot
    be recovered afterwards — the count has to come from the Lives-tab badge read
    before the drain (remember_lives_waiting). This gate spends it.

    Measured 2026-08-20: home envelope 55 vs Lives tab 53 vs Rewards 4 on one
    frame, i.e. the home badge counts other tabs too, which is why the count is
    read from inside the Mailbox and why an unread count must not be guessed at.
    """

    @staticmethod
    def _seed(monkeypatch, waiting):
        """Leave lives_waiting where remember_lives_waiting would have.

        Patching Actor itself with a factory breaks the engine — it reads
        Actor.UNSURE off the class — so hook __init__ instead.
        """
        orig_init = fsm.Actor.__init__

        def init(self, *a, **k):
            orig_init(self, *a, **k)
            self.lives_waiting = waiting

        monkeypatch.setattr(fsm.Actor, "__init__", init)

    def _states(self):
        return {
            "gate": {
                "lives_under": {"count": 30},
                "on_match": [{"type": "goto", "state": "few"}],
                "on_absent": [{"type": "goto", "state": "many"}],
            },
            # Each branch taps a distinct y so the taps say which one ran: a
            # `stop` returns before the engine counts the state, so the visits
            # dict cannot tell them apart.
            "few": {"detect": "few.png",
                    "on_match": [{"type": "tap_xy", "x": 1, "y": 111},
                                 {"type": "stop"}]},
            "many": {"detect": "many.png",
                     "on_match": [{"type": "tap_xy", "x": 1, "y": 222},
                                  {"type": "stop"}]},
        }

    def _run(self, monkeypatch, waiting):
        _patch_find(monkeypatch, {"few.png", "many.png"})
        self._seed(monkeypatch, waiting)
        taps = []
        dev = FakeDevice()
        dev.shell = lambda *a: (taps.append(a), "")[1]
        fsm.Runner(_cfg(self._states(), "gate"), dev).run(max_cycles=6)
        # Taps carry the Actor's humanization jitter (Gaussian, clipped at 8px),
        # so match by distance, not by string: an exact compare reads every tap
        # as neither branch.
        ys = [int(a[-1]) for a in taps if len(a) >= 4 and a[0] == "input"]
        hit = ("few" if any(abs(y - 111) <= 12 for y in ys)
               else "many" if any(abs(y - 222) <= 12 for y in ys)
               else "none")
        return {hit: 1}

    def test_a_short_list_takes_the_send_life_branch(self, monkeypatch, grabs):
        visits = self._run(monkeypatch, 12)
        assert "few" in visits and "many" not in visits, visits

    def test_a_long_list_goes_straight_back(self, monkeypatch, grabs):
        visits = self._run(monkeypatch, 53)
        assert "many" in visits and "few" not in visits, visits

    def test_the_boundary_counts_as_long(self, monkeypatch, grabs):
        """"fewer than 30" is strict: exactly 30 is the long branch."""
        visits = self._run(monkeypatch, 30)
        assert "many" in visits and "few" not in visits, visits

    def test_an_unread_count_takes_the_cheap_branch(self, monkeypatch, grabs):
        """None is "cannot decide". The other branch costs a Send-Life pass over
        7 Episodes, so it must never run off a failed read."""
        visits = self._run(monkeypatch, None)
        assert "many" in visits and "few" not in visits, visits

    def test_the_gate_spends_the_count(self, monkeypatch, grabs):
        """A second gate pass must not re-decide from a sweep already acted on:
        the count belongs to a list that has since been drained."""
        _patch_find(monkeypatch, {"back.png", "done.png"})
        self._seed(monkeypatch, 12)
        states = {
            "gate": {
                "lives_under": {"count": 30},
                "on_match": [{"type": "goto", "state": "back"}],
                "on_absent": [{"type": "goto", "state": "done"}],
            },
            "back": {"detect": "back.png", "on_match": [{"type": "goto", "state": "gate"}]},
            "done": {"detect": "done.png", "on_match": [{"type": "stop"}]},
        }
        states["done"]["on_match"] = [{"type": "tap_xy", "x": 1, "y": 222},
                                      {"type": "stop"}]
        taps = []
        dev = FakeDevice()
        dev.shell = lambda *a: (taps.append(a), "")[1]
        visits = fsm.Runner(_cfg(states, "gate"), dev).run(max_cycles=8)
        # Pass 1: 12 < 30 -> back -> gate. Pass 2: the count is spent, so the
        # gate falls to on_absent and reaches `done` instead of looping forever.
        assert visits.get("gate", 0) >= 2, visits
        ys = [int(a[-1]) for a in taps if len(a) >= 4 and a[0] == "input"]
        assert any(abs(y - 222) <= 12 for y in ys), (
            f"never reached `done` — the count was not consumed: {visits} {ys}")

    def test_a_gate_that_decides_nothing_is_refused(self, monkeypatch, grabs):
        """Same rule visits_under carries: a gate spends no capture, so an exit
        back to itself spins without ever looking at the screen."""
        self._seed(monkeypatch, 12)
        states = {
            "gate": {
                "lives_under": {"count": 30},
                "on_match": [{"type": "goto", "state": "gate"}],
                "on_absent": [{"type": "goto", "state": "gate"}],
            },
        }
        with pytest.raises(fsm.FsmError):
            fsm.Runner(_cfg(states, "gate"), FakeDevice()).run(max_cycles=5)

    def test_the_gate_spends_no_capture(self, monkeypatch, grabs):
        """It decides from a remembered number, not from the screen."""
        before = grabs["n"]
        self._run(monkeypatch, 12)
        # one grab for `few`'s own detect, none for the gate itself
        assert grabs["n"] - before == 1, grabs["n"] - before


class TestLivesCountCrossesTheErrandBoundary:
    """The count is read INSIDE the sweep (a run_config errand) and spent by a
    gate in the PARENT config, so it has to survive the boundary between them.

    _run_errand drives the errand with its own Runner, which builds its own
    Actor — so an action that only writes to `self.lives_waiting` writes to the
    child's copy and the parent's gate sees None forever, i.e. the "few waiting"
    branch could never run. Caught by reading _run_errand rather than live,
    because the branch it disables is the one that needs mail waiting to observe.
    """

    def test_a_count_read_inside_an_errand_reaches_the_parent(self, monkeypatch, grabs):
        _patch_find(monkeypatch, {"child.png", "few.png", "many.png"})

        child_states = {
            "child": {"detect": "child.png",
                      "on_match": [{"type": "remember_lives_waiting"},
                                   {"type": "stop"}]},
        }
        parent_states = {
            "sweep": {"detect": "child.png",
                      "on_match": [{"type": "run_config", "config": "child.json"},
                                   {"type": "goto", "state": "gate"}]},
            "gate": {"lives_under": {"count": 30},
                     "on_match": [{"type": "tap_xy", "x": 1, "y": 111},
                                  {"type": "stop"}],
                     "on_absent": [{"type": "tap_xy", "x": 1, "y": 222},
                                   {"type": "stop"}]},
        }
        monkeypatch.setattr(fsm, "load_config",
                            lambda path: _cfg(child_states, "child"))
        monkeypatch.setattr(fsm.time, "sleep", lambda s: None)
        # The child's own read succeeds; only the hand-back is under test.
        import src.mailbox as mbmod
        monkeypatch.setattr(mbmod, "read_lives_waiting", lambda *a, **k: 12)

        taps = []
        dev = FakeDevice()
        dev.shell = lambda *a: (taps.append(a), "")[1]
        fsm.Runner(_cfg(parent_states, "sweep"), dev).run(max_cycles=10)
        ys = [int(a[-1]) for a in taps if len(a) >= 4 and a[0] == "input"]
        assert any(abs(y - 111) <= 12 for y in ys), (
            f"the parent gate never saw the count the errand read: taps {ys} — "
            f"12 < 30 should have taken the Send-Life branch")

    def test_a_failed_read_inside_an_errand_does_not_erase_the_parents_count(
            self, monkeypatch, grabs):
        """Only a real count is handed back. The gate's own consume is what
        clears it, so an errand that could not read must not clear it on the
        gate's behalf — that would turn "read 12, then a later sweep saw an empty
        list" into "unread", i.e. the wrong branch on a count that WAS read."""
        _patch_find(monkeypatch, {"child.png", "gate.png"})
        child_states = {
            "child": {"detect": "child.png",
                      "on_match": [{"type": "remember_lives_waiting"},
                                   {"type": "stop"}]},
        }
        parent_states = {
            "sweep": {"detect": "child.png",
                      "on_match": [{"type": "run_config", "config": "child.json"},
                                   {"type": "goto", "state": "gate"}]},
            "gate": {"lives_under": {"count": 30},
                     "on_match": [{"type": "tap_xy", "x": 1, "y": 111},
                                  {"type": "stop"}],
                     "on_absent": [{"type": "tap_xy", "x": 1, "y": 222},
                                   {"type": "stop"}]},
        }
        monkeypatch.setattr(fsm, "load_config",
                            lambda path: _cfg(child_states, "child"))
        monkeypatch.setattr(fsm.time, "sleep", lambda s: None)
        import src.mailbox as mbmod
        monkeypatch.setattr(mbmod, "read_lives_waiting", lambda *a, **k: None)

        # The parent already holds a count (an earlier sweep read it).
        orig_init = fsm.Actor.__init__
        parents = []

        def init(self, *a, **k):
            orig_init(self, *a, **k)
            if not parents:            # the parent's Actor is built first
                self.lives_waiting = 12
                parents.append(self)

        monkeypatch.setattr(fsm.Actor, "__init__", init)

        taps = []
        dev = FakeDevice()
        dev.shell = lambda *a: (taps.append(a), "")[1]
        fsm.Runner(_cfg(parent_states, "sweep"), dev).run(max_cycles=10)
        ys = [int(a[-1]) for a in taps if len(a) >= 4 and a[0] == "input"]
        assert any(abs(y - 111) <= 12 for y in ys), (
            f"an unreadable errand wiped the count the parent already had: {ys}")
