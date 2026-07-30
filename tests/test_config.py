"""Config loading + validation."""
import json

import pytest

from src import config as cfgmod


def _write(tmp_path, data):
    p = tmp_path / "farm.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _minimal(tdir, **overrides):
    base = {
        "templates_dir": str(tdir),
        "start_state": "a",
        "states": {
            "a": {"detect": "marker.png", "on_match": [{"type": "stop"}]},
        },
    }
    base.update(overrides)
    return base


def test_valid_config_loads(tmp_path, tdir):
    cfg = cfgmod.load(_write(tmp_path, _minimal(tdir)))
    assert cfg.start_state == "a"
    assert "a" in cfg.states


def test_defaults_applied(tmp_path, tdir):
    cfg = cfgmod.load(_write(tmp_path, _minimal(tdir)))
    assert cfg.poll_ms == 800
    assert cfg.match_threshold == 0.85


def test_missing_config_file(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="not found"):
        cfgmod.load(tmp_path / "nope.json")


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(cfgmod.ConfigError, match="invalid JSON"):
        cfgmod.load(p)


def test_undefined_start_state(tmp_path, tdir):
    with pytest.raises(cfgmod.ConfigError, match="start_state"):
        cfgmod.load(_write(tmp_path, _minimal(tdir, start_state="ghost")))


def test_unknown_action_type(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [{"type": "teleport"}]
    with pytest.raises(cfgmod.ConfigError, match="unknown action type"):
        cfgmod.load(_write(tmp_path, data))


def test_action_missing_fields(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [{"type": "tap_xy", "x": 1}]  # no y
    with pytest.raises(cfgmod.ConfigError, match="missing field"):
        cfgmod.load(_write(tmp_path, data))


def test_goto_undefined_state(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [{"type": "goto", "state": "ghost"}]
    with pytest.raises(cfgmod.ConfigError, match="undefined state"):
        cfgmod.load(_write(tmp_path, data))


def test_on_absent_goto_validated(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_absent"] = {"goto": "ghost"}
    with pytest.raises(cfgmod.ConfigError, match="undefined state"):
        cfgmod.load(_write(tmp_path, data))


def test_jump_and_key_actions_validate(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [
        {"type": "jump", "cx": 238, "cy": 940},
        {"type": "key", "code": 4},
        {"type": "stop"},
    ]
    cfgmod.load(_write(tmp_path, data))  # should not raise


# --- template existence -------------------------------------------------------


def test_missing_templates_dir(tmp_path, tdir):
    data = _minimal(tdir, templates_dir=str(tmp_path / "ghost_dir"))
    with pytest.raises(cfgmod.ConfigError, match="templates_dir does not exist"):
        cfgmod.load(_write(tmp_path, data))


def test_missing_detect_template(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["detect"] = "ghost.png"
    with pytest.raises(cfgmod.ConfigError, match="template not found"):
        cfgmod.load(_write(tmp_path, data))


def test_missing_tap_template_file(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [
        {"type": "tap_template", "template": "ghost.png"},
        {"type": "stop"},
    ]
    with pytest.raises(cfgmod.ConfigError, match="template not found"):
        cfgmod.load(_write(tmp_path, data))


@pytest.mark.parametrize("roi", [
    [1, 2, 3],                  # too few
    [1, 2, 3, 4, 5],            # too many
    "1,2,3,4",                  # not a sequence of ints
    [1, 2, 3.5, 4],             # float
    [-1, 0, 10, 10],            # negative origin
    [0, 0, 0, 10],              # zero width
])
def test_tap_template_roi_must_be_four_positive_ints(tmp_path, tdir, roi):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [
        {"type": "tap_template", "template": "marker.png", "roi": roi},
        {"type": "stop"},
    ]
    with pytest.raises(cfgmod.ConfigError, match="roi"):
        cfgmod.load(_write(tmp_path, data))


def test_tap_template_roi_accepted(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = [
        {"type": "tap_template", "template": "marker.png", "roi": [10, 20, 30, 40]},
        {"type": "stop"},
    ]
    cfg = cfgmod.load(_write(tmp_path, data))
    assert cfg.states["a"]["on_match"][0]["roi"] == [10, 20, 30, 40]


def test_detect_required(tmp_path, tdir):
    data = _minimal(tdir)
    del data["states"]["a"]["detect"]
    with pytest.raises(cfgmod.ConfigError, match="'detect' must be"):
        cfgmod.load(_write(tmp_path, data))


# --- detect any-of + on_match branches ----------------------------------------


def test_detect_list_with_branching_on_match(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"] = {
        "detect": ["marker.png", "other.png"],
        "on_match": {
            "marker.png": [{"type": "stop"}],
            "other.png": [{"type": "tap_xy", "x": 1, "y": 2}],
        },
    }
    cfgmod.load(_write(tmp_path, data))  # should not raise


def test_on_match_dict_keys_must_cover_detect(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"] = {
        "detect": ["marker.png", "other.png"],
        "on_match": {"marker.png": [{"type": "stop"}]},  # other.png branch missing
    }
    with pytest.raises(cfgmod.ConfigError, match="must match the detect list"):
        cfgmod.load(_write(tmp_path, data))


def test_on_match_dict_requires_detect_list(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_match"] = {"marker.png": [{"type": "stop"}]}
    with pytest.raises(cfgmod.ConfigError, match="requires 'detect' to be a list"):
        cfgmod.load(_write(tmp_path, data))


# --- self-goto + timeout trap --------------------------------------------------


def test_self_goto_with_timeout_rejected(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_absent"] = {"goto": "a"}
    data["states"]["a"]["timeout_ms"] = 5000
    with pytest.raises(cfgmod.ConfigError, match="targets itself"):
        cfgmod.load(_write(tmp_path, data))


def test_self_goto_in_action_list_with_timeout_rejected(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_absent"] = [
        {"type": "wait", "ms": 100},
        {"type": "goto", "state": "a"},
    ]
    data["states"]["a"]["timeout_ms"] = 5000
    with pytest.raises(cfgmod.ConfigError, match="targets itself"):
        cfgmod.load(_write(tmp_path, data))


def test_timeout_with_different_goto_ok(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["on_absent"] = {"goto": "b"}
    data["states"]["a"]["timeout_ms"] = 5000
    data["states"]["b"] = {"detect": "marker.png", "on_match": [{"type": "stop"}]}
    cfgmod.load(_write(tmp_path, data))  # pick_box pattern — should not raise


# --- new per-state field bounds -------------------------------------------------


def test_absent_retries_must_be_non_negative_int(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["absent_retries"] = -1
    with pytest.raises(cfgmod.ConfigError, match="absent_retries"):
        cfgmod.load(_write(tmp_path, data))


def test_absent_wait_ms_must_be_positive(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["absent_wait_ms"] = 0
    with pytest.raises(cfgmod.ConfigError, match="absent_wait_ms"):
        cfgmod.load(_write(tmp_path, data))


def test_state_threshold_bounds(tmp_path, tdir):
    data = _minimal(tdir)
    data["states"]["a"]["threshold"] = 1.5
    with pytest.raises(cfgmod.ConfigError, match="threshold"):
        cfgmod.load(_write(tmp_path, data))
