"""Config loading + validation for a farm FSM."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

_ACTION_TYPES = {
    "tap_template", "tap_xy", "swipe", "wait", "goto", "stop", "key", "jump",
    "slide", "text",
    # shared game actions — behaviour lives in Actor so a fix reaches every
    # config naming the action (see src/act.py "shared game actions").
    "relay_tap", "faststart_tap", "close_popup",
}
_REQUIRED_FIELDS = {
    "tap_template": {"template"},
    "tap_xy": {"x", "y"},
    "swipe": {"x1", "y1", "x2", "y2"},
    "wait": {"ms"},
    "goto": {"state"},
    "stop": set(),
    "key": {"code"},
    "jump": {"cx", "cy"},
    "slide": {"cx", "cy"},
    "text": {"value"},
    # coords/counts default to the Actor's live-verified values
    "relay_tap": set(),
    "faststart_tap": set(),
    "close_popup": {"x", "y"},
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


def detect_names(state: dict) -> list[str]:
    """Normalize a state's `detect` (filename or list of filenames) to a list."""
    detect = state.get("detect")
    if isinstance(detect, str):
        return [detect]
    if isinstance(detect, list):
        return detect
    return []


def _validate(cfg: Config) -> None:
    if not cfg.states:
        raise ConfigError("config has no states")
    if cfg.start_state not in cfg.states:
        raise ConfigError(
            f"start_state '{cfg.start_state}' is not a defined state "
            f"(have: {', '.join(cfg.states)})"
        )
    tdir = Path(cfg.templates_dir)
    if not tdir.is_dir():
        raise ConfigError(f"templates_dir does not exist: {tdir}")
    names = set(cfg.states)
    for sname, state in cfg.states.items():
        _validate_state(sname, state, names, tdir)


def _validate_state(sname: str, state: dict, names: set[str], tdir: Path) -> None:
    detect = state.get("detect")
    dnames = detect_names(state)
    if not dnames or not all(isinstance(d, str) for d in dnames):
        raise ConfigError(
            f"state '{sname}': 'detect' must be a template filename "
            f"or a non-empty list of filenames"
        )
    for t in dnames:
        _require_template(sname, tdir, t)

    thr = state.get("threshold")
    if thr is not None and not (isinstance(thr, (int, float)) and 0 < float(thr) <= 1):
        raise ConfigError(f"state '{sname}': 'threshold' must be a number in (0, 1]")

    retries = state.get("absent_retries", 0)
    if not isinstance(retries, int) or isinstance(retries, bool) or retries < 0:
        raise ConfigError(f"state '{sname}': 'absent_retries' must be a non-negative integer")
    wait_ms = state.get("absent_wait_ms")
    if wait_ms is not None and (not isinstance(wait_ms, int) or wait_ms <= 0):
        raise ConfigError(f"state '{sname}': 'absent_wait_ms' must be a positive integer (ms)")

    actions: list[dict] = []
    om = state.get("on_match", [])
    if isinstance(om, dict):
        # per-template branches: every detect entry must have its action list
        if not isinstance(detect, list):
            raise ConfigError(
                f"state '{sname}': dict-form on_match requires 'detect' to be a list"
            )
        if set(om) != set(dnames):
            raise ConfigError(
                f"state '{sname}': dict-form on_match keys must match the detect list "
                f"exactly (detect: {sorted(dnames)}, on_match: {sorted(om)})"
            )
        for branch in om.values():
            actions.extend(branch)
    else:
        actions.extend(om)

    absent = state.get("on_absent")
    absent_goto = None
    if isinstance(absent, dict) and "goto" in absent:
        absent_goto = absent["goto"]
        actions.append({"type": "goto", "state": absent_goto})
    elif isinstance(absent, list):
        actions.extend(absent)
        absent_goto = next(
            (a.get("state") for a in absent if a.get("type") == "goto"), None
        )

    # timeout + on_absent goto pointing at the state itself = guaranteed FsmError
    # once the timeout fires (there is no escape target) — reject at load time.
    if state.get("timeout_ms") is not None and absent_goto == sname:
        raise ConfigError(
            f"state '{sname}': on_absent goto targets itself while timeout_ms is set — "
            f"when the timeout fires there is no escape target and the engine crashes "
            f"with FsmError; point the goto at a different state, use absent_retries, "
            f"or drop timeout_ms"
        )

    for a in actions:
        _validate_action(sname, a, names, tdir)


def _require_template(state: str, tdir: Path, name: str) -> None:
    if not (tdir / name).is_file():
        raise ConfigError(f"state '{state}': template not found: {tdir / name}")


def _validate_action(state: str, action: dict, state_names: set[str], tdir: Path) -> None:
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
    if kind == "tap_template":
        _require_template(state, tdir, action["template"])
    if kind == "close_popup" and action.get("verify") is not None:
        _require_template(state, tdir, action["verify"])
    if kind == "text":
        _validate_text_value(state, action["value"])


#: `adb shell input text` only carries printable ASCII, and the string still
#: passes through a shell — anything outside this set either arrives mangled or
#: gets eaten as a metacharacter. Space is allowed here and encoded as %s later.
_TEXT_ALLOWED = re.compile(r"^[A-Za-z0-9 _.\-]+$")


def _validate_text_value(state: str, value: object) -> None:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"state '{state}': action 'text' needs a non-empty string 'value'")
    if not _TEXT_ALLOWED.match(value):
        raise ConfigError(
            f"state '{state}': action 'text' value {value!r} has characters ADB "
            f"'input text' cannot send — use letters, digits, space, and _ . - only"
        )
