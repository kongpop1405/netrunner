"""Template matching on synthetic frames."""
import numpy as np
import pytest

from src.perceive import Match, PerceiveError, find, ground_present


def _frame(h=200, w=300):
    rng = np.random.default_rng(42)
    return rng.integers(0, 255, (h, w, 3), dtype=np.uint8)


def test_find_pasted_template():
    frame = _frame()
    template = frame[50:90, 100:160].copy()  # 60x40 crop
    m = find(frame, template, 0.9)
    assert m.found
    assert m.score > 0.99
    assert m.x == 100 + 60 // 2
    assert m.y == 50 + 40 // 2


def test_find_absent_template():
    frame = _frame()
    rng = np.random.default_rng(7)  # different noise, no correlation
    template = rng.integers(0, 255, (40, 60, 3), dtype=np.uint8)
    m = find(frame, template, 0.9)
    assert not m.found
    assert m.score < 0.9


def test_uniform_template_rejected():
    frame = _frame()
    flat = np.full((40, 60, 3), 128, dtype=np.uint8)
    with pytest.raises(PerceiveError, match="uniform"):
        find(frame, flat, 0.8)


def test_template_larger_than_frame_rejected():
    frame = _frame(h=50, w=50)
    big = _frame(h=100, w=100)
    with pytest.raises(PerceiveError, match="larger than frame"):
        find(frame, big, 0.8)


def test_match_is_frozen_dataclass():
    m = Match(found=True, score=0.9, x=1, y=2, w=3, h=4)
    with pytest.raises(AttributeError):
        m.score = 0.5


def _flat_frame(h=1080, w=1920, value=80):
    return np.full((h, w, 3), value, dtype=np.uint8)


def test_ground_present_true_when_hard_edge_in_band():
    frame = _flat_frame()
    # a sharp horizontal edge at y=885 (background above, ground below)
    frame[885:, :] = 220
    assert ground_present(frame, y=885, x_range=(1150, 1500))


def test_ground_present_false_over_flat_background():
    frame = _flat_frame()  # uniform — no vertical gradient anywhere
    assert not ground_present(frame, y=885, x_range=(1150, 1500))


def test_ground_present_checks_only_the_given_x_range():
    frame = _flat_frame()
    frame[885:, 0:50] = 220  # edge exists, but outside the probe window
    assert not ground_present(frame, y=885, x_range=(1150, 1500))


def test_ground_present_respects_edge_min_threshold():
    frame = _flat_frame()
    frame[885:, 1150:1500] = 90  # weak edge: value 80 -> 90
    assert not ground_present(frame, y=885, x_range=(1150, 1500), edge_min=100)
    assert ground_present(frame, y=885, x_range=(1150, 1500), edge_min=5)


def test_ground_present_handles_y_near_frame_top():
    frame = _flat_frame()
    frame[5:, :] = 220
    # y=0 with band=13 would want rows -13..13; must clamp, not raise
    assert ground_present(frame, y=0, x_range=(100, 200))
