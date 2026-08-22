"""Phase 6 — verified popup dismissal and the restart_app escape."""
import json
from pathlib import Path

import numpy as np
import pytest

import src.act as actmod
from src import config as cfgmod
from src.config import goto_targets
from src.act import Actor
from src.perceive import Match, TemplateStore

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
        """User request 2026-08-18, revised 2026-08-20: pick ONE of two paths per
        heart-empty pass. Lots of mail waiting -> just drain it and get back to
        farming. Little mail -> spend the idle heart-wait sending Lives across
        every Episode, then drain again to collect what came back.

        The quantity is read, not inferred: remember_lives_waiting reads the
        Lives TAB badge with the Mailbox open and before the first Confirm.
        Measured 2026-08-20 on one frame: home envelope 55, Lives tab 53, Rewards
        tab 4 — the home badge totals every tab, so it cannot stand in for Lives
        (it read 46 -> 53 -> 58 across a session whose sweeps confirmed 2-5
        items, never dropping). The gate used to count confirm_loop visits
        against that state's own 30-confirm cap instead; the cap is gone now that
        the sweep must drain the list, so the badge is what is left to decide on.
        """
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
            assert "visits_under" not in gate, (
                f"{name}: the sweep no longer caps, so a visits count cannot "
                f"tell a long list from a short one — gate on the badge instead")
            assert gate["lives_under"]["count"] == 30, gate["lives_under"]

            sweep = json.loads(
                (CONFIG_DIR / "sendlife_mailbox.json").read_text(encoding="utf-8"))
            # The gate can only decide if something actually read the count, and
            # it has to be read before the drain empties the list.
            base = sweep["states"]["mailbox_base"]
            for marker, branch in base["on_match"].items():
                reads = [k for k, a in enumerate(branch)
                         if a.get("type") == "remember_lives_waiting"]
                assert reads == [0], (
                    f"{marker} branch must read the badge first, before the "
                    f"banner tap that starts draining: {branch}")

            # Few waiting -> Send-Life across every Episode, then sweep again so
            # the Lives those sends bring back are collected before farming.
            few = gate["on_match"]
            sl = [a["config"] for a in few if a.get("type") == "run_config"]
            assert sl == ["config/cookierun/sendlife.json",
                          "config/cookierun/sendlife_mailbox.json"], sl
            eps = [a for a in few if a.get("config", "").endswith("sendlife.json")]
            assert eps[0].get("episodes") == [1, 2, 3, 4, 5, 6, 7], eps[0]
            assert few[-1] == {"type": "goto", "state": "check_heart"}, few[-1]

            # Many waiting, or an unreadable badge -> straight back to farming.
            many = gate["on_absent"]
            many = many if isinstance(many, list) else [many]
            assert not [a for a in many if a.get("type") == "run_config"], (
                f"{name}: the mailbox-had-more branch must not run Send-Life")

            # 7 episodes x ~358s measured + 8 switches + two mailbox sweeps
            # budget to ~2,844s; run_config blocks in this state so it is all
            # billed here.
            assert st["timeout_ms"] >= 5_700_000, f"{name}: timeout_ms {st['timeout_ms']}"


class TestForegroundCheckOnRecovery:
    """Live 19:01-19:11 on 2026-08-19: LDPlayer's own store opened over the
    running game. Every guard and probe asks "which game screen is this?", so a
    screen that is not the game at all defeats all of them together — the FSM
    kept transitioning and the log read healthy while the bot jumped into a
    storefront. The first recovery pass could not help either: it also only
    looks for game screens."""

    def _configs_with_recovery(self):
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "recover_unknown" in raw.get("states", {}):
                out[path.stem] = raw
        return out

    def test_recovery_checks_the_foreground_before_probing(self):
        for name, raw in self._configs_with_recovery().items():
            acts = raw["states"]["recover_unknown"]["on_absent"]
            acts = [acts] if isinstance(acts, dict) else acts
            kinds = [a.get("type") for a in acts]
            assert "require_foreground" in kinds, f"{name}: {kinds}"
            # Before the goto, or the probe walk happens first and the check is
            # only reached on the next lap.
            assert kinds.index("require_foreground") < kinds.index("goto"), (
                f"{name}: foreground check runs after the goto: {kinds}")

    def test_recovery_still_ends_where_it_did(self):
        """The check is an addition, not a redirect — the chain must still walk
        the probe states it always did."""
        for name, raw in self._configs_with_recovery().items():
            acts = raw["states"]["recover_unknown"]["on_absent"]
            acts = [acts] if isinstance(acts, dict) else acts
            gotos = [a.get("state") for a in acts if a.get("type") == "goto"]
            assert len(gotos) == 1, f"{name}: {gotos}"
            assert gotos[0] in raw["states"], f"{name}: goes to missing {gotos[0]}"

    def test_action_is_registered(self):
        assert "require_foreground" in cfgmod._ACTION_TYPES
        assert cfgmod._REQUIRED_FIELDS.get("require_foreground") == set()


class TestEpisodeSurvivesRelogin:
    """Measured 2026-08-19: two restarts that went through recover_login came
    back on Episode 1, while a restart that did not kept Episode 2. recover_pick
    taps the saved-account row, and the game starts a fresh session on Episode 1.
    The farm configs only ever tap Play!, never an Episode, so nothing put the
    selection back — the bot farmed the wrong Episode with nothing in the log
    saying so."""

    class _Store:
        dir = Path("templates/cookierun")
        def get(self, name): return None

    def _actor(self, reads, *, dry_run=False):
        """reads: successive detect_current_episode results."""
        a = Actor(object(), self._Store(), dry_run=dry_run, default_threshold=0.82)
        seq = list(reads)
        switched = []
        import src.episode as epmod
        import tools.switch_episode as swmod
        orig_detect, orig_switch = epmod.detect_current_episode, swmod.switch_episode
        epmod.detect_current_episode = lambda *a, **k: seq.pop(0) if seq else None
        swmod.switch_episode = lambda dev, store, ep, **k: switched.append(ep)
        try:
            yield_ = (a, switched)
            return yield_, (orig_detect, orig_switch, epmod, swmod)
        except Exception:
            epmod.detect_current_episode, swmod.switch_episode = orig_detect, orig_switch
            raise

    def _run(self, reads, *, remembered=None, dry_run=False):
        (a, switched), (od, os_, epmod, swmod) = self._actor(reads, dry_run=dry_run)
        try:
            a.remembered_episode = remembered
            if remembered is None:
                a.remember_episode()
            else:
                a.restore_episode()
            return a.remembered_episode, switched
        finally:
            epmod.detect_current_episode, swmod.switch_episode = od, os_

    def test_remembers_what_home_shows(self):
        assert self._run([2])[0] == 2

    def test_an_unreadable_episode_does_not_erase_a_good_one(self):
        """A bad read must not overwrite the answer that will be restored."""
        (a, _), (od, os_, epmod, swmod) = self._actor([None])
        try:
            a.remembered_episode = 2
            a.remember_episode()
            assert a.remembered_episode == 2
        finally:
            epmod.detect_current_episode, swmod.switch_episode = od, os_

    def test_restores_when_the_login_reset_it(self):
        _, switched = self._run([1], remembered=2)
        assert switched == [2], switched

    def test_no_switch_when_the_episode_already_matches(self):
        _, switched = self._run([2], remembered=2)
        assert switched == [], switched

    def test_refuses_to_switch_blind(self):
        """switch_episode taps the Episode button without knowing what it is on,
        and there is no way back if the read was wrong."""
        _, switched = self._run([None], remembered=2)
        assert switched == [], switched

    def test_nothing_remembered_means_nothing_to_do(self):
        (a, switched), (od, os_, epmod, swmod) = self._actor([1])
        try:
            a.remembered_episode = None
            a.restore_episode()
            assert switched == []
        finally:
            epmod.detect_current_episode, swmod.switch_episode = od, os_

    def test_dry_run_never_switches(self):
        _, switched = self._run([1], remembered=2, dry_run=True)
        assert switched == [], switched


class TestEpisodeActionsAreWired:
    def _farm_configs(self):
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            st = raw.get("states", {})
            if "recover_pick" in st and "home" in st:
                out[path.stem] = raw
        return out

    def test_home_records_the_episode(self):
        for name, raw in self._farm_configs().items():
            kinds = [a.get("type") for a in raw["states"]["home"]["on_match"]]
            assert "remember_episode" in kinds, f"{name}: {kinds}"

    def test_login_recovery_restores_it_before_leaving(self):
        for name, raw in self._farm_configs().items():
            acts = raw["states"]["recover_pick"]["on_match"]
            kinds = [a.get("type") for a in acts]
            assert "restore_episode" in kinds, f"{name}: {kinds}"
            assert kinds.index("restore_episode") < kinds.index("goto"), (
                f"{name}: restores after leaving the state: {kinds}")

    def test_actions_are_registered(self):
        for kind in ("remember_episode", "restore_episode"):
            assert kind in cfgmod._ACTION_TYPES
            assert cfgmod._REQUIRED_FIELDS.get(kind) == set()


class TestRequireForegroundAction:
    """The check that answers what no template can: is this the game at all?"""

    class _Restarter:
        def __init__(self): self.calls = 0
        def restart(self): self.calls += 1

    class _Dev:
        serial = "fake"
        def __init__(self, out): self.out = out
        def shell(self, *a, **k): return self.out

    GAME = "com.devsisters.crg"
    STORE = "com.android.ld.appstore"

    def _run(self, dumpsys, *, dry_run=False, wired=True):
        r = self._Restarter()
        a = Actor(self._Dev(dumpsys), TemplateStore("templates/cookierun"),
                  dry_run=dry_run, default_threshold=0.82)
        a.restarter = r if wired else None
        a.require_foreground()
        return r.calls

    def test_no_restart_while_the_game_owns_the_screen(self):
        """A watchdog fire is usually a game screen that recovers on its own —
        one of the two seen on 2026-08-19 did. This must not restart those."""
        focus = f"  mCurrentFocus=Window{{a u0 {self.GAME}/com.unity3d.player.UnityPlayerActivity}}"
        assert self._run(focus) == 0

    def test_restarts_when_another_app_is_in_front(self):
        focus = f"  mCurrentFocus=Window{{b u0 {self.STORE}/.app.activity.MainActivity}}"
        assert self._run(focus) == 1

    def test_restarts_when_the_foreground_cannot_be_read(self):
        """Unknown is treated as "not the game": the alternative is jumping into
        whatever is there until a second watchdog fire, which is what happened."""
        assert self._run("  mCurrentFocus=null") == 1

    def test_the_package_must_be_the_focused_one_not_merely_mentioned(self):
        out = chr(10).join([
            f"  someOtherLine={self.GAME} appears here",
            f"  mCurrentFocus=Window{{c u0 {self.STORE}/.Main}}",
        ])
        assert self._run(out) == 1

    def test_dry_run_never_restarts(self):
        focus = f"  mCurrentFocus=Window{{b u0 {self.STORE}/.Main}}"
        assert self._run(focus, dry_run=True) == 0

    def test_without_a_restarter_it_warns_instead_of_crashing(self):
        assert self._run("anything", wired=False) == 0


class TestSendLifeExitsToHome:
    """Live 09:02-09:05 on 2026-08-19: sendlife.json ended on scroll_retry_5's
    bare `stop`, which leaves the Friends panel over home. The caller switches
    Episodes next, and switch_episode taps the Episode button at (1280,175)
    straight into that panel: Episode 1 finished, all six switches failed with
    "Episode Map did not open", the restore failed too, and the farm loop ran
    against an Episode nobody chose until the watchdog fired at 1100s."""

    def _cfg(self):
        return json.loads(
            (CONFIG_DIR / "sendlife.json").read_text(encoding="utf-8"))

    def test_no_exit_stops_without_reaching_home(self):
        """Every `stop` must sit in a state that has just seen home_marker —
        otherwise the errand can hand back any screen at all."""
        st = self._cfg()["states"]
        for name, spec in st.items():
            for branch in ("on_match", "on_absent"):
                acts = spec.get(branch)
                acts = [acts] if isinstance(acts, dict) else (acts or [])
                if not any(a.get("type") == "stop" for a in acts):
                    continue
                if branch == "on_match":
                    # home_play_marker, not home_marker: the latter has
                    # "Episode 1" cropped into it and so only sees home on
                    # Episode 1 (0.431 vs 1.000 on an Episode-2 home frame,
                    # measured 2026-08-20).
                    assert spec.get("detect") == "home/home_play_marker.png", (
                        f"{name}.{branch} stops on a screen that is not home: "
                        f"detect={spec.get('detect')}")
                else:
                    # An on_absent stop is the give-up path; it may only appear
                    # at the end of the bounded BACK chain.
                    assert name.startswith("exit_to_home"), (
                        f"{name}.on_absent stops without ever looking for home")

    def test_exit_chain_is_bounded_and_terminates(self):
        """BACK on home itself raises the game's own "Exit the game?" dialog, so
        the chain must not press it forever."""
        st = self._cfg()["states"]
        seen, node = [], "exit_to_home"
        while node and node not in seen:
            seen.append(node)
            nxt = [a.get("state") for a in st[node]["on_absent"]
                   if a.get("type") == "goto"]
            node = nxt[0] if nxt else None
        assert node is None, f"exit chain loops back into {node}: {seen}"
        # Three BACK presses, then the Exit-dialog dismissal, then one last look:
        # what matters is the number of PRESSES, not the chain's length.
        presses = [n for n in seen
                   if any(a.get("type") == "key" for a in st[n]["on_absent"])]
        assert len(presses) <= 3, f"exit chain presses BACK {len(presses)}x: {presses}"
        assert len(seen) <= 5, f"exit chain is {len(seen)} states: {seen}"
        last = st[seen[-1]]["on_absent"]
        assert any(a.get("type") == "stop" for a in last), (
            f"{seen[-1]} neither continues nor stops")

    def test_scroll_exhaustion_routes_into_the_exit(self):
        st = self._cfg()["states"]
        gotos = [a.get("state") for a in st["scroll_retry_5"]["on_absent"]
                 if a.get("type") == "goto"]
        assert gotos == ["exit_to_home"], st["scroll_retry_5"]["on_absent"]

    def test_exit_states_press_back(self):
        """Each BACK step presses BACK. exit_to_home_verify is the exception on
        purpose: it is the look AFTER the last press, and a fourth BACK is what
        raises the game's own "Exit the game?" dialog."""
        st = self._cfg()["states"]
        pressers = [k for k in st
                    if k.startswith("exit_to_home") and k != "exit_to_home_verify"]
        assert len(pressers) == 3, pressers
        for name in pressers:
            keys = [a for a in st[name]["on_absent"] if a.get("type") == "key"]
            assert keys and keys[0].get("code") == 4, f"{name}: {st[name]['on_absent']}"

    def test_the_last_step_looks_before_handing_control_back(self):
        """The old tail pressed BACK and stopped on the result unchecked, so a
        chain that never found home handed an unknown screen to switch_episode —
        the Episodes 3-7 failures of 2026-08-20."""
        st = self._cfg()["states"]
        tail = st["exit_to_home_verify"]
        assert tail["detect"] == "home/home_play_marker.png", tail
        third = st["exit_to_home_3"]["on_absent"]
        assert [a.get("type") for a in third][-1] == "goto", (
            f"exit_to_home_3 still stops on its own BACK unchecked: {third}")
        # It hands off to the Exit-dialog dismissal first: BACK on home is what
        # raises that dialog, so the last press is the likeliest to have created
        # it. The dismissal then reaches the final look either way.
        nxt = third[-1]["state"]
        assert nxt == "exit_dismiss_exitgame", third
        for branch in ("on_match", "on_absent"):
            acts = st[nxt][branch]
            acts = [acts] if isinstance(acts, dict) else acts
            gotos = [a["state"] for a in acts if a.get("type") == "goto"]
            assert gotos == ["exit_to_home_verify"], (branch, acts)


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


class TestLivesBadgeDecidesTheSendLifePass:
    """Measured 2026-08-20 on one live Lives-tab frame: home envelope badge 55,
    Lives tab badge 53, Rewards tab badge 4. The home badge totals the tabs, so
    only the tab's own badge answers "how much mail is waiting". read_counter got
    53 off that frame at three different offsets and paddings, and 4 off the
    Rewards badge only once padded — cropped flush it read 47, picking up the
    neighbour, which is why the offset carries 4px of padding on every side.

    A count that cannot be read must not become a number: the expensive branch is
    a Send-Life pass over 7 Episodes, so an unread badge takes the cheap branch.
    """

    class _Store:
        dir = Path("templates/cookierun/mailbox")
        def get(self, name): return None

    def _actor(self, reads):
        a = Actor(object(), self._Store(), default_threshold=0.85)
        import src.mailbox as mbmod
        orig = mbmod.read_lives_waiting
        seq = list(reads)
        def fake(*_a, **_k):
            v = seq.pop(0)
            if isinstance(v, Exception):
                raise v
            return v
        mbmod.read_lives_waiting = fake
        return a, mbmod, orig

    def _read(self, value):
        a, mbmod, orig = self._actor([value])
        try:
            a.remember_lives_waiting()
            return a.lives_waiting
        finally:
            mbmod.read_lives_waiting = orig

    def test_a_readable_badge_is_remembered(self):
        assert self._read(53) == 53

    def test_an_unreadable_badge_stays_none(self):
        assert self._read(None) is None

    def test_a_raising_read_does_not_escape(self):
        """This runs inside the sweep; a perception failure must not abort the
        drain, only leave the count unknown."""
        assert self._read(RuntimeError("no tesseract")) is None

    def test_a_fresh_read_replaces_a_stale_one(self):
        a, mbmod, orig = self._actor([53, 4])
        try:
            a.remember_lives_waiting()
            a.remember_lives_waiting()
            assert a.lives_waiting == 4
        finally:
            mbmod.read_lives_waiting = orig

    def test_a_failed_read_clears_the_previous_count(self):
        """Opposite of remember_episode, deliberately: a stale Episode is still
        the right Episode to restore, but a stale mail count belongs to a list
        that has already been drained, so keeping it would decide the next pass
        off the last one's number."""
        a, mbmod, orig = self._actor([53, None])
        try:
            a.remember_lives_waiting()
            a.remember_lives_waiting()
            assert a.lives_waiting is None
        finally:
            mbmod.read_lives_waiting = orig

    def test_the_reader_uses_the_lives_tab_not_the_home_badge(self):
        """Guards the measurement above: anchoring on anything but the Lives tab
        marker reads a different quantity."""
        from src import mailbox
        assert mailbox.LIVES_TAB_MARKER == "lives_tab_marker.png"
        dx, dy, w, h = mailbox.LIVES_BADGE_OFFSET
        # The badge sits on the tab's top-right corner: right of the marker's
        # left edge, and above its top (the pill overhangs the tab).
        assert dx > 0 and dy < 0, mailbox.LIVES_BADGE_OFFSET
        assert w >= 55 and h >= 40, (
            "the flush crop that misread the Rewards badge was 55x40; the box "
            "must be padded beyond it")

    def test_zero_and_absurd_reads_are_refused(self):
        """The tab drops the badge entirely at zero, so a 0 is a misread, and a
        count far past any friend list is OCR noise."""
        from src import mailbox
        assert mailbox.LIVES_MAX >= 100
        called = {}
        def fake_counter(frame, region):
            return called.setdefault("n", 0)
        import src.mailbox as mbmod
        orig_find, orig_grab, orig_rc = mbmod.find_named, mbmod.grab, mbmod.read_counter_voted
        mbmod.grab = lambda dev: None
        mbmod.find_named = lambda *a, **k: Match(found=True, score=1.0, x=900, y=215, w=200, h=100)
        try:
            for bad in (0, mailbox.LIVES_MAX + 1):
                mbmod.read_counter_voted = lambda frame, region, _b=bad: _b
                assert mbmod.read_lives_waiting(object(), self._Store()) is None, bad
            mbmod.read_counter_voted = lambda frame, region: 53
            assert mbmod.read_lives_waiting(object(), self._Store()) == 53
        finally:
            mbmod.find_named, mbmod.grab, mbmod.read_counter_voted = orig_find, orig_grab, orig_rc

    def test_an_unreadable_badge_keeps_the_frame(self, tmp_path):
        """Live 2026-08-20 00:28: the sweep logged "no readable Lives badge" while
        53 were waiting a minute earlier, and replaying that saved frame through
        this same reader got 53 — so the frame the sweep actually saw was
        different, and it was gone. An empty list and a failed read are the same
        None, so the frame is what separates them next time."""
        import src.mailbox as mbmod
        orig_find, orig_grab, orig_rc = mbmod.find_named, mbmod.grab, mbmod.read_counter_voted
        mbmod.grab = lambda dev: np.zeros((300, 1200, 3), dtype=np.uint8)
        mbmod.find_named = lambda *a, **k: Match(found=True, score=1.0, x=900, y=215, w=200, h=100)
        mbmod.read_counter_voted = lambda frame, region: None
        try:
            got = mbmod.read_lives_waiting(object(), self._Store(),
                                           keep_unreadable_in=str(tmp_path))
            assert got is None
            kept = list(tmp_path.glob("lives_badge_*.png"))
            assert len(kept) == 1, kept
        finally:
            mbmod.find_named, mbmod.grab, mbmod.read_counter_voted = orig_find, orig_grab, orig_rc

    def test_a_readable_badge_keeps_nothing(self, tmp_path):
        """The diagnostic must not fill the directory on the normal path."""
        import src.mailbox as mbmod
        orig_find, orig_grab, orig_rc = mbmod.find_named, mbmod.grab, mbmod.read_counter_voted
        mbmod.grab = lambda dev: np.zeros((300, 1200, 3), dtype=np.uint8)
        mbmod.find_named = lambda *a, **k: Match(found=True, score=1.0, x=900, y=215, w=200, h=100)
        mbmod.read_counter_voted = lambda frame, region: 53
        try:
            assert mbmod.read_lives_waiting(object(), self._Store(),
                                            keep_unreadable_in=str(tmp_path)) == 53
            assert not list(tmp_path.glob("*.png"))
        finally:
            mbmod.find_named, mbmod.grab, mbmod.read_counter_voted = orig_find, orig_grab, orig_rc

    def test_the_diagnostic_cannot_break_the_sweep(self, tmp_path):
        """It runs mid-drain; a broken save must not take the run down with it."""
        import src.mailbox as mbmod
        orig_find, orig_grab, orig_rc = mbmod.find_named, mbmod.grab, mbmod.read_counter_voted
        mbmod.grab = lambda dev: np.zeros((300, 1200, 3), dtype=np.uint8)
        mbmod.find_named = lambda *a, **k: Match(found=True, score=1.0, x=900, y=215, w=200, h=100)
        mbmod.read_counter_voted = lambda frame, region: None
        try:
            # cv2.imwrite cannot write here: the parent is an existing FILE,
            # so mkdir raises rather than the write failing quietly.
            blocker = tmp_path / "not_a_dir"
            blocker.write_text("x")
            assert mbmod.read_lives_waiting(object(), self._Store(),
                                            keep_unreadable_in=str(blocker / "sub")) is None
        finally:
            mbmod.find_named, mbmod.grab, mbmod.read_counter_voted = orig_find, orig_grab, orig_rc

    def test_an_absent_tab_reads_nothing(self):
        import src.mailbox as mbmod
        orig_find, orig_grab = mbmod.find_named, mbmod.grab
        mbmod.grab = lambda dev: None
        mbmod.find_named = lambda *a, **k: Match(found=False, score=0.1, x=0, y=0, w=0, h=0)
        try:
            assert mbmod.read_lives_waiting(object(), self._Store()) is None
        finally:
            mbmod.find_named, mbmod.grab = orig_find, orig_grab


class TestMailboxDrainsTheWholeList:
    """User request 2026-08-20: "sendlife_mailbox ต้องทำให้หมด ทำจนจดหมายหมด".

    The 30-confirm cap this replaces existed for a real reason and its cost was
    measured: live 00:24-00:33 on 2026-08-19 the cap fired and went straight to
    `done`, leaving item 31's "Send X a free Life?" dialog open. `done` looks for
    alldone_marker (0.474 on that frame — absent), so it fell to close_mailbox,
    whose X at (1692,135) the dialog covers; close_popup warned twice and `stop`
    handed control back with the dialog still up. The farm loop matches nothing on
    that screen (sendlife_marker 0.598, under the 0.82 threshold), so it walked
    its guard chain looking healthy for 601s until the progress watchdog fired.
    Stopping mid-list is what created that frame; running to the end reaches
    `done` on the game's own "All Lives received and sent!" popup instead.

    The cap's second job — telling the parent gate a long list from a short one —
    moved to remember_lives_waiting reading the Lives tab badge before the drain.
    """

    def _sweep(self):
        return json.loads(
            (CONFIG_DIR / "sendlife_mailbox.json").read_text(encoding="utf-8"))

    def test_the_sweep_has_no_confirm_cap(self):
        cl = self._sweep()["states"]["confirm_loop"]
        assert "max_visits" not in cl and "max_visits_goto" not in cl, (
            "a cap stops the sweep with mail still waiting, which is exactly "
            "what the user asked to stop doing")

    def test_the_cap_only_exit_is_gone_with_it(self):
        """cap_close_dialog existed solely to clean up after the cap. Left behind
        with nothing jumping to it, it reads as an orphan state."""
        assert "cap_close_dialog" not in self._sweep()["states"]

    def test_the_drain_still_has_a_stop(self):
        """The user chose the existing timeout over a high safety cap, so those
        stops have to actually be there: a wall clock on the state and the
        config-level no-progress watchdog."""
        raw = self._sweep()
        cl = raw["states"]["confirm_loop"]
        assert cl["timeout_ms"] >= 20_000, cl["timeout_ms"]
        assert raw["no_progress_s"] > 0 and raw["no_progress_goto"] in raw["states"]
        assert "confirm_loop" in raw["progress_states"], (
            "each confirm has to count as progress or the watchdog fires "
            "mid-drain on a long list")

    def test_running_out_exits_through_done(self):
        """Absent dialog means the list is finished, and `done` is what closes the
        game's own end-of-list popup — the path a full drain now always takes."""
        cl = self._sweep()["states"]["confirm_loop"]
        assert cl["on_absent"] == {"goto": "done"}, cl["on_absent"]
        assert cl.get("absent_retries", 0) >= 3, (
            "the dialog re-opens in ~500-700ms between friends; without retries "
            "that gap reads as an empty list")


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
        assert branch == [{"type": "remember_lives_waiting"},
                          {"type": "goto", "state": "confirm_loop"}], branch

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


class TestHomeIsDetectedEpisodeIndependently:
    """Live 2026-08-20, three cycles in a row (04:32, 06:40, 07:56): Send-Life
    ran on Episodes 1 and 2, then every switch to 3-7 failed with "Episode Map
    did not open" and the restore of the original Episode failed too — so the
    farm loop was left on whatever Episode the last attempt touched, and only
    2 of 7 Episodes ever got Lives.

    Root cause is the marker, not the taps: home/home_marker.png is cropped with
    the words "Episode 1" inside it, so it only matches while Episode 1 is
    selected. Scored against a real home frame with Episode 2 up, it gets 0.431
    (absent) while home/home_play_marker.png — the Play! button alone — gets
    1.000. sendlife's exit_to_home chain waits for home using the episode-bound
    one: on Episode 1 it matched and stopped cleanly (0 BACK presses, switch
    then worked first tap), on Episode 2 it never matched, pressed BACK three
    times, and exit_to_home_3 stops without re-checking — leaving some other
    screen up for switch_episode to tap the Episode button on.

    The farm configs already moved to the Play! marker (coinrun.json's note says
    why the Episode-banner one "silently broke"); these errands were missed.
    """

    PATHS = [Path("config/cookierun") / n for n in
             ("sendlife.json", "addfriend.json", "giftdraw.json")]

    def test_no_state_waits_for_home_with_an_episode_bound_marker(self):
        # Only USES count. The _note fields deliberately still name the old
        # marker to explain what was wrong with it — scanning the whole state
        # blob flagged every state this fix already corrected.
        def uses(state):
            det = state.get("detect")
            if det == "home/home_marker.png":
                return True
            if isinstance(det, list) and "home/home_marker.png" in det:
                return True
            for branch in ("on_match", "on_absent", "on_match_timeout"):
                acts = state.get(branch)
                acts = [acts] if isinstance(acts, dict) else (acts or [])
                for a in acts:
                    if isinstance(a, dict) and "home/home_marker.png" in (
                            a.get("verify"), a.get("template")):
                        return True
            return False

        offenders = []
        for path in self.PATHS:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for name, state in raw["states"].items():
                if uses(state):
                    offenders.append(f"{path.name}:{name}")
        assert not offenders, (
            "home/home_marker.png has 'Episode 1' cropped into it, so these "
            f"states only see home on Episode 1: {offenders}")

    def test_the_exit_chain_ends_by_confirming_home(self):
        """exit_to_home_3 used to press BACK and stop without looking, so a
        chain that never found home handed control back anyway — the caller then
        tapped the Episode button on an unknown screen. Its note claimed the
        caller re-reads the Episode first; _run_errand_per_episode only reads it
        once, before the loop."""
        raw = json.loads((Path("config/cookierun") / "sendlife.json")
                         .read_text(encoding="utf-8"))
        states = raw["states"]
        kinds = [a.get("type") for a in states["exit_to_home_3"]["on_absent"]]
        assert kinds[-1] == "goto", (
            f"the last BACK press stops without ever confirming home: {kinds}")
        assert "exit_dismiss_exitgame" in states, (
            "the chain must clear the Exit dialog its own BACK presses raise")
        assert states["exit_to_home_verify"]["detect"] == "home/home_play_marker.png"


class TestExitGameDialogIsRuledOut:
    """Caught live 2026-08-20 09:13:55 by snapping the failure instead of
    reasoning about it. The screen when "Episode Map did not open" fires is home
    with the game's own "Exit the game?" dialog centred over it — Cancel/Confirm
    — because sendlife's exit chain presses BACK three times: the first closes
    the Friends panel and reaches home, the next two land ON home, and BACK on
    home raises that dialog (exit_to_home's own note says so).

    The trap is that home/home_play_marker.png scores 1.000 through it: Play!
    sits bottom-right, the dialog is centred, nothing overlaps. Measured that
    day — dialog frame: exitgame 1.000, home_play 1.000; clean Episode-2 home:
    exitgame 0.399, home_play 1.000. So switch_episode's "wait for home" guard
    passes and it taps the Episode button into a modal, three attempts, then
    reports the map as the thing that failed.

    An earlier theory blamed the episode-bound home_marker.png crop. That marker
    IS wrong for this (0.431 on Episode-2 home) and is fixed alongside, but it is
    not what defeats the switch: the probe showed home_play at 1.000 on the very
    frame that failed, so the switch would have gone ahead either way.
    """

    MARKER = "home/exitgame_marker.png"

    def test_the_marker_exists(self):
        assert (Path("templates/cookierun") / self.MARKER).exists(), (
            "cropped from the live failure frame — 'Exit the game?' text only, "
            "no buttons, so it stays valid if the buttons move")

    def test_the_exit_chain_dismisses_it(self):
        """The chain that CREATES the dialog has to be the one that clears it:
        every BACK press after the panel closes risks raising it."""
        raw = json.loads((Path("config/cookierun") / "sendlife.json")
                         .read_text(encoding="utf-8"))
        st = raw["states"]
        handlers = [n for n, s in st.items()
                    if self.MARKER in json.dumps(s, ensure_ascii=False)]
        assert handlers, (
            "nothing in sendlife.json looks for the dialog its own BACK presses "
            f"raise: {sorted(st)}")

    def test_dismissal_taps_cancel_never_confirm(self):
        """Confirm closes the GAME. Measured button centres on the failure frame:
        Cancel (724,687), Confirm (1188,687)."""
        raw = json.loads((Path("config/cookierun") / "sendlife.json")
                         .read_text(encoding="utf-8"))
        for name, spec in raw["states"].items():
            blob = json.dumps(spec, ensure_ascii=False)
            if self.MARKER not in blob:
                continue
            acts = spec.get("on_match")
            acts = [acts] if isinstance(acts, dict) else (acts or [])
            for a in acts:
                x, y = a.get("x"), a.get("y")
                if x is None or y is None:
                    continue
                assert not (abs(x - 1188) < 120 and abs(y - 687) < 60), (
                    f"{name} taps ({x},{y}) — that is Confirm, which exits the game")


class TestUnknownScreenClosesFast:
    """Live 2026-08-21: a screen with no marker at all (a new "Friendly Run"
    submenu, two popups deep) stalled the bot for the full no_progress_s window
    before the watchdog even started recovering — recover_unknown_probe only
    walks screens this config already has a marker for, so an unrecognised one
    is invisible to every step of it until recover_unknown_restart's expensive
    app cycle.

    Android BACK dismisses most dialogs without needing to know what they are —
    key() says so already, and the sendlife exit chain has relied on exactly
    this for a while. So the recovery path spends a few fast BACK presses,
    checking for home after each one, BEFORE the probe walk that requires
    recognising the screen. A screen that closes on BACK recovers in seconds
    instead of the full probe walk plus restart.
    """

    def _configs_with_recovery(self):
        out = {}
        for path in sorted(CONFIG_DIR.glob("*.json")):
            raw = json.loads(path.read_text(encoding="utf-8"))
            if "recover_unknown" in raw.get("states", {}):
                out[path.stem] = raw
        return out

    def _farm_configs(self):
        """Configs with a full probe walk (recover_unknown_probe exists).
        Errand configs (sendlife/addfriend/giftdraw) go straight from
        recover_unknown to the backspam chain — there is no probe walk to
        stand in front of."""
        return {n: r for n, r in self._configs_with_recovery().items()
               if "recover_unknown_probe" in r["states"]}

    def _errand_configs(self):
        return {n: r for n, r in self._configs_with_recovery().items()
               if "recover_unknown_probe" not in r["states"]}

    def test_farm_configs_try_back_before_the_probe_walk(self):
        for name, raw in self._farm_configs().items():
            st = raw["states"]
            acts = st["recover_unknown_probe"]["on_absent"]
            acts = [acts] if isinstance(acts, dict) else acts
            gotos = [a.get("state") for a in acts if a.get("type") == "goto"]
            assert gotos and gotos[0].startswith("recover_unknown_backspam") or (
                gotos == ["recover_unknown_pick"]
                and "recover_unknown_backspam_1" in raw["states"]["recover_unknown_pick"]
                   .get("on_absent", {}).get("goto", "")
            ), (f"{name}: recover_unknown_probe.on_absent must reach the "
                f"backspam chain before the probe walk resumes, got {gotos}")

    def test_errand_configs_try_back_before_restart(self):
        for name, raw in self._errand_configs().items():
            st = raw["states"]
            acts = st["recover_unknown"]["on_absent"]
            acts = [acts] if isinstance(acts, dict) else acts
            gotos = [a.get("state") for a in acts if a.get("type") == "goto"]
            assert gotos == ["recover_unknown_backspam_1"], (
                f"{name}: recover_unknown.on_absent must try backspam before "
                f"restart_app, got {gotos}")

    def test_backspam_checks_home_after_every_press(self):
        """Not a blind burst: a screen that closes on the first BACK must not
        eat two more presses (which could re-open something, or hit the game's
        own Exit-the-game confirm on a THIRD press while sitting on home)."""
        for name, raw in self._configs_with_recovery().items():
            st = raw["states"]
            chain = [n for n in st if n.startswith("recover_unknown_backspam")]
            assert len(chain) >= 2, f"{name}: only one backspam step: {chain}"
            resume = raw["start_state"]
            for n in chain:
                assert st[n]["detect"] == "home/home_play_marker.png", (
                    f"{name}:{n} must detect home before pressing again")
                on_match = st[n]["on_match"]
                on_match = [on_match] if isinstance(on_match, dict) else on_match
                assert any(a.get("type") == "goto" and a.get("state") == resume
                           for a in on_match), (
                    f"{name}:{n}.on_match must rejoin ({resume}) immediately, "
                    f"not press BACK again")

    def test_backspam_is_bounded_and_falls_back_to_the_probe_walk(self):
        """BACK on home itself raises the game's own Exit confirm — the same
        trap exit_to_home_3 already guards against — so this chain must stop
        pressing well before that, and hand off to the known-popup probe walk
        rather than looping or stopping silently."""
        for name, raw in self._configs_with_recovery().items():
            st = raw["states"]
            chain = sorted(n for n in st if n.startswith("recover_unknown_backspam"))
            assert len(chain) <= 3, f"{name}: too many BACK presses: {chain}"
            last = st[chain[-1]]
            on_absent = last["on_absent"]
            on_absent = [on_absent] if isinstance(on_absent, dict) else on_absent
            gotos = [a.get("state") for a in on_absent if a.get("type") == "goto"]
            expect = "probe_sdkfail" if "recover_unknown_probe" in st else "recover_unknown_restart"
            assert gotos == [expect], (
                f"{name}: {chain[-1]} must fall through to {expect} on "
                f"exhaustion, got {gotos}")

    def test_every_backspam_state_presses_key_4(self):
        for name, raw in self._configs_with_recovery().items():
            st = raw["states"]
            for n in sorted(k for k in st if k.startswith("recover_unknown_backspam")):
                acts = st[n]["on_absent"]
                acts = [acts] if isinstance(acts, dict) else acts
                keys = [a for a in acts if a.get("type") == "key"]
                assert keys and keys[0].get("code") == 4, f"{name}:{n}: {acts}"
