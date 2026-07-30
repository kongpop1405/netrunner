"""Phase 2 — session reset: restart verification and the FSM timer."""
import json

import numpy as np
import pytest

import src.fsm as fsm
import src.session as sessionmod
from src import config as cfgmod
from src.config import Config
from src.device import AdbError
from src.perceive import Match
from src.session import Restarter, SessionError


@pytest.fixture(autouse=True)
def _no_waiting(monkeypatch):
    """Collapse every settle/gap so the spaced checks run instantly."""
    monkeypatch.setattr(sessionmod, "STOP_SETTLE_S", 0)
    monkeypatch.setattr(sessionmod, "LAUNCH_SETTLE_S", 0)
    monkeypatch.setattr(sessionmod, "STABILITY_GAP_S", 0)
    monkeypatch.setattr(sessionmod, "RETRY_GAP_S", 0)
    monkeypatch.setattr(sessionmod.time, "sleep", lambda s: None)


class ScriptedDevice:
    """`pidof` answers come from a script; everything else is recorded."""

    serial = "fake"

    def __init__(self, pidof_script):
        self.pidof = list(pidof_script)
        self.calls = []

    def shell(self, *args):
        self.calls.append(args)
        if args[0] == "pidof":
            return self.pidof.pop(0) if self.pidof else ""
        if args[:2] == ("cmd", "package"):
            return "com.devsisters.crg/com.unity3d.player.UnityPlayerActivity"
        return ""


class TestRestarter:
    def test_happy_path(self):
        # 1 post-launch check + 3 stability checks
        dev = ScriptedDevice(["1234"] * 4)
        launched = []
        Restarter(dev, start_app=lambda: launched.append(1)).restart()
        assert launched == [1]
        assert ("am", "force-stop", "com.devsisters.crg") in dev.calls

    def test_crash_during_stability_then_success(self):
        """A launch that dies inside the stability window must be retried, not
        accepted — `am start` returning success proves nothing."""
        dev = ScriptedDevice([
            "1234", "1234", "",          # attempt 1: alive, alive, dead
            "1234", "1234", "1234", "1234",  # attempt 2: clean
        ])
        launched = []
        Restarter(dev, start_app=lambda: launched.append(1)).restart()
        assert len(launched) == 2

    def test_gives_up_after_max_attempts(self, monkeypatch):
        monkeypatch.setattr(sessionmod, "MAX_ATTEMPTS", 3)
        dev = ScriptedDevice([""] * 20)  # never comes up
        launched = []
        with pytest.raises(SessionError, match="stay running"):
            Restarter(dev, start_app=lambda: launched.append(1)).restart()
        assert len(launched) == 3

    def test_launch_error_counts_as_attempt(self, monkeypatch):
        monkeypatch.setattr(sessionmod, "MAX_ATTEMPTS", 2)

        def boom():
            raise AdbError("device offline")

        dev = ScriptedDevice([""] * 10)
        with pytest.raises(SessionError):
            Restarter(dev, start_app=boom).restart()

    def test_am_start_fallback_used_without_start_app(self):
        dev = ScriptedDevice(["1234"] * 4)
        Restarter(dev).restart()
        assert any(c[:2] == ("am", "start") for c in dev.calls)

    def test_unresolvable_activity_raises(self, monkeypatch):
        monkeypatch.setattr(sessionmod, "MAX_ATTEMPTS", 1)

        class NoActivity(ScriptedDevice):
            def shell(self, *args):
                if args[:2] == ("cmd", "package"):
                    return "No activity found"
                return super().shell(*args)

        with pytest.raises(SessionError, match="stay running"):
            Restarter(NoActivity([""] * 5)).restart()

    def test_pidof_adb_error_assumed_alive(self):
        """An adb hiccup during a check is not proof the app died."""
        class Flaky(ScriptedDevice):
            def shell(self, *args):
                if args[0] == "pidof":
                    raise AdbError("timed out")
                return super().shell(*args)

        Restarter(Flaky([]), start_app=lambda: None).restart()  # must not raise


# --- FSM timer -------------------------------------------------------------------


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start, **kw):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states, **kw)


def _patch_loop(monkeypatch, found: set[str], *, clock_step: float = 0.0):
    """Stub the loop's IO. `clock_step` advances a fake monotonic clock by that
    many seconds per CYCLE (driven off grab, which runs once per cycle) — real
    wall time cannot be used because sleeping is stubbed out, and a per-read
    clock would make elapsed time depend on how often the loop reads it."""
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


class _SpyRestarter:
    def __init__(self, fail=False):
        self.count = 0
        self.fail = fail

    def restart(self):
        self.count += 1
        if self.fail:
            raise SessionError("app will not stay up")


def _lap_states():
    return {
        "home": {"detect": "home.png", "on_match": [
            {"type": "tap_xy", "x": 1, "y": 1}, {"type": "goto", "state": "running"}]},
        "running": {"detect": "running.png", "on_match": [
            {"type": "tap_xy", "x": 2, "y": 2}, {"type": "goto", "state": "home"}]},
    }


class TestFsmSessionReset:
    def test_resets_when_budget_elapsed(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        spy = _SpyRestarter()
        cfg = _cfg(_lap_states(), "home", session_reset_s=(5.0, 6.0))
        fsm.Runner(cfg, FakeDevice(), restarter=spy).run(max_cycles=12)
        assert spy.count >= 1

    def test_never_resets_before_budget(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"})
        spy = _SpyRestarter()
        cfg = _cfg(_lap_states(), "home", session_reset_s=(3600.0, 7200.0))
        fsm.Runner(cfg, FakeDevice(), restarter=spy).run(max_cycles=20)
        assert spy.count == 0

    def test_only_at_reset_state(self, monkeypatch):
        """A due reset must wait for the safe state — restarting mid-run would
        forfeit the run and its heart."""
        _patch_loop(monkeypatch, {"running.png"}, clock_step=1.0)  # home never matches
        spy = _SpyRestarter()
        states = _lap_states()
        states["running"]["on_match"] = [{"type": "tap_xy", "x": 2, "y": 2},
                                         {"type": "goto", "state": "running"}]
        cfg = _cfg(states, "running", session_reset_s=(2.0, 3.0),
                   reset_at_state="home")
        fsm.Runner(cfg, FakeDevice(), restarter=spy).run(max_cycles=15)
        assert spy.count == 0  # never reached home

    def test_dry_run_never_resets(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        spy = _SpyRestarter()
        cfg = _cfg(_lap_states(), "home", session_reset_s=(5.0, 6.0))
        fsm.Runner(cfg, FakeDevice(), restarter=spy).run(dry_run=True, max_cycles=12)
        assert spy.count == 0

    def test_no_restarter_disables_reset(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        cfg = _cfg(_lap_states(), "home", session_reset_s=(5.0, 6.0))
        fsm.Runner(cfg, FakeDevice()).run(max_cycles=8)  # must not crash

    def test_failed_restart_is_fatal(self, monkeypatch):
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        spy = _SpyRestarter(fail=True)
        cfg = _cfg(_lap_states(), "home", session_reset_s=(5.0, 6.0))
        with pytest.raises(fsm.FsmError, match="session reset failed"):
            fsm.Runner(cfg, FakeDevice(), restarter=spy).run(max_cycles=12)

    def test_resumes_from_start_state(self, monkeypatch):
        """After the app restarts, the loop must re-enter at start_state — the
        screen it believed in is gone."""
        _patch_loop(monkeypatch, {"home.png", "running.png"}, clock_step=1.0)
        seen = []
        real = fsm.Runner._session_reset

        def spy_reset(self, elapsed):
            seen.append("reset")
            real(self, elapsed)

        monkeypatch.setattr(fsm.Runner, "_session_reset", spy_reset)
        # reset on the very first arrival back at home (budget 1s, 1s per cycle)
        # so the only long sleep that could appear would be the lap after it
        cfg = _cfg(_lap_states(), "home", session_reset_s=(1.0, 1.5),
                   inter_game_delay_s=(30.0, 60.0))
        sleeps = []
        monkeypatch.setattr(fsm.time, "sleep", sleeps.append)
        fsm.Runner(cfg, FakeDevice(), restarter=_SpyRestarter()).run(max_cycles=4)
        assert seen
        # the lap right after a reset must not also idle 30-60s: the app just
        # went away and came back, a far longer gap than any inter-game pause
        assert not [s for s in sleeps if s >= 30]


class TestSessionConfig:
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

    def test_parsed(self, tmp_path, tdir):
        cfg = cfgmod.load(self._write(tmp_path, tdir, session_reset_s=[5400, 10800],
                                      package="com.x.y"))
        assert cfg.session_reset_s == (5400, 10800)
        assert cfg.package == "com.x.y"

    def test_bad_range_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="session_reset_s"):
            cfgmod.load(self._write(tmp_path, tdir, session_reset_s=[10800, 5400]))

    def test_reset_at_state_must_exist(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="reset_at_state"):
            cfgmod.load(self._write(tmp_path, tdir, session_reset_s=[100, 200],
                                    reset_at_state="ghost"))

    def test_reset_at_state_without_budget_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="without session_reset_s"):
            cfgmod.load(self._write(tmp_path, tdir, reset_at_state="a"))


class TestWantsRestarter:
    """A restart_app action needs a Restarter as much as a scheduled reset does —
    Connection Lost hands off to it, and a warn-and-noop is the wrong recovery for
    a dropped connection."""

    def _cfg_with(self, state):
        return Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                      start_state="a", states={"a": state})

    def test_session_reset_wants_one(self):
        import main
        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                     start_state="a", states={"a": {"detect": "a.png"}},
                     session_reset_s=(60.0, 90.0))
        assert main._wants_restarter(cfg)

    def test_restart_app_in_on_match_wants_one(self):
        import main
        cfg = self._cfg_with({"detect": "a.png", "on_match": [{"type": "restart_app"}]})
        assert main._wants_restarter(cfg)

    def test_restart_app_in_on_absent_wants_one(self):
        import main
        cfg = self._cfg_with({"detect": "a.png",
                              "on_absent": [{"type": "restart_app"},
                                            {"type": "goto", "state": "a"}]})
        assert main._wants_restarter(cfg)

    def test_restart_app_in_branching_on_match_wants_one(self):
        import main
        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                     start_state="a", states={"a": {
                         "detect": ["x.png", "y.png"],
                         "on_match": {"x.png": [{"type": "goto", "state": "a"}],
                                      "y.png": [{"type": "restart_app"}]}}})
        assert main._wants_restarter(cfg)

    def test_plain_config_wants_none(self):
        import main
        cfg = self._cfg_with({"detect": "a.png", "on_match": [{"type": "goto", "state": "a"}]})
        assert not main._wants_restarter(cfg)

    def test_build_restarter_none_for_plain_config(self):
        import main
        cfg = self._cfg_with({"detect": "a.png", "on_match": [{"type": "goto", "state": "a"}]})

        class D:
            serial = "x"
        assert main.build_restarter(cfg, D(), "adb", None) is None

    def test_build_restarter_present_for_restart_app_config(self):
        import main
        cfg = self._cfg_with({"detect": "a.png", "on_match": [{"type": "restart_app"}]})

        class D:
            serial = "127.0.0.1:5555"
        r = main.build_restarter(cfg, D(), "adb", None)
        assert r is not None and hasattr(r, "restart")

    def test_shipped_connectionlost_configs_get_a_restarter(self):
        """Every config with a probe_connectionlost state must actually build a
        Restarter, or restart_app silently does nothing there."""
        import glob
        import main
        from src import config as cfgmod

        class D:
            serial = "127.0.0.1:5555"

        for path in sorted(glob.glob("config/cookierun/*.json")):
            cfg = cfgmod.load(path)
            uses_restart = any(
                a.get("type") == "restart_app"
                for st in cfg.states.values()
                for block in ([st.get("on_match")] if isinstance(st.get("on_match"), list)
                              else list(st["on_match"].values()) if isinstance(st.get("on_match"), dict)
                              else []) + ([st["on_absent"]] if isinstance(st.get("on_absent"), list) else [])
                for a in block)
            if uses_restart:
                assert main.build_restarter(cfg, D(), "adb", None) is not None, path
