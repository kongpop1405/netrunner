"""Phase 1 — inter-game delay, poll jitter, wait jitter."""
import json

import numpy as np
import pytest

import src.act as actmod
import src.fsm as fsm
from src import config as cfgmod
from src.config import Config
from src.perceive import Match


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start, **kw):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states, **kw)


def _patch_find(monkeypatch, found: set[str]):
    monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
        found=name in found, score=1.0 if name in found else 0.1, x=5, y=5, w=2, h=2))


def _patch_grab(monkeypatch):
    monkeypatch.setattr(fsm, "grab",
                        lambda device, retries=2: np.zeros((10, 10, 3), dtype=np.uint8))


@pytest.fixture
def sleeps(monkeypatch):
    """Capture every fsm-level sleep instead of really sleeping."""
    out = []
    monkeypatch.setattr(fsm.time, "sleep", out.append)
    return out


# --- inter-game delay ------------------------------------------------------------


class TestInterGameDelay:
    def _states(self):
        # home -> running -> home ... one lap = one "game"
        return {
            "home": {"detect": "home.png", "on_match": [
                {"type": "tap_xy", "x": 1, "y": 1}, {"type": "goto", "state": "running"}]},
            "running": {"detect": "running.png", "on_match": [
                {"type": "tap_xy", "x": 2, "y": 2}, {"type": "goto", "state": "home"}]},
        }

    def test_first_arrival_not_delayed(self, monkeypatch, sleeps):
        """Start state IS the inter-game state — the first visit is game 1
        starting, not game 0 ending, so it must not idle."""
        _patch_find(monkeypatch, {"home.png", "running.png"})
        _patch_grab(monkeypatch)
        cfg = _cfg(self._states(), "home", inter_game_delay_s=(30.0, 60.0))
        fsm.Runner(cfg, FakeDevice()).run(dry_run=True, max_cycles=1)
        assert not [s for s in sleeps if s >= 30]

    def test_delay_on_each_return(self, monkeypatch, sleeps):
        _patch_find(monkeypatch, {"home.png", "running.png"})
        _patch_grab(monkeypatch)
        cfg = _cfg(self._states(), "home", inter_game_delay_s=(30.0, 60.0))
        fsm.Runner(cfg, FakeDevice()).run(dry_run=True, max_cycles=7)
        long = [s for s in sleeps if s >= 30]
        assert len(long) >= 2
        assert all(30.0 <= s <= 60.0 for s in long)

    def test_delay_values_vary(self, monkeypatch, sleeps):
        """A fixed 45s every lap would be as much a signature as no delay."""
        _patch_find(monkeypatch, {"home.png", "running.png"})
        _patch_grab(monkeypatch)
        cfg = _cfg(self._states(), "home", inter_game_delay_s=(30.0, 60.0))
        fsm.Runner(cfg, FakeDevice()).run(dry_run=True, max_cycles=41)
        long = [s for s in sleeps if s >= 30]
        assert len(set(long)) > 1

    def test_no_delay_when_unset(self, monkeypatch, sleeps):
        """Configs that don't ask for it keep the old behaviour exactly."""
        _patch_find(monkeypatch, {"home.png", "running.png"})
        _patch_grab(monkeypatch)
        fsm.Runner(_cfg(self._states(), "home"), FakeDevice()).run(
            dry_run=True, max_cycles=10)
        assert not [s for s in sleeps if s >= 30]

    def test_custom_inter_game_state(self, monkeypatch, sleeps):
        """Delay attaches to inter_game_state, not to start_state."""
        _patch_find(monkeypatch, {"home.png", "running.png"})
        _patch_grab(monkeypatch)
        cfg = _cfg(self._states(), "home",
                   inter_game_delay_s=(30.0, 60.0), inter_game_state="running")
        fsm.Runner(cfg, FakeDevice()).run(dry_run=True, max_cycles=6)
        # 'running' is entered on cycle 2 -> that first arrival is skipped, the
        # next one delays. Either way the delay must exist and be in range.
        long = [s for s in sleeps if s >= 30]
        assert long and all(30.0 <= s <= 60.0 for s in long)

    def test_idle_not_billed_to_match_timeout(self, monkeypatch, sleeps):
        """A 45s idle must not consume a match_timeout budget on the state we
        idled in — otherwise every delayed lap would trip the escape."""
        _patch_find(monkeypatch, {"home.png"})
        _patch_grab(monkeypatch)
        states = {
            "home": {"detect": "home.png",
                     "on_match": [{"type": "tap_xy", "x": 1, "y": 1},
                                  {"type": "goto", "state": "other"}],
                     "on_absent": {"goto": "other"},
                     "match_timeout_ms": 5000},
            "other": {"detect": "other.png", "on_absent": {"goto": "home"},
                      "timeout_ms": 999999},
        }
        cfg = _cfg(states, "home", inter_game_delay_s=(30.0, 60.0))
        fsm.Runner(cfg, FakeDevice()).run(dry_run=True, max_cycles=8)  # no FsmError


# --- poll jitter -----------------------------------------------------------------


class TestPollJitter:
    def test_fixed_poll_unchanged(self):
        assert _cfg({}, "a").poll_delay_s() == 0.001

    def test_range_poll_varies_within_bounds(self):
        cfg = _cfg({}, "a", poll_ms_range=(500, 900))
        draws = {cfg.poll_delay_s() for _ in range(40)}
        assert len(draws) > 1
        assert all(0.5 <= d <= 0.9 for d in draws)

    def test_runner_uses_jittered_poll(self, monkeypatch, sleeps):
        _patch_find(monkeypatch, set())  # never match -> sleep every cycle
        _patch_grab(monkeypatch)
        cfg = _cfg({"a": {"detect": "a.png"}}, "a", poll_ms_range=(500, 900))
        fsm.Runner(cfg, FakeDevice()).run(max_cycles=12)
        polls = [s for s in sleeps if 0.5 <= s <= 0.9]
        assert len(polls) >= 8
        assert len(set(polls)) > 1


# --- wait jitter -----------------------------------------------------------------


class TestWaitJitter:
    @pytest.fixture
    def actor(self, monkeypatch):
        out = []
        monkeypatch.setattr(actmod.time, "sleep", out.append)
        a = actmod.Actor(FakeDevice(), store=None, dry_run=True)
        a.slept = out
        return a

    def test_fixed_ms_unchanged(self, actor):
        actor.run({"type": "wait", "ms": 900}, None)
        assert actor.slept == [0.9]

    def test_range_ms_varies_within_bounds(self, actor):
        for _ in range(40):
            actor.run({"type": "wait", "ms": [800, 1400]}, None)
        assert len(set(actor.slept)) > 1
        assert all(0.8 <= s <= 1.4 for s in actor.slept)


# --- config parsing --------------------------------------------------------------


class TestPacingConfig:
    def _write(self, tmp_path, tdir, **top):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {"a": {"detect": "marker.png", "on_match": [{"type": "stop"}]}},
        }
        data.update(top)
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return p

    def test_poll_ms_range_parsed(self, tmp_path, tdir):
        cfg = cfgmod.load(self._write(tmp_path, tdir, poll_ms=[500, 900]))
        assert cfg.poll_ms_range == (500, 900)
        assert cfg.poll_ms == 500  # int field stays meaningful

    def test_poll_ms_scalar_keeps_none_range(self, tmp_path, tdir):
        cfg = cfgmod.load(self._write(tmp_path, tdir, poll_ms=600))
        assert cfg.poll_ms_range is None
        assert cfg.poll_ms == 600

    def test_inter_game_delay_parsed(self, tmp_path, tdir):
        cfg = cfgmod.load(self._write(tmp_path, tdir, inter_game_delay_s=[30, 60]))
        assert cfg.inter_game_delay_s == (30, 60)

    @pytest.mark.parametrize("bad", [[60, 30], [0, 60], [30], 30.5, "x", [30, "a"], [True, 2]])
    def test_bad_ranges_rejected(self, tmp_path, tdir, bad):
        with pytest.raises(cfgmod.ConfigError, match="inter_game_delay_s"):
            cfgmod.load(self._write(tmp_path, tdir, inter_game_delay_s=bad))

    def test_inter_game_state_must_exist(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="inter_game_state"):
            cfgmod.load(self._write(tmp_path, tdir,
                                    inter_game_delay_s=[30, 60], inter_game_state="ghost"))

    def test_inter_game_state_without_delay_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="without inter_game_delay_s"):
            cfgmod.load(self._write(tmp_path, tdir, inter_game_state="a"))

    def test_wait_range_validated(self, tmp_path, tdir):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {"a": {"detect": "marker.png",
                             "on_match": [{"type": "wait", "ms": [1400, 800]}]}},
        }
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        with pytest.raises(cfgmod.ConfigError, match="wait.ms"):
            cfgmod.load(p)

    def test_wait_range_ok(self, tmp_path, tdir):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {"a": {"detect": "marker.png",
                             "on_match": [{"type": "wait", "ms": [800, 1400]},
                                          {"type": "stop"}]}},
        }
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        cfgmod.load(p)  # must not raise
