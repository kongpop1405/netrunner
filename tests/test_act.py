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


# --- shared game actions ------------------------------------------------------


@pytest.fixture
def fast_actor(actor):
    """Actor with humanization delays zeroed so tap counts are what's measured."""
    actor.delay_range = (0, 0)
    actor.hesitate_chance = 0
    actor.relay_gap_s = 0
    actor.faststart_gap_ms = 0
    actor.popup_settle_ms = 0
    return actor


def test_relay_tap_defaults_to_verified_centre(fast_actor):
    fast_actor.run({"type": "relay_tap"}, FRAME)
    (call,) = fast_actor.device.calls
    assert call[:2] == ("input", "tap")
    assert abs(int(call[2]) - 960) <= fast_actor.spatial_clip
    assert abs(int(call[3]) - 540) <= fast_actor.spatial_clip


def test_relay_taps_knob_repeats_the_tap(fast_actor):
    """The single knob that fixes 'the relay sometimes doesn't fire' everywhere."""
    fast_actor.relay_taps = 3
    fast_actor.run({"type": "relay_tap"}, FRAME)
    assert len(fast_actor.device.calls) == 3


def test_relay_tap_accepts_coord_override(fast_actor):
    fast_actor.run({"type": "relay_tap", "x": 100, "y": 200}, FRAME)
    (call,) = fast_actor.device.calls
    assert abs(int(call[2]) - 100) <= fast_actor.spatial_clip
    assert abs(int(call[3]) - 200) <= fast_actor.spatial_clip


def test_faststart_tap_replaces_the_inline_ladder(fast_actor):
    """One action must produce the same taps the 24-entry JSON ladder did."""
    fast_actor.run({"type": "faststart_tap", "taps": 12}, FRAME)
    assert len(fast_actor.device.calls) == 12
    for call in fast_actor.device.calls:
        assert call[:2] == ("input", "tap")
        assert abs(int(call[2]) - 985) <= fast_actor.spatial_clip
        assert abs(int(call[3]) - 515) <= fast_actor.spatial_clip


def test_faststart_taps_default_is_tunable_in_one_place(fast_actor):
    fast_actor.faststart_taps = 5
    fast_actor.run({"type": "faststart_tap"}, FRAME)
    assert len(fast_actor.device.calls) == 5


def test_close_popup_without_verify_taps_once(fast_actor):
    fast_actor.run({"type": "close_popup", "x": 727, "y": 688}, FRAME)
    (call,) = fast_actor.device.calls
    assert abs(int(call[2]) - 727) <= fast_actor.spatial_clip
    assert abs(int(call[3]) - 688) <= fast_actor.spatial_clip


def test_close_popup_retries_while_marker_still_on_screen(tdir, frame, monkeypatch):
    """The 'close didn't take' fix: a tap that lands mid-fade is repeated."""
    from src import act as act_mod

    a = Actor(FakeDevice(), TemplateStore(tdir))
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    a.popup_settle_ms = 0
    monkeypatch.setattr(act_mod, "grab", lambda device: frame)  # marker still there

    a.run({"type": "close_popup", "x": 10, "y": 20, "verify": "marker.png",
           "retries": 2}, frame)
    assert len(a.device.calls) == 3  # initial + 2 retries, marker never cleared


def test_close_popup_stops_once_marker_is_gone(tdir, frame, monkeypatch):
    from src import act as act_mod

    a = Actor(FakeDevice(), TemplateStore(tdir))
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    a.popup_settle_ms = 0
    blank = np.zeros_like(frame)
    monkeypatch.setattr(act_mod, "grab", lambda device: blank)  # marker cleared

    a.run({"type": "close_popup", "x": 10, "y": 20, "verify": "marker.png",
           "retries": 2}, frame)
    assert len(a.device.calls) == 1


def test_close_popup_survives_a_failed_verification(tdir, frame, monkeypatch):
    """A broken re-read must not turn a working close into a crash."""
    from src import act as act_mod

    def boom(device):
        raise act_mod.CaptureError("screencap died")

    a = Actor(FakeDevice(), TemplateStore(tdir))
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    a.popup_settle_ms = 0
    monkeypatch.setattr(act_mod, "grab", boom)

    a.run({"type": "close_popup", "x": 10, "y": 20, "verify": "marker.png"}, frame)
    assert len(a.device.calls) == 1


def test_shared_actions_send_nothing_in_dry_run(tmp_path):
    a = Actor(FakeDevice(), TemplateStore(tmp_path), dry_run=True)
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    a.relay_gap_s = 0
    a.faststart_gap_ms = 0
    a.popup_settle_ms = 0
    a.run({"type": "relay_tap"}, FRAME)
    a.run({"type": "faststart_tap", "taps": 3}, FRAME)
    a.run({"type": "close_popup", "x": 1, "y": 2}, FRAME)
    assert a.device.calls == []


# --- tap_template roi + optional ------------------------------------------------


def _two_marker_frame(tdir, frame):
    """A frame holding marker.png twice, so a roi is the only way to pick one."""
    import cv2
    tpl = cv2.imread(str(tdir / "marker.png"))
    th, tw = tpl.shape[:2]
    wide = np.zeros((th + 200, tw + 400, 3), dtype=np.uint8)
    wide[10:10 + th, 10:10 + tw] = tpl              # copy A, top-left
    wide[150:150 + th, 300:300 + tw] = tpl          # copy B, lower-right
    return wide


def test_tap_template_roi_selects_the_copy_inside_it(tdir, frame):
    a = Actor(FakeDevice(), TemplateStore(tdir))
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    wide = _two_marker_frame(tdir, frame)

    a.run({"type": "tap_template", "template": "marker.png",
           "roi": [300, 150, 200, 120]}, wide)

    (call,) = a.device.calls
    x, y = int(call[2]), int(call[3])
    assert 300 <= x <= 500 and 150 <= y <= 270, f"tapped ({x},{y}), outside the roi"


def test_tap_template_optional_skips_when_absent(tdir):
    a = Actor(FakeDevice(), TemplateStore(tdir))
    a.delay_range = (0, 0)
    a.hesitate_chance = 0
    blank = np.zeros((100, 100, 3), dtype=np.uint8)

    a.run({"type": "tap_template", "template": "marker.png", "optional": True}, blank)

    assert a.device.calls == []


def test_tap_template_still_raises_when_not_optional(tdir):
    a = Actor(FakeDevice(), TemplateStore(tdir))
    blank = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ActError, match="not on screen"):
        a.run({"type": "tap_template", "template": "marker.png"}, blank)
