"""Phase 4 skeleton — solving the odd-cards-out challenge, or refusing to."""
import json

import numpy as np
import pytest

import src.act as actmod
import src.fsm as fsm
from src import config as cfgmod
from src.act import Actor
from src.perceive import PerceiveError, odd_cells_out

CELL = (60, 60)
#: 3x2 grid, cells 60px wide with the frame comfortably around them
CELLS = [(50, 50), (150, 50), (250, 50), (50, 150), (150, 150), (250, 150)]


def _grid(odd_indices, seed=1, frame_size=(220, 320)):
    """A 6-cell grid where the listed indices carry different content."""
    rng = np.random.default_rng(seed)
    frame = np.full((frame_size[0], frame_size[1], 3), 20, dtype=np.uint8)
    common = rng.integers(0, 255, (CELL[1], CELL[0], 3), dtype=np.uint8)
    for i, (cx, cy) in enumerate(CELLS):
        patch = (rng.integers(0, 255, (CELL[1], CELL[0], 3), dtype=np.uint8)
                 if i in odd_indices else common)
        frame[cy - CELL[1] // 2: cy + CELL[1] // 2,
              cx - CELL[0] // 2: cx + CELL[0] // 2] = patch
    return frame


class TestOddCellsOut:
    def test_finds_the_two_odd_cards(self):
        assert sorted(odd_cells_out(_grid({1, 5}), CELLS, CELL)) == [1, 5]

    @pytest.mark.parametrize("odd", [{0, 3}, {2, 4}, {3, 4}])
    def test_finds_them_wherever_they_sit(self, odd):
        assert sorted(odd_cells_out(_grid(odd), CELLS, CELL)) == sorted(odd)

    def test_all_identical_refuses_to_answer(self):
        """Rank alone always returns two cards. cookierun-classic-bot did exactly
        that, so an unfamiliar challenge produced two confident wrong taps."""
        assert odd_cells_out(_grid(set()), CELLS, CELL) is None

    def test_all_different_refuses_to_answer(self):
        """No majority to compare against — the scores are flat, so there is no
        signal, even though six cards are technically 'all odd'."""
        assert odd_cells_out(_grid({0, 1, 2, 3, 4, 5}), CELLS, CELL) is None

    def test_gap_min_is_what_decides(self):
        frame = _grid({1, 5})
        assert odd_cells_out(frame, CELLS, CELL, gap_min=0.001) is not None
        assert odd_cells_out(frame, CELLS, CELL, gap_min=0.999) is None

    def test_pick_one(self):
        assert odd_cells_out(_grid({4}), CELLS, CELL, pick=1) == [4]

    def test_cell_outside_frame_raises(self):
        """Bad coordinates must be loud: silently comparing clipped crops of
        different sizes would produce a confident wrong answer."""
        with pytest.raises(PerceiveError, match="falls outside"):
            odd_cells_out(_grid({1, 5}), [*CELLS, (9999, 9999)], CELL)

    def test_negative_cell_raises(self):
        with pytest.raises(PerceiveError, match="falls outside"):
            odd_cells_out(_grid({1, 5}), [(5, 5), *CELLS[1:]], CELL)

    def test_pick_must_leave_a_majority(self):
        with pytest.raises(PerceiveError, match="majority"):
            odd_cells_out(_grid({1}), CELLS, CELL, pick=6)

    def test_grayscale_frame_works(self):
        frame = _grid({2, 3})
        gray = frame[:, :, 0]
        assert sorted(odd_cells_out(gray, CELLS, CELL)) == [2, 3]


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
    dev = FakeDevice()
    return Actor(dev, store=object(), dry_run=False)


class TestSolveCardsAction:
    def _action(self, **kw):
        a = {"type": "solve_cards", "cells": CELLS, "cell_size": list(CELL),
             "bail_goto": "captcha_bail", "confirm_xy": [160, 200]}
        a.update(kw)
        return a

    def test_taps_the_odd_cards_then_confirm(self, actor):
        result = actor.run(self._action(), _grid({1, 5}))
        assert result is None
        assert len(actor.device.taps) == 3  # two cards + confirm

    def test_taps_land_inside_their_cards(self, actor):
        actor.run(self._action(confirm_xy=None), _grid({0, 4}))
        for tx, ty in actor.device.taps:
            assert any(abs(tx - cx) <= CELL[0] // 2 and abs(ty - cy) <= CELL[1] // 2
                       for cx, cy in (CELLS[0], CELLS[4]))

    def test_unsure_taps_nothing_at_all(self, actor):
        """Refusing is the cheap mistake; a wrong answer risks the account."""
        result = actor.run(self._action(), _grid(set()))
        assert result == Actor.UNSURE
        assert actor.device.taps == []

    def test_confirm_is_optional(self, actor):
        actor.run(self._action(confirm_xy=None), _grid({2, 3}))
        assert len(actor.device.taps) == 2

    def test_dry_run_sends_nothing(self, monkeypatch):
        monkeypatch.setattr(actmod.time, "sleep", lambda s: None)
        dev = FakeDevice()
        a = Actor(dev, store=object(), dry_run=True)
        assert a.run(self._action(), _grid({1, 5})) is None
        assert dev.taps == []


class TestUnsureRoutesToBail:
    def test_fsm_sends_unsure_to_bail_goto(self, monkeypatch):
        """The action's own bail_goto is where an unreadable puzzle leaves the
        loop — a stop-and-alert state, not a guess."""
        from src.config import Config

        monkeypatch.setattr(fsm, "find_named", lambda f, s, name, t: __import__(
            "src.perceive", fromlist=["Match"]).Match(
            found=True, score=1.0, x=5, y=5, w=2, h=2))
        monkeypatch.setattr(fsm, "grab",
                            lambda d, retries=2: np.zeros((10, 10, 3), dtype=np.uint8))
        monkeypatch.setattr(fsm.time, "sleep", lambda s: None)

        class UnsureActor:
            UNSURE = Actor.UNSURE

            def __init__(self, *a, **kw):
                pass

            def run(self, action, frame):
                return Actor.UNSURE if action["type"] == "solve_cards" else None

        monkeypatch.setattr(fsm, "Actor", UnsureActor)
        states = {
            "captcha": {"detect": "c.png", "on_match": [
                {"type": "solve_cards", "cells": CELLS, "cell_size": list(CELL),
                 "bail_goto": "bail"}]},
            "bail": {"detect": "b.png", "on_match": [{"type": "stop"}]},
        }
        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                     start_state="captcha", states=states)

        class D:
            serial = "fake"

            def shell(self, *a):
                return ""

        # bail stops the run; reaching max_cycles instead would mean it never got there
        fsm.Runner(cfg, D()).run(max_cycles=6)


class TestSolveCardsValidation:
    def _load(self, tmp_path, tdir, action):
        data = {
            "templates_dir": str(tdir),
            "start_state": "a",
            "states": {
                "a": {"detect": "marker.png", "on_match": [action]},
                "bail": {"detect": "marker.png", "on_match": [{"type": "stop"}]},
            },
        }
        p = tmp_path / "farm.json"
        p.write_text(json.dumps(data), encoding="utf-8")
        return cfgmod.load(p)

    def _action(self, **kw):
        a = {"type": "solve_cards", "cells": [[10, 10], [70, 10], [130, 10]],
             "cell_size": [40, 40], "bail_goto": "bail"}
        a.update(kw)
        return a

    def test_valid_action_loads(self, tmp_path, tdir):
        self._load(tmp_path, tdir, self._action())  # must not raise

    def test_bail_goto_must_exist(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="bail_goto"):
            self._load(tmp_path, tdir, self._action(bail_goto="ghost"))

    def test_bail_goto_required(self, tmp_path, tdir):
        a = self._action()
        del a["bail_goto"]
        with pytest.raises(cfgmod.ConfigError, match="missing field"):
            self._load(tmp_path, tdir, a)

    def test_too_few_cells(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="at least 3"):
            self._load(tmp_path, tdir, self._action(cells=[[10, 10], [70, 10]]))

    def test_malformed_cell(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match=r"cells\[1\]"):
            self._load(tmp_path, tdir,
                       self._action(cells=[[10, 10], [70], [130, 10]]))

    def test_negative_cell_rejected(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match=r"cells\[0\]"):
            self._load(tmp_path, tdir,
                       self._action(cells=[[-1, 10], [70, 10], [130, 10]]))

    def test_bad_cell_size(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="cell_size"):
            self._load(tmp_path, tdir, self._action(cell_size=[0, 40]))

    @pytest.mark.parametrize("pick", [0, 3, 9, "two"])
    def test_pick_bounds(self, tmp_path, tdir, pick):
        with pytest.raises(cfgmod.ConfigError, match="pick"):
            self._load(tmp_path, tdir, self._action(pick=pick))

    @pytest.mark.parametrize("gap", [0, 1, 1.5, -0.1, "wide"])
    def test_gap_min_bounds(self, tmp_path, tdir, gap):
        with pytest.raises(cfgmod.ConfigError, match="gap_min"):
            self._load(tmp_path, tdir, self._action(gap_min=gap))

    def test_confirm_xy_shape(self, tmp_path, tdir):
        with pytest.raises(cfgmod.ConfigError, match="confirm_xy"):
            self._load(tmp_path, tdir, self._action(confirm_xy=[10]))
