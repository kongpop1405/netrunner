"""Actor dispatch + humanization bounds. No real device — FakeDevice records."""
import numpy as np
import pytest

from src.act import ActError, Actor
from src.perceive import TemplateStore


class FakeDevice:
    def __init__(self):
        self.calls: list[tuple[str, ...]] = []
        self.serial = "fake"

    def shell(self, *args):
        self.calls.append(args)
        return ""


@pytest.fixture
def actor(tmp_path):
    return Actor(FakeDevice(), TemplateStore(tmp_path))


FRAME = np.zeros((100, 100, 3), dtype=np.uint8)


def test_tap_xy_sends_input_tap(actor):
    actor.delay_range = (0, 0)
    actor.hesitate_chance = 0
    assert actor.run({"type": "tap_xy", "x": 50, "y": 60}, FRAME) is None
    (call,) = actor.device.calls
    assert call[:2] == ("input", "tap")
    # jitter stays within spatial_clip of the target
    assert abs(int(call[2]) - 50) <= actor.spatial_clip
    assert abs(int(call[3]) - 60) <= actor.spatial_clip


def test_dry_run_sends_nothing(tmp_path):
    a = Actor(FakeDevice(), TemplateStore(tmp_path), dry_run=True)
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    a.run({"type": "tap_xy", "x": 1, "y": 2}, FRAME)
    a.run({"type": "key", "code": 4}, FRAME)
    a.run({"type": "jump", "cx": 50, "cy": 50, "rx": 10, "ry": 5}, FRAME)
    assert a.device.calls == []


def test_goto_returns_state(actor):
    assert actor.run({"type": "goto", "state": "next"}, FRAME) == "next"
    assert actor.device.calls == []


def test_stop_returns_sentinel(actor):
    assert actor.run({"type": "stop"}, FRAME) == "__stop__"


def test_key_sends_keyevent(actor):
    actor.run({"type": "key", "code": 4}, FRAME)
    assert actor.device.calls == [("input", "keyevent", "4")]


def test_swipe_sends_input_swipe(actor):
    actor.run({"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "ms": 250}, FRAME)
    assert actor.device.calls == [("input", "swipe", "1", "2", "3", "4", "250")]


def test_unknown_action_raises(actor):
    with pytest.raises(ActError, match="unknown action type"):
        actor.run({"type": "warp"}, FRAME)


def test_jump_taps_inside_zone(actor):
    actor.double_jump_chance = 0  # deterministic single tap
    actor.run({"type": "jump", "cx": 238, "cy": 940, "rx": 175, "ry": 55}, FRAME)
    (call,) = actor.device.calls
    x, y = int(call[2]), int(call[3])
    assert ((x - 238) / 175) ** 2 + ((y - 940) / 55) ** 2 <= 1.0


def test_double_jump_taps_twice(actor):
    actor.double_jump_chance = 1.0
    actor.double_jump_gap = (0, 0)
    actor.run({"type": "jump", "cx": 238, "cy": 940, "rx": 175, "ry": 55}, FRAME)
    assert len(actor.device.calls) == 2


def test_rand_in_zone_always_inside_ellipse(actor):
    for _ in range(200):
        x, y = actor._rand_in_zone(0, 0, 100, 40)
        assert (x / 100) ** 2 + (y / 40) ** 2 <= 1.0 + 1e-9
