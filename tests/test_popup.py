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


class TestGuardParity:
    """Every config that runs on the home screen carries the same guards.

    Party Run (2026-08-06) was reachable from anywhere on home and detectable by
    nothing, so it livelocked whatever config happened to land there. A guard that
    exists in six configs and not the seventh just moves which launcher hangs.
    """

    def _home_configs(self):
        """Configs driving the home screen — i.e. those with the full template
        tree. sendlife_mailbox scopes itself to templates/cookierun/mailbox and
        drives a popup, so home markers do not exist for it to guard with."""
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if raw.get("templates_dir") == "templates/cookierun":
                out[path.stem] = raw
        return out

    def test_every_home_config_guards_party_run(self):
        configs = self._home_configs()
        assert len(configs) >= 11, f"expected the whole home set, got {sorted(configs)}"
        for name, raw in configs.items():
            g = raw["states"].get("guard_not_partyrun")
            assert g, f"{name} has no Party Run guard"
            assert g["detect"] == "home/partyrun_marker.png", name
            closes = [a for a in g["on_match"] if a.get("type") == "close_popup"]
            assert len(closes) == 1, f"{name}: {g['on_match']}"
            assert (closes[0]["x"], closes[0]["y"]) == (1820, 135), name

    #: Taps in the top-right banner strip are the ones that matter here: that is
    #: where Party Run's own entry point lives, so a blind tap landing there can
    #: open the screen the guard exists to close. Measured on a live Party Run
    #: frame (20260806_182330): (1640,107) is dark background BGR(93,52,51) —
    #: pressing nothing, forever — while (851,117) lands on the purple title bar
    #: itself, which is inert. Guarding against every tap on the path would flag
    #: harmless navigation and teach the next reader to skip the assertion.
    BANNER_STRIP_X = 1400
    BANNER_STRIP_Y = 200

    def _is_banner_tap(self, action):
        x = action.get("x", action.get("x1"))
        y = action.get("y", action.get("y1"))
        return (x is not None and y is not None
                and x > self.BANNER_STRIP_X and y < self.BANNER_STRIP_Y)

    def test_the_guard_precedes_every_blind_action_it_protects(self):
        """A guard placed after the blind tap is a guard that fires on the screen
        the tap just opened. addfriend's close_info tap (1640,107) sits four pixels
        from the (1633,107) that opened Party Run in the farm loop."""
        blind = {"tap_xy", "jump", "swipe"}
        for name, raw in self._home_configs().items():
            st = raw["states"]

            def absent_goto(spec):
                v = spec.get("on_absent")
                if isinstance(v, dict):
                    return v.get("goto")
                if isinstance(v, list):
                    return next((a["state"] for a in v
                                 if a.get("type") == "goto"), None)
                return None

            walked, node = [], raw["start_state"]
            while node and node in st and node not in walked:
                walked.append(node)
                node = absent_goto(st[node])
            assert "guard_not_partyrun" in walked, (
                f"{name}: the guard is not on the absent path, so a screen that "
                f"matches nothing never reaches it")
            pos = walked.index("guard_not_partyrun")
            for earlier in walked[:pos]:
                acts = st[earlier].get("on_absent")
                acts = acts if isinstance(acts, list) else []
                risky = [a for a in acts
                         if a.get("type") in blind and self._is_banner_tap(a)]
                assert not risky, (
                    f"{name}: {earlier} taps the Party Run banner strip at "
                    f"{risky} before the guard is checked")

    def test_every_home_config_has_a_watchdog(self):
        """Without one, a livelock ends only when --max-cycles does — which the
        errand configs relied on, and which is not a recovery."""
        for name, raw in self._home_configs().items():
            assert raw.get("no_progress_goto"), f"{name} has no watchdog"
            assert raw.get("progress_states"), f"{name} has no progress states"
            goto = raw["no_progress_goto"]
            assert goto in raw["states"], f"{name}: watchdog points at missing {goto}"
            esc = raw.get("no_progress_escalate_goto")
            assert esc in raw["states"], f"{name}: escalation points at missing {esc}"

    def test_check_heart_runs_sendlife_before_mailbox_with_headroom(self):
        """User request 2026-08-18: send lives to friends during the heart-empty
        wait (not just passively receive via mailbox), sendlife.json first so
        friends have time to send back before the mailbox sweep collects them.

        sendlife.json alone measured 1411s (23.5 min) on 2026-08-16; mailbox
        measured 138s; summed 1549s left almost no margin under the old
        1,500,000ms (25 min) check_heart timeout — raised to 3,000,000ms (50 min)
        when sendlife was re-added so the ceiling has real headroom again."""
        for name, raw in self._home_configs().items():
            st = raw["states"].get("check_heart")
            if not st:
                continue
            calls = [a["config"] for a in st["on_match"] if a.get("type") == "run_config"]
            assert calls == [
                "config/cookierun/sendlife.json",
                "config/cookierun/sendlife_mailbox.json",
            ], f"{name}: {calls}"
            assert st["timeout_ms"] >= 3_000_000, f"{name}: timeout_ms {st['timeout_ms']}"


class TestMailboxBaseHandlesEmptyFriendList:
    """Live 2026-08-18: 'No Lives received! Send Lives to friends...' — the Quick
    Receive & Send banner never renders when nobody's on the list, but the old
    single-marker detect (lives_tab_marker only) still matched every poll, so
    on_match kept blindly tap_template-ing a banner that plain wasn't there:
    logged WARNING and skipped, forever (acted=True is set before the tap even
    runs, so the no-action livelock detector never trips; timeout_ms only fires
    on the on_absent path). Fix: detect both markers, branch on which one
    actually matched, and skip the tap when only the tab (not the banner) is
    present.
    """

    PATH = Path("config/cookierun/sendlife_mailbox.json")

    def _mailbox_base(self):
        raw = json.loads(self.PATH.read_text(encoding="utf-8"))
        return raw["states"]["mailbox_base"]

    def test_detect_lists_both_markers(self):
        st = self._mailbox_base()
        assert st["detect"] == ["quick_btn_marker.png", "lives_tab_marker.png"], st["detect"]

    def test_banner_present_branch_taps_and_advances(self):
        st = self._mailbox_base()
        branch = st["on_match"]["quick_btn_marker.png"]
        taps = [a for a in branch if a.get("type") == "tap_template"]
        assert len(taps) == 1 and taps[0]["template"] == "quick_btn_marker.png", branch
        assert branch[-1] == {"type": "goto", "state": "confirm_loop"}, branch

    def test_banner_absent_branch_skips_the_tap(self):
        """Only the tab marker matched (empty list) -> go straight to
        confirm_loop, no tap_template attempted against a banner that isn't
        there."""
        st = self._mailbox_base()
        branch = st["on_match"]["lives_tab_marker.png"]
        assert not any(a.get("type") == "tap_template" for a in branch), branch
        assert branch == [{"type": "goto", "state": "confirm_loop"}], branch

    def test_neither_marker_still_falls_back_to_confirm_loop(self):
        """Genuinely-off-screen case (e.g. mailbox closed underneath us) must
        keep reaching confirm_loop too, same destination as both on_match
        branches — nothing here should be able to strand the run."""
        st = self._mailbox_base()
        assert st["on_absent"] == {"goto": "confirm_loop"}, st["on_absent"]
