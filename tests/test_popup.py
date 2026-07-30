"""Phase 6 — verified popup dismissal and the restart_app escape."""
import json
from pathlib import Path

import numpy as np
import pytest

import src.act as actmod
from src import config as cfgmod
from src.act import Actor
from src.perceive import Match

CONFIG_DIR = Path("config/cookierun")


class FakeDevice:
    serial = "fake"

    def __init__(self):
        self.taps = []

    def shell(self, *args):
        if args[:2] == ("input", "tap"):
            self.taps.append((int(args[2]), int(args[3])))
        return ""


@pytest.fixture
def actor(monkeypatch):
    monkeypatch.setattr(actmod.time, "sleep", lambda s: None)
    monkeypatch.setattr(actmod, "grab",
                        lambda d, retries=2: np.zeros((10, 10, 3), dtype=np.uint8))
    dev = FakeDevice()
    a = Actor(dev, store=object(), dry_run=False)
    a.device = dev
    return a


def _found(monkeypatch, sequence):
    """find_named answers from a script of booleans, then False forever."""
    seq = list(sequence)

    def fake(frame, store, name, thr):
        hit = seq.pop(0) if seq else False
        return Match(found=hit, score=1.0 if hit else 0.1, x=1, y=1, w=1, h=1)

    monkeypatch.setattr(actmod, "find_named", fake)


class TestClosePopup:
    def test_taps_once_when_popup_goes_away(self, actor, monkeypatch):
        _found(monkeypatch, [False])
        actor.run({"type": "close_popup", "x": 100, "y": 200,
                   "verify": "p.png", "settle_ms": 0}, None)
        assert actor.device.taps and len(actor.device.taps) == 1

    def test_retaps_while_popup_still_matches(self, actor, monkeypatch):
        """A tap landing mid-fade does nothing; the old blind tap+wait pair had
        no way to notice, which is the bug this action exists for."""
        _found(monkeypatch, [True, False])
        actor.run({"type": "close_popup", "x": 100, "y": 200,
                   "verify": "p.png", "settle_ms": 0, "retries": 2}, None)
        assert len(actor.device.taps) == 2

    def test_gives_up_after_retries(self, actor, monkeypatch):
        _found(monkeypatch, [True] * 10)
        actor.run({"type": "close_popup", "x": 1, "y": 2,
                   "verify": "p.png", "settle_ms": 0, "retries": 2}, None)
        assert len(actor.device.taps) == 3  # 1 + 2 retries, then moves on

    def test_without_verify_stays_blind(self, actor, monkeypatch):
        _found(monkeypatch, [True] * 5)  # would retry forever if consulted
        actor.run({"type": "close_popup", "x": 1, "y": 2, "settle_ms": 0}, None)
        assert len(actor.device.taps) == 1

    def test_jitters_the_tap(self, actor, monkeypatch):
        """Close taps go through the same humanized tap as everything else."""
        _found(monkeypatch, [False] * 40)
        for _ in range(40):
            actor.run({"type": "close_popup", "x": 500, "y": 500,
                       "verify": "p.png", "settle_ms": 0}, None)
        assert len({t for t in actor.device.taps}) > 1


class TestRestartApp:
    def test_calls_the_restarter(self, actor):
        class Spy:
            n = 0

            def restart(self):
                Spy.n += 1

        actor.restarter = Spy()
        actor.run({"type": "restart_app"}, None)
        assert Spy.n == 1

    def test_dry_run_does_nothing(self, monkeypatch):
        class Spy:
            n = 0

            def restart(self):
                Spy.n += 1

        a = Actor(FakeDevice(), store=object(), dry_run=True)
        a.restarter = Spy()
        a.run({"type": "restart_app"}, None)
        assert Spy.n == 0

    def test_missing_restarter_warns_not_crashes(self, actor, caplog):
        actor.restarter = None
        actor.run({"type": "restart_app"}, None)  # must not raise
        assert any("no restarter" in r.message for r in caplog.records)

    def test_action_type_accepted_by_validation(self, tmp_path, tdir):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {"a": {"detect": "marker.png",
                             "on_match": [{"type": "restart_app"},
                                          {"type": "goto", "state": "a"}]}},
        }
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        cfgmod.load(p)  # must not raise


class TestShippedConfigsUseVerifiedCloses:
    """The migration must have landed, and landed only where it belongs."""

    def _configs(self):
        return sorted(CONFIG_DIR.glob("*.json"))

    def test_popup_states_verify_their_own_marker(self):
        checked = 0
        for path in self._configs():
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, st in raw["states"].items():
                om = st.get("on_match")
                if not isinstance(om, list):
                    continue
                for a in om:
                    if a.get("type") != "close_popup":
                        continue
                    checked += 1
                    # verify must be the state's OWN marker: anything else and
                    # the retry loop would be watching the wrong screen
                    assert a.get("verify") == st.get("detect"), f"{path.name}:{name}"
        # every close_popup across the active configs must verify its own marker;
        # the exact count moves as configs are added or archived, so just require
        # the migration actually landed somewhere rather than a brittle number.
        assert checked > 40, f"only {checked} close_popup found — migration missing?"

    def test_navigation_taps_left_blind(self):
        """home/shop/in-run taps are navigation, not dismissal — converting them
        would make the loop wait for a screen that is supposed to stay."""
        keep_blind = {"home", "await_shop", "buy_magnet", "check_heart",
                      "mb_open", "lives_scan"}
        raw = json.loads((CONFIG_DIR / "boxrun_toggle.json").read_text(encoding="utf-8"))
        for name in keep_blind:
            st = raw["states"].get(name)
            if st is None:
                continue
            for lst in ([st.get("on_match")] if isinstance(st.get("on_match"), list) else []) + \
                       ([st["on_absent"]] if isinstance(st.get("on_absent"), list) else []):
                assert not any(a.get("type") == "close_popup" for a in lst), name

    def test_all_configs_still_load(self):
        for path in self._configs():
            cfgmod.load(path)  # validation covers verify templates existing
