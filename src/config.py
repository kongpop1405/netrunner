"""Config loading + validation for a farm FSM."""
from __future__ import annotations

import json
import logging
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("netrunner.config")

_ACTION_TYPES = {
    "tap_template", "tap_xy", "swipe", "wait", "goto", "stop", "key", "jump",
    "slide", "text",
    # shared game actions — behaviour lives in Actor so a fix reaches every
    # config naming the action (see src/act.py "shared game actions").
    "relay_tap", "faststart_tap", "close_popup", "restart_app", "solve_cards",
    "run_config",
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
    "restart_app": set(),
    "solve_cards": {"cells", "cell_size", "bail_goto"},
    "run_config": {"config"},
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
    #: (min, max) ms when `poll_ms` was given as a range — a fixed poll makes the
    #: in-run hop cadence a metronome, which is exactly the signature a human
    #: player does not have. None = the single `poll_ms` value, unchanged.
    poll_ms_range: tuple[int, int] | None = None
    #: (min, max) seconds to idle before starting another game.
    inter_game_delay_s: tuple[float, float] | None = None
    #: state whose entry counts as "one game finished" (default: start_state).
    inter_game_state: str | None = None
    #: (min, max) seconds of farming before the app is restarted. None = never.
    session_reset_s: tuple[float, float] | None = None
    #: state the restart is allowed to happen in — restarting mid-run would
    #: forfeit the run and its heart (default: inter_game_state, else start_state).
    reset_at_state: str | None = None
    #: android package to force-stop/relaunch on reset.
    package: str | None = None
    #: side errands the farm loop detours into on a timer — sending lives to
    #: friends, say. A bot that farms for twelve hours and never touches the
    #: social screens is as distinctive as one that never pauses.
    periodic_routines: tuple[dict, ...] = ()
    #: states whose arrival proves the loop is getting somewhere (a run ended, a
    #: box was banked, home came back). Reaching any of them resets the
    #: no-progress timer.
    progress_states: frozenset[str] = frozenset()
    #: where to jump when `no_progress_s` elapses without touching a progress
    #: state — a recovery state that assumes the screen is unrecognised. None
    #: disables the watchdog (default), so existing configs behave unchanged.
    no_progress_goto: str | None = None
    #: seconds of no progress before `no_progress_goto` fires.
    no_progress_s: float = 300.0
    #: where to go on the SECOND consecutive fire — the first recovery having
    #: failed to produce any progress. None repeats `no_progress_goto` forever.
    no_progress_escalate_goto: str | None = None

    def poll_delay_s(self) -> float:
        """Seconds to sleep for one poll — jittered when a range was configured."""
        if self.poll_ms_range is not None:
            return random.uniform(*self.poll_ms_range) / 1000
        return self.poll_ms / 1000


def parse_range(value: object, label: str, *, integer: bool) -> tuple:
    """Read a `[min, max]` pair. Raises ConfigError on anything else.

    Ranges are how every pacing knob is expressed (poll, inter-game delay,
    wait): a single number keeps the old fixed behaviour, a pair asks for a
    fresh random draw each time it is used.
    """
    if not (isinstance(value, (list, tuple)) and len(value) == 2):
        raise ConfigError(f"'{label}' must be a [min, max] pair")
    lo, hi = value
    if isinstance(lo, bool) or isinstance(hi, bool):
        raise ConfigError(f"'{label}' bounds must be numbers")
    want = int if integer else (int, float)
    if not (isinstance(lo, want) and isinstance(hi, want)):
        kind = "integers" if integer else "numbers"
        raise ConfigError(f"'{label}' bounds must be {kind}")
    if lo <= 0 or hi <= 0:
        raise ConfigError(f"'{label}' bounds must be positive")
    if lo > hi:
        raise ConfigError(f"'{label}' min ({lo}) is greater than max ({hi})")
    return (lo, hi)


def _parse_routines(raw: object) -> tuple[dict, ...]:
    """Normalize `periodic_routines`. State names are checked in _validate,
    once the state table is known."""
    if not isinstance(raw, list):
        raise ConfigError("'periodic_routines' must be a list")
    out = []
    for i, r in enumerate(raw):
        if not isinstance(r, dict):
            raise ConfigError(f"periodic_routines[{i}] must be an object")
        name = r.get("name") or f"routine{i}"
        if not isinstance(r.get("goto"), str):
            raise ConfigError(f"routine '{name}' needs a 'goto' state name")
        out.append({
            "name": name,
            "interval_s": parse_range(
                r.get("interval_s"), f"routine '{name}': interval_s", integer=False),
            "goto": r["goto"],
            "at_state": r.get("at_state"),
            "after_reset": bool(r.get("after_reset", False)),
        })
    return tuple(out)


def load(path: str | Path) -> Config:
    p = Path(path)
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"config not found: {p}") from e
    except json.JSONDecodeError as e:
        raise ConfigError(f"invalid JSON in {p}: {e}") from e

    poll = raw.get("poll_ms", 800)
    poll_range = None
    if isinstance(poll, (list, tuple)):
        poll_range = parse_range(poll, "poll_ms", integer=True)
        poll = poll_range[0]  # keep the int field meaningful for anything reading it

    igd = raw.get("inter_game_delay_s")
    if igd is not None:
        igd = parse_range(igd, "inter_game_delay_s", integer=False)

    srs = raw.get("session_reset_s")
    if srs is not None:
        srs = parse_range(srs, "session_reset_s", integer=False)

    cfg = Config(
        device=raw.get("device"),
        templates_dir=raw.get("templates_dir", f"templates/{p.stem}"),
        poll_ms=int(poll),
        match_threshold=float(raw.get("match_threshold", 0.85)),
        start_state=raw.get("start_state", ""),
        states=raw.get("states", {}),
        path=p,
        poll_ms_range=poll_range,
        inter_game_delay_s=igd,
        inter_game_state=raw.get("inter_game_state"),
        session_reset_s=srs,
        reset_at_state=raw.get("reset_at_state"),
        package=raw.get("package"),
        periodic_routines=_parse_routines(raw.get("periodic_routines", [])),
        progress_states=frozenset(raw.get("progress_states", [])),
        no_progress_goto=raw.get("no_progress_goto"),
        no_progress_s=float(raw.get("no_progress_s", 300)),
        no_progress_escalate_goto=raw.get("no_progress_escalate_goto"),
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
    if cfg.inter_game_state is not None and cfg.inter_game_state not in cfg.states:
        raise ConfigError(
            f"inter_game_state '{cfg.inter_game_state}' is not a defined state"
        )
    if cfg.inter_game_state is not None and cfg.inter_game_delay_s is None:
        raise ConfigError("inter_game_state set without inter_game_delay_s")
    if cfg.reset_at_state is not None and cfg.reset_at_state not in cfg.states:
        raise ConfigError(f"reset_at_state '{cfg.reset_at_state}' is not a defined state")
    if cfg.reset_at_state is not None and cfg.session_reset_s is None:
        raise ConfigError("reset_at_state set without session_reset_s")
    for r in cfg.periodic_routines:
        if r["goto"] not in cfg.states:
            raise ConfigError(
                f"routine '{r['name']}': goto targets undefined state '{r['goto']}'")
        if r["at_state"] is not None and r["at_state"] not in cfg.states:
            raise ConfigError(
                f"routine '{r['name']}': at_state '{r['at_state']}' is not a defined state")
    unknown_progress = sorted(cfg.progress_states - set(cfg.states))
    if unknown_progress:
        raise ConfigError(
            f"progress_states names undefined state(s): {', '.join(unknown_progress)}")
    if cfg.no_progress_goto is not None and cfg.no_progress_goto not in cfg.states:
        raise ConfigError(
            f"no_progress_goto '{cfg.no_progress_goto}' is not a defined state")
    if cfg.no_progress_goto is not None and not cfg.progress_states:
        raise ConfigError("no_progress_goto set without progress_states — the "
                          "watchdog would fire on a perfectly healthy loop")
    if cfg.no_progress_s <= 0:
        raise ConfigError("no_progress_s must be positive (seconds)")
    esc = cfg.no_progress_escalate_goto
    if esc is not None and esc not in cfg.states:
        raise ConfigError(f"no_progress_escalate_goto '{esc}' is not a defined state")
    if esc is not None and cfg.no_progress_goto is None:
        raise ConfigError("no_progress_escalate_goto set without no_progress_goto")
    names = set(cfg.states)
    for sname, state in cfg.states.items():
        _validate_state(sname, state, names, tdir)
    # The watchdog reaches its recovery state without any goto edge pointing at
    # it, so it is a reachability root like a routine's goto.
    orphans = unreachable_states(
        cfg.states, cfg.start_state,
        extra_roots=[r["goto"] for r in cfg.periodic_routines]
        + [s for s in (cfg.no_progress_goto, cfg.no_progress_escalate_goto) if s])
    if orphans:
        # Warn, don't raise: an orphan may be parked on purpose (an experiment,
        # a state kept for reference) — but silent orphans have also hidden a
        # broken chain (ep3's whole boost-buy chain was unreachable for weeks).
        log.warning(
            "%s: %d state(s) unreachable from start_state '%s': %s",
            cfg.path.name or "config", len(orphans), cfg.start_state,
            ", ".join(orphans),
        )


def goto_targets(state: dict) -> set[str]:
    """Every state name this state can transition to (on_match + on_absent)."""
    outs: set[str] = set()
    lists: list[list[dict]] = []
    om = state.get("on_match", [])
    lists.extend(om.values()) if isinstance(om, dict) else lists.append(om)
    oa = state.get("on_absent")
    if isinstance(oa, dict) and "goto" in oa:
        outs.add(oa["goto"])
    elif isinstance(oa, list):
        lists.append(oa)
    omt = state.get("on_match_timeout")
    if isinstance(omt, dict) and "goto" in omt:
        outs.add(omt["goto"])
    for actions in lists:
        for a in actions:
            if a.get("type") == "goto":
                outs.add(a.get("state"))
    return outs


def unreachable_states(states: dict[str, dict], start_state: str,
                       extra_roots: list[str] | None = None) -> list[str]:
    """States with no goto path from start_state (BFS over goto_targets).

    `extra_roots` are states the engine can jump to without a goto — a periodic
    routine's entry point, for instance. Without them a routine's whole chain
    looks orphaned and the real orphans get lost in the noise.
    """
    seen: set[str] = set()
    stack = [start_state] if start_state in states else []
    stack += [r for r in (extra_roots or []) if r in states]
    while stack:
        s = stack.pop()
        if s in seen:
            continue
        seen.add(s)
        stack.extend(t for t in goto_targets(states[s]) if t in states)
    return sorted(set(states) - seen)


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

    mt = state.get("match_timeout_ms")
    if mt is not None and (not isinstance(mt, int) or isinstance(mt, bool) or mt <= 0):
        raise ConfigError(f"state '{sname}': 'match_timeout_ms' must be a positive integer (ms)")
    omt = state.get("on_match_timeout")
    if omt is not None:
        if not (isinstance(omt, dict) and isinstance(omt.get("goto"), str)):
            raise ConfigError(
                f"state '{sname}': 'on_match_timeout' must be {{\"goto\": \"<state>\"}}"
            )
        actions.append({"type": "goto", "state": omt["goto"]})
        if mt is None:
            raise ConfigError(
                f"state '{sname}': 'on_match_timeout' set without 'match_timeout_ms'"
            )
    if mt is not None:
        # Same trap as timeout_ms below: the escape target (on_match_timeout,
        # else the on_absent goto) must exist and not point back at the state.
        escape = omt["goto"] if omt else absent_goto
        if escape == sname:
            raise ConfigError(
                f"state '{sname}': match_timeout_ms escape goto targets itself — "
                f"when the timeout fires there is no way out"
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


def _validate_roi(state: str, roi) -> None:
    """A tap_template roi must be four non-negative ints (x, y, w, h).

    Caught here rather than at runtime: a malformed roi slices the frame to
    something empty or wrong, and perceive would either raise mid-run or,
    worse, match inside a region nobody intended.
    """
    if roi is None:
        return
    if not isinstance(roi, (list, tuple)) or len(roi) != 4:
        raise ConfigError(
            f"state '{state}': tap_template roi must be [x, y, w, h], got {roi!r}"
        )
    if not all(isinstance(v, int) and not isinstance(v, bool) for v in roi):
        raise ConfigError(
            f"state '{state}': tap_template roi values must be integers, got {roi!r}"
        )
    x, y, w, h = roi
    if x < 0 or y < 0 or w <= 0 or h <= 0:
        raise ConfigError(
            f"state '{state}': tap_template roi needs x,y >= 0 and w,h > 0, got {roi!r}"
        )


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
        _validate_roi(state, action.get("roi"))
    if kind == "close_popup" and action.get("verify") is not None:
        _require_template(state, tdir, action["verify"])
    if kind == "solve_cards":
        _validate_solve_cards(state, action, state_names)
    if kind == "wait" and isinstance(action["ms"], (list, tuple)):
        parse_range(action["ms"], f"state '{state}': wait.ms", integer=True)
    if kind == "text":
        _validate_text_value(state, action["value"])
    if kind == "run_config" and not Path(action["config"]).is_file():
        raise ConfigError(
            f"state '{state}': run_config target not found: {action['config']}")


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


def _validate_solve_cards(state: str, action: dict, state_names: set[str]) -> None:
    """A card puzzle answered from bad geometry is worse than one not answered:
    wrong taps risk the account. So the coordinates and the bail route are
    checked at load time, not discovered mid-challenge.
    """
    cells = action["cells"]
    if not (isinstance(cells, list) and len(cells) >= 3):
        raise ConfigError(
            f"state '{state}': solve_cards 'cells' needs at least 3 [x, y] points")
    for i, c in enumerate(cells):
        if not (isinstance(c, (list, tuple)) and len(c) == 2
                and all(isinstance(v, int) and not isinstance(v, bool) and v >= 0
                        for v in c)):
            raise ConfigError(
                f"state '{state}': solve_cards cells[{i}] must be [x, y] integers")
    size = action["cell_size"]
    if not (isinstance(size, (list, tuple)) and len(size) == 2
            and all(isinstance(v, int) and v > 0 for v in size)):
        raise ConfigError(
            f"state '{state}': solve_cards 'cell_size' must be [w, h] positive integers")

    pick = action.get("pick", 2)
    if not isinstance(pick, int) or isinstance(pick, bool) or not 1 <= pick < len(cells):
        raise ConfigError(
            f"state '{state}': solve_cards 'pick' must be between 1 and "
            f"{len(cells) - 1} (it has to leave a majority to compare against)")

    gap = action.get("gap_min", 0.04)
    if not isinstance(gap, (int, float)) or isinstance(gap, bool) or not 0 < gap < 1:
        raise ConfigError(
            f"state '{state}': solve_cards 'gap_min' must be a number in (0, 1) — "
            f"it is the confidence margin below which nothing is tapped")

    if action["bail_goto"] not in state_names:
        raise ConfigError(
            f"state '{state}': solve_cards 'bail_goto' targets undefined state "
            f"'{action['bail_goto']}' — that is where the loop goes when the cards "
            f"cannot be read, so it must exist")

    confirm = action.get("confirm_xy")
    if confirm is not None and not (isinstance(confirm, (list, tuple))
                                    and len(confirm) == 2
                                    and all(isinstance(v, int) for v in confirm)):
        raise ConfigError(
            f"state '{state}': solve_cards 'confirm_xy' must be [x, y] integers")
