"""Phase 6 — verified popup dismissal and the restart_app escape."""
import json
from pathlib import Path

import numpy as np
import pytest

import src.act as actmod
from src import config as cfgmod
from src.config import goto_targets
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

    def test_check_heart_sweeps_mailbox_then_gates_sendlife(self):
        """User request 2026-08-18: only send lives when the mailbox came up
        short. How many Lives are waiting cannot be read before opening the
        Mailbox — the Lives tab shows rows with no total, and the home envelope
        badge counts Notices+Rewards (seen going 46 -> 53 -> 58 in one session
        while sweeps confirmed 2-5 items, never dropping afterwards). So the
        sweep runs first and mailbox_count_gate branches on confirms actually
        made: 30 (the confirm_loop cap) means more were waiting, so get back to
        farming; fewer means the list drained and the idle heart-wait is worth
        spending on Send-Life across every Episode."""
        for name, raw in self._home_configs().items():
            st = raw["states"].get("check_heart")
            if not st:
                continue
            runs = [a for a in st["on_match"] if a.get("type") == "run_config"]
            calls = [a["config"] for a in runs]
            assert calls == ["config/cookierun/sendlife_mailbox.json"], (
                f"{name}: check_heart itself must only sweep the mailbox; "
                f"Send-Life belongs behind the gate. got {calls}")
            # The sweep is one popup chain and must never switch episodes.
            assert runs[0].get("episodes") is None, runs[0]

            gate_name = st["on_match"][-1].get("state")
            assert gate_name, f"{name}: check_heart must end by going to the gate"
            gate = raw["states"][gate_name]
            under = gate["visits_under"]
            assert under["state"] == "confirm_loop", gate
            # The gate's count and the sweep's own cap are the same quantity —
            # if they drift, "hit the cap" and "counted as many" stop agreeing.
            sweep = json.loads(
                (CONFIG_DIR / "sendlife_mailbox.json").read_text(encoding="utf-8"))
            cap = sweep["states"]["confirm_loop"]["max_visits"]
            assert under["count"] == cap, (
                f"{name}: gate counts {under['count']} but confirm_loop caps at {cap}")

            # Fewer than the cap -> Send-Life across every Episode, then back.
            few = gate["on_match"]
            sl = [a for a in few if a.get("type") == "run_config"]
            assert [a["config"] for a in sl] == ["config/cookierun/sendlife.json"], sl
            assert sl[0].get("episodes") == [1, 2, 3, 4, 5, 6, 7], sl[0]
            assert few[-1] == {"type": "goto", "state": "check_heart"}, few[-1]

            # At the cap -> straight back, no Send-Life on this pass.
            many = gate["on_absent"]
            many = many if isinstance(many, list) else [many]
            assert not [a for a in many if a.get("type") == "run_config"], (
                f"{name}: the mailbox-had-more branch must not run Send-Life")

            # 7 episodes x ~358s measured + 8 switches + the mailbox sweep budgets
            # to ~2,844s; run_config blocks in this state so it is all billed here.
            assert st["timeout_ms"] >= 5_700_000, f"{name}: timeout_ms {st['timeout_ms']}"


class TestPartyRunnersSeasonScreen:
    """Live 01:20 on 2026-08-19: the "Best Party Runners / The season is over!"
    leaderboard held the screen while the farm loop walked its guard chain
    normally. Nothing in the config matched it — the best-scoring template across
    the whole repo was friendcookie_innerclose at 0.97, a generic round X that
    hits on any dialog with a close button, so every guard missed and
    guard_not_inactive concluded the run was live."""

    def _farm_configs(self):
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            st = raw.get("states", {})
            # The farm loops, not the errand configs: addfriend carries a
            # guard_not_partyrun too but has no probe chain to hang the twin off.
            if "guard_not_partyrun" in st and "probe_rankingrewards" in st:
                out[path.stem] = raw
        return out

    def test_handled_on_both_chains(self):
        """A probe-only fix looks complete until the screen appears mid-run,
        where the probe states are unreachable — the 2026-07-31 News bug."""
        for name, raw in self._farm_configs().items():
            st = raw["states"]
            for side in ("probe_partyrunners", "guard_not_partyrunners"):
                assert side in st, f"{name}: {side} missing"
                assert st[side]["detect"] == "home/partyrunners_marker.png", st[side]

    def test_reachable_from_both_chains(self):
        """A state nothing points at never runs, however correct it is."""
        for name, raw in self._farm_configs().items():
            st = raw["states"]
            for target in ("probe_partyrunners", "guard_not_partyrunners"):
                inbound = [k for k, v in st.items()
                           if k != target and target in goto_targets(v)]
                assert inbound, f"{name}: nothing reaches {target}"

    def test_guard_returns_to_the_run_and_probe_to_home(self):
        for name, raw in self._farm_configs().items():
            st = raw["states"]
            gotos = lambda k: [a.get("state") for a in st[k]["on_match"]
                               if a.get("type") == "goto"]
            assert gotos("probe_partyrunners") == ["home"], name
            assert gotos("guard_not_partyrunners") == ["running"], name

    def test_closes_with_close_popup_not_a_blind_tap(self):
        """A blind tap cannot tell a wrong coordinate from a slow fade — the
        mistake that let the Party Run banner sit for 38 passes in silence."""
        for name, raw in self._farm_configs().items():
            for side in ("probe_partyrunners", "guard_not_partyrunners"):
                act = raw["states"][side]["on_match"][0]
                assert act["type"] == "close_popup", f"{name}/{side}: {act}"
                assert act.get("verify") == "home/partyrunners_marker.png", act

    def test_marker_exists(self):
        assert (Path("templates/cookierun/home/partyrunners_marker.png").exists())


class TestMailboxCapClosesItsDialog:
    """Live 00:24-00:33 on 2026-08-19: confirm_loop hit max_visits 30 and went
    straight to `done`, leaving item 31's "Send X a free Life?" dialog open.
    `done` looks for alldone_marker (measured 0.474 on that frame — absent), so
    it fell to close_mailbox, whose X at (1692,135) the dialog covers; close_popup
    warned twice and `stop` handed control back to the farm loop with the dialog
    still up. Nothing in the farm loop matches that screen (sendlife_marker scores
    0.598, under the 0.82 threshold), so it walked its guard chain looking healthy
    until the progress watchdog fired 601s later."""

    def _sweep(self):
        return json.loads(
            (CONFIG_DIR / "sendlife_mailbox.json").read_text(encoding="utf-8"))

    def test_cap_exits_through_a_state_that_closes_the_dialog(self):
        st = self._sweep()["states"]
        target = st["confirm_loop"]["max_visits_goto"]
        assert target != "done", (
            "the cap must not hand straight to `done` — the dialog that stopped "
            "the sweep is still on screen")
        gate = st[target]
        # It must key off the same marker confirm_loop uses, or it cannot tell
        # whether a dialog is actually there.
        assert gate["detect"] == st["confirm_loop"]["detect"], gate
        closes = [a for a in gate["on_match"]
                  if a.get("type") in ("close_popup", "tap_template", "tap_xy")]
        assert closes, f"{target} does not dismiss anything: {gate['on_match']}"
        # close_popup, not a blind tap: it re-reads the frame and warns if the
        # marker never clears.
        assert closes[0]["type"] == "close_popup", closes[0]
        assert closes[0].get("verify") == gate["detect"], closes[0]

    def test_cap_exit_leaves_the_queue_instead_of_working_it(self):
        """Measured live 2026-08-19 on the stuck frame (Lives badge 70): only the
        dialog's own X leaves the queue. Cancel accepts the current Life and
        re-opens the dialog for the next friend — 12 Cancel taps took the badge
        70 -> 37 and the heart counter up 32 before "All Lives received and sent!"
        appeared. Confirm does the same and sends a Life besides. Either button
        drains the list, which is what the cap exists to prevent."""
        st = self._sweep()["states"]
        gate = st[st["confirm_loop"]["max_visits_goto"]]
        buttons = {"Cancel": 727, "Confirm": 1192}  # measured button centres
        for a in gate["on_match"]:
            x, y = a.get("x"), a.get("y")
            if x is None:
                continue
            for label, bx in buttons.items():
                on_button_row = y is not None and abs(y - 687) < 60
                assert not (abs(x - bx) < 100 and on_button_row), (
                    f"tap at ({x},{y}) lands on {label} ({bx},687), which works "
                    f"the queue instead of leaving it")

    def test_cap_target_is_reachable(self):
        """`max_visits_goto` is an engine jump with no goto naming it, so the
        reachability walk has to know about it or this state reads as an orphan."""
        from src.config import goto_targets
        st = self._sweep()["states"]
        target = st["confirm_loop"]["max_visits_goto"]
        assert target in goto_targets(st["confirm_loop"]), (
            "goto_targets does not follow max_visits_goto")


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


class TestConnectionLostReachableFromMatchingHome:
    """Live livelock 2026-08-18: 'Connection lost!' dims home but Play! still
    matches through its scrim, so `home` took its on_match path, tapped Play into
    the dialog, and came right back — home -> verify_* -> await_shop -> running ->
    guard_not_home -> home, 24 laps, every transition logging normally and no
    state repeating, so neither the same-state nor the no-act livelock detector
    tripped. probe_connectionlost existed the whole time, but it hangs off
    home.on_absent, and a home that MATCHES never takes on_absent: the guard was
    unreachable on the only path that actually runs.

    So the dialog has to be ruled out on the match path too, which is what the
    verify_* chain is for (it was built for the inactive popup, which fails the
    exact same way — see verify_no_popup's own note).
    """

    def _configs(self):
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "verify_no_popup" in raw.get("states", {}):
                out[path.stem] = raw
        # The farm configs all carry this chain; an errand config does not. A
        # count this far below the set means the fixture stopped finding them.
        assert len(out) >= 8, f"expected the whole farm set, got {sorted(out)}"
        return out

    def _goto(self, spec):
        if isinstance(spec, dict):
            return spec.get("goto")
        if isinstance(spec, list):
            return next((a["state"] for a in spec if a.get("type") == "goto"), None)
        return None

    def test_the_play_tap_path_checks_connection_lost_before_tapping(self):
        configs = self._configs()
        assert configs, "no config carries the verify chain — wrong fixture?"
        for name, raw in configs.items():
            st = raw["states"]
            # walk what home's on_match hands off to, and require the dialog
            # check to sit on that path BEFORE any tap of Play.
            entry = next((a["state"] for a in st["home"].get("on_match", [])
                          if a.get("type") == "goto"), None)
            assert entry, f"{name}: home no longer hands off to a verify chain"

            walked, node = [], entry
            while node and node in st and node not in walked:
                walked.append(node)
                node = self._goto(st[node].get("on_absent"))
            assert "verify_no_connectionlost" in walked, (
                f"{name}: connection-lost is not checked on the path a MATCHING "
                f"home takes — walked {walked}")

    def test_the_dialog_arm_restarts_rather_than_dismissing(self):
        """Confirm on this dialog restarts the client rather than closing it, so a
        close_popup that waits for the marker to vanish would be waiting on the
        wrong thing — probe_connectionlost already handles it via restart_app."""
        for name, raw in self._configs().items():
            s = raw["states"]["verify_no_connectionlost"]
            assert s["detect"] == "home/connectionlost_marker.png", name
            kinds = [a.get("type") for a in s["on_match"]]
            assert "restart_app" in kinds, f"{name}: {kinds}"
            assert not any(k == "close_popup" for k in kinds), f"{name}: {kinds}"
            assert self._goto(s["on_match"]) == "recover_login", f"{name}: {kinds}"
