"""Phase 7 — unknown-screen collector + log report parser."""
import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

import src.fsm as fsm
from src.config import Config
from src.perceive import Match

# tools/ is a script dir, not a package (no __init__.py) — load by path so the
# test does not depend on rootdir happening to be on sys.path.
_spec = importlib.util.spec_from_file_location(
    "report_runs", Path(__file__).resolve().parent.parent / "tools" / "report_runs.py")
report_runs = importlib.util.module_from_spec(_spec)
sys.modules["report_runs"] = report_runs
_spec.loader.exec_module(report_runs)


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _cfg(states, start):
    return Config(device=None, templates_dir=".", poll_ms=1,
                  match_threshold=0.8, start_state=start, states=states)


# --- collector -------------------------------------------------------------------


class TestUnknownScreenCollector:
    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch, tmp_path):
        self.images = []
        self.dir = tmp_path / "unknown"
        monkeypatch.setattr(fsm, "_STUCK_STATE_WARN_CYCLES", 3)
        monkeypatch.setattr(fsm, "send_alert", lambda *a, **k: None)
        monkeypatch.setattr(fsm, "send_alert_with_image",
                            lambda url, title, msg, path, **k: self.images.append(path))
        monkeypatch.setattr(fsm, "grab",
                            lambda device, retries=2: np.zeros((8, 8, 3), dtype=np.uint8))

    def _run(self, states, start, cycles):
        fsm.Runner(_cfg(states, start), FakeDevice(),
                   unknown_dir=self.dir).run(max_cycles=cycles)

    def test_archives_once_per_stuck_episode(self, monkeypatch):
        """Same-state livelock: one PNG + one image alert, not one per poll."""
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=True, score=1.0, x=1, y=1, w=1, h=1))
        states = {"a": {"detect": "a.png", "on_match": [{"type": "wait", "ms": 0}]}}
        self._run(states, "a", 20)
        assert len(self.images) == 1
        assert len(list(self.dir.glob("*.png"))) == 1
        assert "_a.png" in self.images[0].name  # state name in the filename

    def test_archives_on_pingpong_livelock(self, monkeypatch):
        """Goto-cycle livelock (states change, nothing acted) also archives."""
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=name == "a.png", score=1.0 if name == "a.png" else 0.1, x=1, y=1, w=1, h=1))
        states = {
            "a": {"detect": "a.png", "on_match": [{"type": "goto", "state": "b"}]},
            "b": {"detect": "b.png", "on_absent": {"goto": "a"}, "timeout_ms": 99999},
        }
        self._run(states, "a", 30)
        assert len(self.images) >= 1

    def test_archive_failure_does_not_kill_run(self, monkeypatch):
        """Observability is best-effort: a broken save must not end the farm."""
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=True, score=1.0, x=1, y=1, w=1, h=1))
        monkeypatch.setattr(fsm.cv2, "imwrite",
                            lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
        states = {"a": {"detect": "a.png", "on_match": [{"type": "wait", "ms": 0}]}}
        self._run(states, "a", 10)  # must not raise
        assert self.images == []

    def test_no_archive_when_healthy(self, monkeypatch):
        """A loop that keeps transitioning and acting never archives."""
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=True, score=1.0, x=1, y=1, w=1, h=1))
        states = {
            "a": {"detect": "a.png", "on_match": [
                {"type": "tap_xy", "x": 1, "y": 1}, {"type": "goto", "state": "b"}]},
            "b": {"detect": "b.png", "on_match": [
                {"type": "tap_xy", "x": 2, "y": 2}, {"type": "goto", "state": "a"}]},
        }
        fsm.Runner(_cfg(states, "a"), FakeDevice(),
                   unknown_dir=self.dir).run(dry_run=True, max_cycles=20)
        assert self.images == []
        assert not self.dir.exists()


# --- log parser ------------------------------------------------------------------


def _log(tmp_path, name, lines):
    p = tmp_path / name
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestReportRuns:
    def test_counts_runs_boxes_and_failures(self, tmp_path):
        _log(tmp_path, "netrunner.log.2026-07-30_10", [
            "10:00:01 INFO netrunner.fsm: start state=home device=x dry_run=False",
            "10:00:05 INFO netrunner.fsm: transition home -> running",
            "10:01:00 INFO netrunner.fsm: transition running -> run_result",
            "10:01:02 INFO netrunner.fsm: transition run_result -> mb_open",
            "10:02:00 INFO netrunner.fsm: transition mb_open -> home",
            "10:02:10 INFO netrunner.fsm: transition home -> running",
            "10:03:00 WARNING netrunner.fsm: adb error on cycle 42 (1/5 before giving up): boom",
            "10:04:00 WARNING netrunner.fsm: perceive error on cycle 50 (1/5 before giving up): oom",
        ])
        s = report_runs.summarize(report_runs.collect(tmp_path))
        assert s["events"]["runs_started"] == 2
        assert s["events"]["runs_finished"] == 1
        assert s["events"]["boxes_seen"] == 1
        assert s["events"]["adb_fail"] == 1
        assert s["events"]["perceive_fail"] == 1
        assert s["events"]["session_start"] == 1

    def test_midnight_wrap(self, tmp_path):
        """Log lines carry only HH:MM:SS — a clock going backwards means a new day,
        otherwise the span would come out negative."""
        _log(tmp_path, "netrunner.log.2026-07-30_23", [
            "23:59:58 INFO netrunner.fsm: transition home -> running",
            "00:00:04 INFO netrunner.fsm: transition running -> run_result",
        ])
        rows = report_runs.collect(tmp_path)
        assert rows[1]["ts"] > rows[0]["ts"]
        assert (rows[1]["ts"] - rows[0]["ts"]).total_seconds() == 6

    def test_ignores_traceback_continuations(self, tmp_path):
        _log(tmp_path, "netrunner.log.2026-07-30_10", [
            "10:00:00 ERROR netrunner: unhandled crash",
            "Traceback (most recent call last):",
            '  File "main.py", line 1, in <module>',
            "10:00:01 INFO netrunner.fsm: transition home -> running",
        ])
        rows = report_runs.collect(tmp_path)
        assert len(rows) == 2

    def test_renders_html_with_stats(self, tmp_path):
        _log(tmp_path, "netrunner.log.2026-07-30_10", [
            "10:00:05 INFO netrunner.fsm: transition home -> running",
            "11:00:05 INFO netrunner.fsm: transition running -> run_result",
        ])
        out = tmp_path / "out" / "runs.html"
        s = report_runs.summarize(report_runs.collect(tmp_path))
        report_runs.render(s, out, tmp_path)
        body = out.read_text(encoding="utf-8")
        assert '<meta charset="utf-8">' in body  # served over HTTP without mojibake
        assert "Runs started" in body

    def test_empty_logs_render_placeholder(self, tmp_path):
        out = tmp_path / "runs.html"
        s = report_runs.summarize([])
        report_runs.render(s, out, tmp_path)
        assert "Nothing to summarize" in out.read_text(encoding="utf-8")


# --- progress watchdog -----------------------------------------------------------


class TestProgressWatchdog:
    """The 2026-07-31 livelock: 389 cycles of jumping into an unrecognised News
    popup over 13h, with BOTH existing detectors silent — state kept changing
    (same_state_streak reset every poll) and jump/slide count as actions
    (no_act_streak reset every poll). The watchdog asks the question neither of
    them does: did the loop reach anywhere that counts as progress?
    """

    @pytest.fixture(autouse=True)
    def _stub(self, monkeypatch, tmp_path):
        self.alerts = []
        self.dir = tmp_path / "unknown"
        monkeypatch.setattr(fsm, "send_alert",
                            lambda url, title, msg, **k: self.alerts.append(title))
        monkeypatch.setattr(fsm, "send_alert_with_image", lambda *a, **k: None)
        monkeypatch.setattr(fsm, "grab",
                            lambda device, retries=2: np.zeros((8, 8, 3), dtype=np.uint8))
        # Never match: every detect is absent, so the loop walks its absent edges
        # exactly like a screen nothing recognises.
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=False, score=0.1, x=0, y=0, w=1, h=1))

    def _cfg_with_watchdog(self, **over):
        # A miniature of the real loop: run -> jump -> back to run, plus a home
        # the watchdog can recover into. Nothing here ever reaches `home` on its
        # own — that is the livelock.
        states = {
            "running": {"detect": "result.png", "on_absent": {"goto": "jump"}},
            "jump": {"detect": "result.png",
                     "on_absent": [{"type": "tap_xy", "x": 1, "y": 1},
                                   {"type": "goto", "state": "running"}]},
            "home": {"detect": "home.png", "on_absent": {"goto": "running"}},
        }
        cfg = _cfg(states, "running")
        cfg.progress_states = frozenset(["home"])
        cfg.no_progress_goto = "home"
        cfg.no_progress_s = 0.05
        for k, v in over.items():
            setattr(cfg, k, v)
        return cfg

    def _run(self, cfg, cycles=40):
        fsm.Runner(cfg, FakeDevice(), unknown_dir=self.dir).run(max_cycles=cycles)

    def test_fires_when_no_progress_state_is_reached(self):
        """The livelock shape: busy, state-changing, going nowhere."""
        self._run(self._cfg_with_watchdog())
        assert "NetRunner: no progress" in self.alerts
        assert list(self.dir.glob("*.png")), "stuck frame must be archived for cropping"

    def test_disabled_by_default(self):
        """Configs that never opted in must behave exactly as before."""
        cfg = self._cfg_with_watchdog()
        cfg.no_progress_goto = None
        self._run(cfg)
        assert "NetRunner: no progress" not in self.alerts

    def test_reaching_a_progress_state_resets_the_timer(self, monkeypatch):
        """A healthy loop passes through progress states and never trips."""
        # `home` matches now, so the loop parks there — i.e. it keeps arriving at
        # a progress state, which is what a working farm loop does between runs.
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=name == "home.png", score=1.0, x=0, y=0, w=1, h=1))
        cfg = self._cfg_with_watchdog()
        cfg.states["home"]["on_match"] = [{"type": "wait", "ms": 0}]
        cfg.start_state = "home"
        self._run(cfg)
        assert "NetRunner: no progress" not in self.alerts

    def test_second_fire_escalates(self):
        """The cheap recovery having failed, the next fire must not repeat it.

        Live 2026-08-01: the Events popup has no marker and ignores Android BACK,
        so a probe-chain recovery returns to the same stuck screen. Repeating it
        forever would be the original livelock with extra steps.
        """
        cfg = self._cfg_with_watchdog()
        cfg.states["restart"] = {"detect": "restart.png",
                                 "on_absent": {"goto": "running"}}
        cfg.no_progress_escalate_goto = "restart"
        seen = []
        cfg.states["home"]["on_absent"] = {"goto": "running"}
        real = fsm.Runner._archive_unknown
        fsm.Runner._archive_unknown = lambda self, f, s: seen.append(s)
        try:
            # The grace window deliberately spaces fires out, so make it small
            # enough that a second one lands inside the cycle budget.
            monkeypatch_grace = 0.05
            orig_grace = fsm._RECOVERY_GRACE_S
            fsm._RECOVERY_GRACE_S = monkeypatch_grace
            self._run(cfg, cycles=200)
        finally:
            fsm._RECOVERY_GRACE_S = orig_grace
            fsm.Runner._archive_unknown = real
        assert len(seen) >= 2, "watchdog must re-arm and fire again"
        assert self.alerts.count("NetRunner: no progress") >= 2

    def test_recovery_gets_a_grace_window(self, monkeypatch):
        """A slow recovery must not be judged while it is still running.

        restart_app + relogin measured 99s live (2026-08-01) — longer than a
        tight no_progress_s. Without the grace window the watchdog fires again
        mid-restart and stacks a second restart on the one in flight.
        """
        monkeypatch.setattr(fsm, "_RECOVERY_GRACE_S", 30)
        cfg = self._cfg_with_watchdog()
        cfg.no_progress_s = 0.05
        fires = []
        real = fsm.Runner._archive_unknown
        fsm.Runner._archive_unknown = lambda self, f, s: fires.append(s)
        try:
            self._run(cfg, cycles=60)
        finally:
            fsm.Runner._archive_unknown = real
        # Without the grace window this loop fires on essentially every poll.
        assert len(fires) == 1, f"grace window must suppress re-fires, got {len(fires)}"

    def test_the_blind_threshold_clears_a_healthy_run(self):
        """The limit is a measurement, not a derivation.

        Sizing it off the state-table length (32 states -> 48) fired mid-run on a
        live boxrun_magnet: home -> ten probes -> boost_shop -> the in-run jump
        chain match nothing by design, which measured 70 consecutive misses on
        2026-08-06, and the recovery cost a heart and a 7.3M-point run. The Events
        popup — a genuinely unrecognised screen — reached 229 before escalating.
        Anything inside that gap is safe; 48 was not.
        """
        healthy_run_misses = 70      # measured, healthy boxrun_magnet
        stuck_screen_misses = 229    # measured, Events popup
        assert fsm._BLIND_LAP_CYCLES > healthy_run_misses, (
            "would fire during a normal run and forfeit it")
        assert fsm._BLIND_LAP_CYCLES < stuck_screen_misses, (
            "would never beat the wall clock it exists to pre-empt")

    def test_blind_lap_fires_before_the_wall_clock(self, monkeypatch):
        """Nothing matching anywhere is a stuck screen, and knowing that does not
        require waiting out no_progress_s.

        Party Run (2026-08-06) rode a 29-state absent chain at ~21s a lap for 38
        passes of blind tapping before 300s elapsed. The wall clock cannot tell
        that from a long run; a streak of misses outliving the whole state table
        can only mean nothing on screen is recognised.
        """
        monkeypatch.setattr(fsm, "_BLIND_LAP_CYCLES", 6)
        cfg = self._cfg_with_watchdog()
        cfg.no_progress_s = 3600  # the wall clock must not be what fires
        fires = []
        real = fsm.Runner._archive_unknown
        fsm.Runner._archive_unknown = lambda self, f, s: fires.append(s)
        try:
            self._run(cfg, cycles=10)
        finally:
            fsm.Runner._archive_unknown = real
        assert fires, "a blind lap must trip the recovery on its own"
        assert "NetRunner: unrecognised screen" in self.alerts, self.alerts

    def test_a_match_anywhere_clears_the_blind_streak(self, monkeypatch):
        """The streak counts misses, not polls: a loop that keeps matching
        something is being understood, however slowly it moves."""
        monkeypatch.setattr(fsm, "_BLIND_LAP_CYCLES", 6)
        # `running` matches every poll, so the loop sits there acting on it — busy
        # and never reaching a progress state, but never blind either.
        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: Match(
            found=name == "result.png", score=1.0, x=0, y=0, w=1, h=1))
        cfg = self._cfg_with_watchdog()
        cfg.no_progress_s = 3600
        cfg.states["running"]["on_match"] = [{"type": "wait", "ms": 0}]
        self._run(cfg, cycles=30)
        assert "NetRunner: unrecognised screen" not in self.alerts, self.alerts

    def test_blind_streak_is_also_held_off_during_recovery(self, monkeypatch):
        """The grace window has to cover both detectors.

        It works by pushing last_progress_at into the future, which silenced the
        wall clock but said nothing about the streak — and a restart+relogin polls
        ~99s matching nothing, so the streak would sail past its limit and stack a
        second recovery on the one still running.
        """
        monkeypatch.setattr(fsm, "_BLIND_LAP_CYCLES", 6)
        monkeypatch.setattr(fsm, "_RECOVERY_GRACE_S", 30)
        cfg = self._cfg_with_watchdog()
        cfg.no_progress_s = 0.05
        fires = []
        real = fsm.Runner._archive_unknown
        fsm.Runner._archive_unknown = lambda self, f, s: fires.append(s)
        try:
            self._run(cfg, cycles=60)
        finally:
            fsm.Runner._archive_unknown = real
        assert len(fires) == 1, (
            f"blind streak must respect the grace window too, got {len(fires)}")
