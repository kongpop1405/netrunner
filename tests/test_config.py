"""Config loading + validation."""
import json

import pytest

from src import config as cfgmod


def _write(tmp_path, data):
    p = tmp_path / "farm.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def _minimal(**overrides):
    base = {
        "start_state": "a",
        "states": {
            "a": {"detect": "m.png", "on_match": [{"type": "stop"}]},
        },
    }
    base.update(overrides)
    return base


def test_valid_config_loads(tmp_path):
    cfg = cfgmod.load(_write(tmp_path, _minimal()))
    assert cfg.start_state == "a"
    assert "a" in cfg.states


def test_defaults_applied(tmp_path):
    cfg = cfgmod.load(_write(tmp_path, _minimal()))
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


def test_undefined_start_state(tmp_path):
    with pytest.raises(cfgmod.ConfigError, match="start_state"):
        cfgmod.load(_write(tmp_path, _minimal(start_state="ghost")))


def test_unknown_action_type(tmp_path):
    data = _minimal()
    data["states"]["a"]["on_match"] = [{"type": "teleport"}]
    with pytest.raises(cfgmod.ConfigError, match="unknown action type"):
        cfgmod.load(_write(tmp_path, data))


def test_action_missing_fields(tmp_path):
    data = _minimal()
    data["states"]["a"]["on_match"] = [{"type": "tap_xy", "x": 1}]  # no y
    with pytest.raises(cfgmod.ConfigError, match="missing field"):
        cfgmod.load(_write(tmp_path, data))


def test_goto_undefined_state(tmp_path):
    data = _minimal()
    data["states"]["a"]["on_match"] = [{"type": "goto", "state": "ghost"}]
    with pytest.raises(cfgmod.ConfigError, match="undefined state"):
        cfgmod.load(_write(tmp_path, data))


def test_on_absent_goto_validated(tmp_path):
    data = _minimal()
    data["states"]["a"]["on_absent"] = {"goto": "ghost"}
    with pytest.raises(cfgmod.ConfigError, match="undefined state"):
        cfgmod.load(_write(tmp_path, data))


def test_jump_and_key_actions_validate(tmp_path):
    data = _minimal()
    data["states"]["a"]["on_match"] = [
        {"type": "jump", "cx": 238, "cy": 940},
        {"type": "key", "code": 4},
        {"type": "stop"},
    ]
    cfgmod.load(_write(tmp_path, data))  # should not raise
