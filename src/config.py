"""Config loading + validation for a farm FSM."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

_ACTION_TYPES = {"tap_template", "tap_xy", "swipe", "wait", "goto", "stop", "key", "jump"}
_REQUIRED_FIELDS = {
    "tap_template": {"template"},
    "tap_xy": {"x", "y"},
    "swipe": {"x1", "y1", "x2", "y2"},
    "wait": {"ms"},
    "goto": {"state"},
    "stop": set(),
    "key": {"code"},
    "jump": {"cx", "cy"},
}


class ConfigError(RuntimeError):
    pass


@dataclass
class Config:
    device: str | None
    templates_dir: str
    poll_ms: int
    match_threshold: float
    start_state: str
    states: dict[str, dict]
    path: Path = field(default_factory=Path)


def load(path: str | Path) -> Config:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {p}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {p}: {e}") from e

    cfg = Config(
        device=raw.get("device"),
        templates_dir=raw.get("templates_dir", f"templates/{p.stem}"),
        poll_ms=int(raw.get("poll_ms", 800)),
        match_threshold=float(raw.get("match_threshold", 0.85)),
        start_state=raw.get("start_state", ""),
        states=raw.get("states", {}),
        path=p,
    )
    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    if not cfg.states:
        raise ConfigError("config has no states")
    if cfg.start_state not in cfg.states:
        raise ConfigError(
            f"start_state '{cfg.start_state}' is not a defined state "
            f"(have: {', '.join(cfg.states)})"
        )
    names = set(cfg.states)
    for sname, state in cfg.states.items():
        actions = list(state.get("on_match", []))
        absent = state.get("on_absent")
        if isinstance(absent, dict) and "goto" in absent:
            actions.append({"type": "goto", "state": absent["goto"]})
        elif isinstance(absent, list):
            actions.extend(absent)
        for a in actions:
            _validate_action(sname, a, names)


def _validate_action(state: str, action: dict, state_names: set[str]) -> None:
    kind = action.get("type")
    if kind not in _ACTION_TYPES:
        raise ConfigError(f"state '{state}': unknown action type {kind!r}")
    missing = _REQUIRED_FIELDS[kind] - action.keys()
    if missing:
        raise ConfigError(
            f"state '{state}': action '{kind}' missing field(s): {', '.join(sorted(missing))}"
        )
    if kind == "goto" and action["state"] not in state_names:
        raise ConfigError(
            f"state '{state}': goto targets undefined state '{action['state']}'"
        )
