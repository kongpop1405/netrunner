"""Rewrite inline tap ladders in bot configs as the shared action types.

    python tools/migrate_action_types.py                    # show the diff, write nothing
    python tools/migrate_action_types.py --write            # apply to every config
    python tools/migrate_action_types.py --write config/cookierun/boxrun_toggle.json

Three patterns are recognised, each collapsing hand-written JSON into one action
whose behaviour lives in src/act.py (see "shared game actions" there):

  tap_xy(985,515) + wait, repeated        -> {"type": "faststart_tap"}
  tap_xy(960,540)                         -> {"type": "relay_tap"}
  tap_xy(x,y) + wait, before a goto       -> {"type": "close_popup", ...}

The point is propagation: once a config names the action, a tuning fix in
act.py reaches it without anyone editing JSON again.

Only the first two patterns are enabled by default. close_popup rewriting is
opt-in (--close-popups) because "tap something, then wait" is the shape of many
actions that are not popup closes — buy-cell taps, menu navigation, the Play
button — and the script cannot tell them apart from coordinates alone.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.act import Actor

#: Coordinates identifying each ladder, read from the Actor so the script and
#: the runtime can never disagree about what "the relay button" means.
FASTSTART_XY = Actor.faststart_xy
RELAY_XY = Actor.relay_xy

#: A faststart ladder shorter than this is more likely a coincidence than the
#: real spam block (which is written as 12-14 pairs in every config using it).
MIN_FASTSTART_RUN = 3


def _is_tap(action: dict, xy: tuple[int, int]) -> bool:
    return (action.get("type") == "tap_xy"
            and (action.get("x"), action.get("y")) == xy)


def _collapse_faststart(actions: list[dict]) -> tuple[list[dict], int]:
    """Replace runs of tap_xy(faststart)+wait pairs with one faststart_tap."""
    out: list[dict] = []
    i = 0
    collapsed = 0
    while i < len(actions):
        run_taps = 0
        gap_ms = None
        j = i
        while j < len(actions) and _is_tap(actions[j], FASTSTART_XY):
            run_taps += 1
            j += 1
            if j < len(actions) and actions[j].get("type") == "wait":
                if gap_ms is None:
                    gap_ms = actions[j].get("ms")
                j += 1

        if run_taps >= MIN_FASTSTART_RUN:
            action = {"type": "faststart_tap", "taps": run_taps}
            if gap_ms is not None:
                action["gap_ms"] = gap_ms
            out.append(action)
            collapsed += 1
            i = j
            continue

        out.append(actions[i])
        i += 1
    return out, collapsed


def _swap_relay(actions: list[dict]) -> tuple[list[dict], int]:
    out = []
    swapped = 0
    for action in actions:
        if _is_tap(action, RELAY_XY):
            out.append({"type": "relay_tap"})
            swapped += 1
        else:
            out.append(action)
    return out, swapped


def _swap_close_popups(actions: list[dict]) -> tuple[list[dict], int]:
    """Fold `tap_xy + wait + goto` into close_popup + goto.

    Deliberately narrow: only a tap immediately followed by a wait and then a
    goto — the exact shape of every probe state's dismiss. A tap followed by
    another tap (a multi-step buy flow) is left alone.
    """
    out: list[dict] = []
    i = 0
    swapped = 0
    while i < len(actions):
        a = actions[i]
        is_close = (
            a.get("type") == "tap_xy"
            and i + 2 < len(actions)
            and actions[i + 1].get("type") == "wait"
            and actions[i + 2].get("type") == "goto"
            and not _is_tap(a, FASTSTART_XY)
            and not _is_tap(a, RELAY_XY)
        )
        if is_close:
            out.append({
                "type": "close_popup",
                "x": a["x"], "y": a["y"],
                "settle_ms": actions[i + 1]["ms"],
            })
            swapped += 1
            i += 2  # the goto is re-visited on the next iteration
            continue
        out.append(a)
        i += 1
    return out, swapped


def _walk_action_lists(states: dict, fn) -> int:
    """Apply `fn` to every action list in every state. Returns total changes."""
    total = 0
    for state in states.values():
        for key in ("on_match", "on_absent"):
            block = state.get(key)
            if isinstance(block, list):
                new, n = fn(block)
                if n:
                    state[key] = new
                    total += n
            elif isinstance(block, dict) and key == "on_match":
                # per-template branches: {template: [actions]}
                for tname, branch in block.items():
                    if isinstance(branch, list):
                        new, n = fn(branch)
                        if n:
                            block[tname] = new
                            total += n
    return total


def migrate(path: Path, *, close_popups: bool) -> tuple[str, dict[str, int]]:
    raw = path.read_text(encoding="utf-8")
    cfg = json.loads(raw)
    states = cfg.get("states", {})

    counts = {
        "faststart_tap": _walk_action_lists(states, _collapse_faststart),
        "relay_tap": _walk_action_lists(states, _swap_relay),
    }
    if close_popups:
        counts["close_popup"] = _walk_action_lists(states, _swap_close_popups)

    out = json.dumps(cfg, indent=2, ensure_ascii=False) + "\n"
    return out, counts


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("configs", nargs="*", type=Path,
                    help="config files (default: every config/*/*.json)")
    ap.add_argument("--write", action="store_true",
                    help="write the files (default: report only)")
    ap.add_argument("--close-popups", action="store_true",
                    help="also rewrite tap+wait+goto as close_popup (review the "
                         "diff carefully — see the module docstring)")
    args = ap.parse_args(argv)

    paths = args.configs or sorted(Path("config").glob("*/*.json"))
    if not paths:
        print("no configs found", file=sys.stderr)
        return 2

    touched = 0
    for path in paths:
        out, counts = migrate(path, close_popups=args.close_popups)
        changed = {k: v for k, v in counts.items() if v}
        if not changed:
            continue
        touched += 1
        summary = ", ".join(f"{v}x {k}" for k, v in changed.items())
        if args.write:
            path.write_text(out, encoding="utf-8")
            print(f"[written] {path}: {summary}")
        else:
            before = len(path.read_text(encoding="utf-8").splitlines())
            after = len(out.splitlines())
            print(f"[dry-run] {path}: {summary}  ({before} -> {after} lines)")

    if not args.write and touched:
        print(f"\n{touched} file(s) would change. Re-run with --write to apply.")
    elif not touched:
        print("nothing to migrate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
