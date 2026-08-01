"""Phase 3 — picking a boost by role marker rather than by state name."""
import glob
import json
from pathlib import Path

import pytest

from src import boost
from src import config as cfgmod
from src.config import Config, ConfigError

CONFIG_DIR = Path("config/cookierun")


def _chain_states():
    """A minimal labelled buy chain: probe / buy (2 taps) / picker / gate."""
    return {
        "gate": {"detect": "shop.png", "boost_role": "gate",
                 "boost_skip_goto": "play",
                 "on_match": [{"type": "goto", "state": "probe"}]},
        "probe": {"detect": "old_banner.png", "boost_role": "probe",
                  "on_match": [{"type": "goto", "state": "play"}],
                  "on_absent": {"goto": "buy"}},
        "buy": {"detect": "shop.png", "boost_role": "buy", "on_match": [
            {"type": "tap_xy", "x": 1, "y": 1},
            {"type": "wait", "ms": 100},
            {"type": "tap_xy", "x": 2, "y": 2},
            {"type": "wait", "ms": 100},
            {"type": "goto", "state": "picker"}]},
        "picker": {"detect": "picker.png", "boost_role": "picker", "on_match": [
            {"type": "tap_xy", "x": 9, "y": 9},
            {"type": "goto", "state": "probe"}]},
        "play": {"detect": "play.png", "on_match": [{"type": "stop"}]},
    }


def _cfg(states=None):
    return Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.85,
                  start_state="gate", states=states if states is not None else _chain_states())


def _taps(cfg, name):
    return [(a["x"], a["y"]) for a in cfg.states[name]["on_match"]
            if a.get("type") == "tap_xy"]


class TestApplyBoost:
    def test_rewrites_banner_taps_and_multibuy(self):
        cfg = _cfg()
        boost.apply_boost(cfg, "magnet")
        p = boost.PROFILES["magnet"]
        assert cfg.states["probe"]["detect"] == p["banner"]
        assert _taps(cfg, "buy") == [tuple(t) for t in p["buy_taps"]]
        assert _taps(cfg, "picker") == [p["multibuy"]]

    def test_shorter_profile_drops_the_extra_tap_and_its_wait(self):
        """The speed chain reaches Multi directly — the baseline's first tap and
        the wait that existed to settle it must both go."""
        cfg = _cfg()
        boost.apply_boost(cfg, "speed")
        assert _taps(cfg, "buy") == [tuple(boost.PROFILES["speed"]["buy_taps"][0])]
        waits = [a for a in cfg.states["buy"]["on_match"] if a.get("type") == "wait"]
        assert len(waits) == 1

    def test_none_routes_past_the_chain(self):
        cfg = _cfg()
        boost.apply_boost(cfg, "none")
        gotos = [a["state"] for a in cfg.states["gate"]["on_match"]
                 if a.get("type") == "goto"]
        assert gotos == ["play"]

    def test_none_needs_a_skip_target(self):
        states = _chain_states()
        del states["gate"]["boost_skip_goto"]
        with pytest.raises(ConfigError, match="boost_skip_goto"):
            boost.apply_boost(_cfg(states), "none")

    def test_none_needs_a_gate(self):
        states = _chain_states()
        del states["gate"]["boost_role"]
        with pytest.raises(ConfigError, match="gate"):
            boost.apply_boost(_cfg(states), "none")

    def test_incomplete_profile_says_what_is_missing(self):
        with pytest.raises(ConfigError, match="crop the equipped pill"):
            boost.apply_boost(_cfg(), "goldcoinmagic")

    def test_unknown_boost_lists_the_choices(self):
        with pytest.raises(ConfigError, match="ready: "):
            boost.apply_boost(_cfg(), "nope")

    def test_config_without_a_chain_is_rejected(self):
        states = {"a": {"detect": "a.png", "on_match": [{"type": "stop"}]}}
        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.85,
                     start_state="a", states=states)
        with pytest.raises(ConfigError, match="no boost chain"):
            boost.apply_boost(cfg, "magnet")

    def test_unknown_role_is_rejected(self):
        states = _chain_states()
        states["probe"]["boost_role"] = "prboe"  # typo
        with pytest.raises(ConfigError, match="unknown boost_role"):
            boost.apply_boost(_cfg(states), "magnet")

    def test_multiple_probe_states_all_retargeted(self):
        """probe_magnet and start_run both read the pill; missing one leaves the
        post-roll check watching the previous boost's banner."""
        states = _chain_states()
        states["probe2"] = {"detect": "old_banner.png", "boost_role": "probe",
                            "on_match": [{"type": "goto", "state": "play"}]}
        cfg = _cfg(states)
        boost.apply_boost(cfg, "doublecoins")
        want = boost.PROFILES["doublecoins"]["banner"]
        assert cfg.states["probe"]["detect"] == want
        assert cfg.states["probe2"]["detect"] == want


class TestChoiceReporting:
    def test_ready_only_lists_profiles_with_banners(self):
        assert set(boost.ready()) == {"magnet", "speed", "doublecoins"}
        assert all(boost.PROFILES[k]["banner"] for k in boost.ready())

    def test_eleven_boosts_plus_none(self):
        assert len(boost.PROFILES) == 11
        assert "none" in boost.CHOICES and len(boost.CHOICES) == 12

    def test_describe_names_what_pending_ones_need(self):
        text = boost.describe_choices()
        assert "magnet" in text
        assert "crop" in text and "1920x1080" in text
        assert "Gold Coin Magic" in text


class TestShippedConfigs:
    def test_every_labelled_chain_accepts_every_ready_boost(self):
        checked = 0
        for path in sorted(glob.glob(str(CONFIG_DIR / "*.json"))):
            for choice in boost.ready():
                cfg = cfgmod.load(path)
                if not boost.supports_boost(cfg):
                    continue
                boost.apply_boost(cfg, choice)  # must not raise
                checked += 1
        # at least the boost-carrying configs (magnet, coinrun, toggle) x the
        # 3 ready boosts; exact count shifts as configs are archived, so just
        # require the retarget path was exercised on real configs.
        assert checked >= 6, f"only {checked} labelled chains accepted a boost"

    def test_gates_carry_a_skip_target(self):
        for path in sorted(glob.glob(str(CONFIG_DIR / "*.json"))):
            raw = json.loads(Path(path).read_text(encoding="utf-8"))
            for name, st in raw["states"].items():
                if st.get("boost_role") == "gate":
                    assert st.get("boost_skip_goto"), f"{Path(path).name}:{name}"

    def test_role_markers_do_not_break_validation(self):
        for path in sorted(glob.glob(str(CONFIG_DIR / "*.json"))):
            cfgmod.load(path)  # unknown top-level state keys must be tolerated


class TestNoOrphansShipped:
    """Every config's graph must be whole. This is a regression guard: the boost
    chains in ep3/norelay were unreachable for weeks, so the bot silently played
    with whatever boost happened to be equipped."""

    def test_all_configs_fully_reachable(self):
        from src.config import unreachable_states

        for path in sorted(glob.glob(str(CONFIG_DIR / "*.json"))):
            cfg = cfgmod.load(path)
            # Same roots the loader uses: routines and the progress watchdog's
            # recovery states, which the engine jumps to without a goto edge.
            roots = [r["goto"] for r in cfg.periodic_routines]
            roots += [s for s in (cfg.no_progress_goto,
                                  cfg.no_progress_escalate_goto) if s]
            orphans = unreachable_states(cfg.states, cfg.start_state, extra_roots=roots)
            assert orphans == [], f"{Path(path).name}: {orphans}"

    def test_boost_gates_enter_the_chain_when_one_exists(self):
        """A config carrying a buy chain must actually route into it — gates
        pointing straight at the play state is what orphaned ep3's chain."""
        for path in sorted(glob.glob(str(CONFIG_DIR / "*.json"))):
            cfg = cfgmod.load(path)
            probes = [n for n, st in cfg.states.items()
                      if st.get("boost_role") == "probe" and n.startswith("probe_")]
            gates = [n for n, st in cfg.states.items() if st.get("boost_role") == "gate"]
            if not (probes and gates):
                continue
            for gate in gates:
                targets = [a["state"] for a in cfg.states[gate].get("on_match", [])
                           if a.get("type") == "goto"]
                assert any(t in probes for t in targets), \
                    f"{Path(path).name}:{gate} skips the buy chain ({targets})"


class TestPickerTicks:
    """Multi-Buy re-rolls until any ticked boost lands, so the picker must be
    left holding exactly one tick — the boost that was asked for."""

    def _picker(self, choice):
        cfg = _cfg()
        boost.apply_boost(cfg, choice)
        return cfg.states["picker"]["on_match"]

    def test_every_other_row_is_cleared_and_the_target_set(self):
        actions = self._picker("magnet")
        ticks = [a for a in actions if a.get("type") == "tap_template"]
        assert len(ticks) == len(boost.PICK)

        wanted = [a for a in ticks if a["template"] == boost.UNTICKED_TEMPLATE]
        clears = [a for a in ticks if a["template"] == boost.TICKED_TEMPLATE]
        assert len(wanted) == 1, "exactly one row should be ticked ON"
        assert len(clears) == len(boost.PICK) - 1

        x, y = boost.PICK["magnet"]
        assert wanted[0]["roi"] == boost._roi(x, y)

    def test_rows_are_cleared_before_the_target_is_set(self):
        actions = self._picker("speed")
        kinds = [a["template"] for a in actions if a.get("type") == "tap_template"]
        assert kinds[-1] == boost.UNTICKED_TEMPLATE, \
            "the target must be ticked last, after the clears"

    def test_ticks_run_before_multibuy(self):
        actions = self._picker("doublecoins")
        first_multibuy = next(i for i, a in enumerate(actions)
                              if a.get("type") == "tap_xy")
        last_tick = max(i for i, a in enumerate(actions)
                        if a.get("type") == "tap_template")
        assert last_tick < first_multibuy

    def test_each_roi_covers_only_its_own_row(self):
        """Rows sit 74px apart; an roi reaching a neighbour would let the disc
        match the wrong row and tick something nobody asked for."""
        for name, (x, y) in boost.PICK.items():
            rx, ry, rw, rh = boost._roi(x, y)
            for other, (ox, oy) in boost.PICK.items():
                if other == name:
                    continue
                inside = rx <= ox <= rx + rw and ry <= oy <= ry + rh
                assert not inside, f"{name}'s roi contains {other}"

    def test_taps_are_conditional(self):
        """A blind tap on an already-correct row would toggle it the wrong way."""
        for a in self._picker("magnet"):
            if a.get("type") == "tap_template":
                assert a.get("optional") is True
