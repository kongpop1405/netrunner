"""Phase 5 — periodic routines (the send-lives errand)."""
import json

import numpy as np
import pytest

import src.fsm as fsm
from src import config as cfgmod
from src.config import Config, unreachable_states
from src.perceive import Match
from src.session import SessionError


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start, **kw):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states, **kw)


def _patch_loop(monkeypatch, found: set[str], *, clock_step: float = 0.0):
    """Stub the loop's IO. `clock_step` advances a fake monotonic clock by that
    many seconds per CYCLE (driven off grab, which runs once per cycle) — a
    per-read clock would make elapsed time depend on how many times the loop
    happens to call monotonic(), which no assertion can rely on."""
    monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
        found=name in found, score=1.0 if name in found else 0.1, x=5, y=5, w=2, h=2))
    monkeypatch.setattr(fsm.time, "sleep", lambda s: None)
    monkeypatch.setattr(fsm, "send_alert", lambda *a, **k: None)

    now = {"t": 0.0}

    def fake_grab(device, retries=2):
        now["t"] += clock_step
        return np.zeros((10, 10, 3), dtype=np.uint8)

    monkeypatch.setattr(fsm, "grab", fake_grab)
    if clock_step:
        monkeypatch.setattr(fsm.time, "monotonic", lambda: now["t"])


def _states():
    """home <-> running lap, plus a one-state errand that returns to home."""
    return {
        "home": {"detect": "home.png", "on_match": [
            {"type": "tap_xy", "x": 1, "y": 1}, {"type": "goto", "state": "running"}]},
        "running": {"detect": "running.png", "on_match": [
            {"type": "tap_xy", "x": 2, "y": 2}, {"type": "goto", "state": "home"}]},
        "errand": {"detect": "errand.png", "on_match": [
            {"type": "tap_xy", "x": 3, "y": 3}, {"type": "goto", "state": "home"}]},
    }


def _routine(**kw):
    r = {"name": "send_lives", "interval_s": (5.0, 6.0), "goto": "errand",
         "at_state": "home", "after_reset": False}
    r.update(kw)
    return (r,)


def _visited(monkeypatch, cfg, cycles, **runner_kw):
    seen = []
    real = fsm.Runner._run_actions

    def spy(self, actions, frame, state):
        seen.append(state)
        return real(self, actions, frame, state)

    monkeypatch.setattr(fsm.Runner, "_run_actions", spy)
    fsm.Runner(cfg, FakeDevice(), **runner_kw).run(dry_run=True, max_cycles=cycles)
    return seen


class TestRoutineTimer:
    def test_fires_when_due(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png", "errand.png"}, clock_step=1.0)
        cfg = _cfg(_states(), "home", periodic_routines=_routine())
        assert "errand" in _visited(monkeypatch, cfg, 20)

    def test_not_before_due(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png", "errand.png"}, clock_step=1.0)
        cfg = _cfg(_states(), "home",
                   periodic_routines=_routine(interval_s=(3600.0, 7200.0)))
        assert "errand" not in _visited(monkeypatch, cfg, 20)

    def test_waits_for_at_state(self, monkeypatch):
        """Due mid-run must not interrupt the run — the errand only starts from
        the safe state."""
        _patch_loop(monkeypatch, {"running.png", "errand.png"}, clock_step=1.0)
        states = _states()
        states["running"]["on_match"] = [{"type": "tap_xy", "x": 2, "y": 2},
                                         {"type": "goto", "state": "running"}]
        cfg = _cfg(states, "running", periodic_routines=_routine(at_state="home"))
        assert "errand" not in _visited(monkeypatch, cfg, 15)

    def test_reschedules_after_firing(self, monkeypatch):
        """One due window must produce one detour, not a detour every lap."""
        _patch_loop(monkeypatch, {"home.png", "running.png", "errand.png"}, clock_step=1.0)
        # 1s per cycle: the first fire lands around cycle 8-9 and the reschedule
        # puts the next one past cycle 16, beyond this run
        cfg = _cfg(_states(), "home", periodic_routines=_routine(interval_s=(8.0, 9.0)))
        seen = _visited(monkeypatch, cfg, 14)
        assert seen.count("errand") == 1

    def test_no_routines_configured(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        cfg = _cfg(_states(), "home")
        assert "errand" not in _visited(monkeypatch, cfg, 12)

    def test_at_state_defaults_to_inter_game_state(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png", "errand.png"}, clock_step=1.0)
        cfg = _cfg(_states(), "running", periodic_routines=_routine(at_state=None),
                   inter_game_delay_s=(0.1, 0.2), inter_game_state="home")
        assert "errand" in _visited(monkeypatch, cfg, 20)

    def test_after_reset_brings_routine_forward(self, monkeypatch):
        """cookierun-bot sends lives right after every app restart; a routine
        marked after_reset must not wait out a fresh interval."""
        _patch_loop(monkeypatch, {"home.png", "running.png", "errand.png"}, clock_step=1.0)

        class Spy:
            """Restarts once, then pushes the next budget out of reach so the
            routine gets a lap to itself."""

            def __init__(self, cfg):
                self.cfg = cfg
                self.n = 0

            def restart(self):
                self.n += 1
                self.cfg.session_reset_s = (1e6, 2e6)

        cfg = _cfg(_states(), "home",
                   # one reset early on, then far out of reach, so the lap after
                   # it is free for the brought-forward routine to fire
                   session_reset_s=(3.0, 4.0),
                   periodic_routines=_routine(interval_s=(3600.0, 7200.0),
                                              after_reset=True))
        seen = []
        real = fsm.Runner._run_actions

        def spy(self, actions, frame, state):
            seen.append(state)
            return real(self, actions, frame, state)

        monkeypatch.setattr(fsm.Runner, "_run_actions", spy)
        # not dry_run: resets are disabled in dry runs
        fsm.Runner(cfg, FakeDevice(), restarter=Spy(cfg)).run(max_cycles=20)
        assert "errand" in seen  # despite the 1h interval

    def test_routine_entry_counts_as_reachable(self):
        """A routine's chain is only reachable via the timer — the orphan check
        must know that or it drowns the real orphans."""
        states = _states()
        states["errand"]["on_match"] = [{"type": "goto", "state": "errand_2"}]
        states["errand_2"] = {"detect": "e2.png", "on_match": [
            {"type": "goto", "state": "home"}]}
        assert unreachable_states(states, "home") == ["errand", "errand_2"]
        assert unreachable_states(states, "home", extra_roots=["errand"]) == []


class TestRoutineConfig:
    def _write(self, tmp_path, tdir, routines):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {"a": {"detect": "marker.png", "on_match": [{"type": "stop"}]},
                       "b": {"detect": "marker.png", "on_match": [{"type": "stop"}]}},
            "periodic_routines": routines,
        }
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_parsed(self, tmp_path, tdir):
        cfg = cfgmod.load(self._write(tmp_path, tdir, [
            {"name": "lives", "interval_s": [1500, 2100], "goto": "b",
             "at_state": "a", "after_reset": True}]))
        r = cfg.periodic_routines[0]
        assert (r["name"], r["interval_s"], r["goto"], r["after_reset"]) == \
               ("lives", (1500, 2100), "b", True)

    def test_goto_must_exist(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="undefined state"):
            cfgmod.load(self._write(tmp_path, tdir, [
                {"name": "x", "interval_s": [1, 2], "goto": "ghost"}]))

    def test_at_state_must_exist(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="at_state"):
            cfgmod.load(self._write(tmp_path, tdir, [
                {"name": "x", "interval_s": [1, 2], "goto": "b", "at_state": "ghost"}]))

    def test_goto_required(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="needs a 'goto'"):
            cfgmod.load(self._write(tmp_path, tdir, [
                {"name": "x", "interval_s": [1, 2]}]))

    def test_bad_interval_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="interval_s"):
            cfgmod.load(self._write(tmp_path, tdir, [
                {"name": "x", "interval_s": [2100, 1500], "goto": "b"}]))

    def test_not_a_list_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="must be a list"):
            cfgmod.load(self._write(tmp_path, tdir, {"name": "x"}))


class TestShippedLivesConfig:
    """The real boxrun_toggle graft — the chain must be whole and reachable."""

    def test_lives_chain_reachable_and_returns_home(self):
        cfg = cfgmod.load("config/cookierun/boxrun_toggle.json")
        lives = [n for n in cfg.states if n.startswith("lives_")]
        assert len(lives) >= 13
        roots = [r["goto"] for r in cfg.periodic_routines]
        orphans = unreachable_states(cfg.states, cfg.start_state, extra_roots=roots)
        assert not [o for o in orphans if o.startswith("lives_")]
        # no leftover `stop`: ending the friends list means resuming the farm
        for name in lives:
            actions = cfg.states[name].get("on_match", [])
            pool = list(actions.values()) if isinstance(actions, dict) else [actions]
            oa = cfg.states[name].get("on_absent")
            if isinstance(oa, list):
                pool.append(oa)
            for lst in pool:
                assert not any(a.get("type") == "stop" for a in lst), name

    def test_routine_points_at_the_chain(self):
        cfg = cfgmod.load("config/cookierun/boxrun_toggle.json")
        r = cfg.periodic_routines[0]
        assert r["goto"] == "lives_scan"
        assert r["at_state"] == "home"
        assert r["after_reset"] is True
        assert r["interval_s"] == (1500, 2100)
