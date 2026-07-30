"""Lint farm FSM configs — the checks that caught real shipped bugs, as a CLI.

    python tools/lint_config.py config/cookierun/*.json
    python tools/lint_config.py --svg docs/graphs config/cookierun/boxrun_ep6.json

Checks per config:
  1. loads + validates (config.load — hard errors: missing template, ghost goto)
  2. unreachable states (BFS from start_state) — ep3 shipped with its whole
     boost-buy chain orphaned and nobody noticed for weeks
  3. `_note` vs `detect` mismatch — a state whose _note names other marker
     PNGs but never its own detect file usually describes a different screen
     than the one it watches (how mb_gate watched inactive_marker while its
     note talked about the Mystery Box)

--svg also writes a BFS-layered transition graph per config, orphans in red.

Exit code: 0 clean · 1 findings · 2 config failed to load.
"""
from __future__ import annotations

import argparse
import html
import logging
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# load() already warns about orphans via logging; the CLI prints its own
# report, so silence the logger to avoid every finding appearing twice.
logging.getLogger("netrunner.config").setLevel(logging.ERROR)

from src import config as cfgmod  # noqa: E402
from src.config import detect_names, goto_targets, unreachable_states  # noqa: E402

_PNG = re.compile(r"[A-Za-z0-9_]+\.png")


#: A note that says the detect is deliberately not the template it discusses —
#: ep6v2 detects boxcount2 while waiting on a boxcount3 crop, for instance — is
#: describing intent, not drifting from it. Suppress the hint when it says so.
_DELIBERATE = ("TEMPORARILY", "DEFERRED", "not captured yet", "NOT captured yet")


def note_detect_mismatches(states: dict[str, dict]) -> list[tuple[str, str, list[str]]]:
    """(state, detect_shown, pngs_in_note) where the note names marker PNGs but
    never the state's own detect file. Heuristic — report as hints, not errors."""
    out = []
    for name, state in states.items():
        note = state.get("_note", "")
        mentioned = set(_PNG.findall(note))
        if not mentioned:
            continue
        if any(k in note for k in _DELIBERATE):
            continue
        dnames = set(detect_names(state))
        if dnames and not (mentioned & dnames):
            out.append((name, ", ".join(sorted(dnames)), sorted(mentioned)))
    return out


def _bfs_levels(states: dict[str, dict], start: str,
                extra_roots: list[str] | None = None) -> list[list[str]]:
    seen: set[str] = set()
    levels: list[list[str]] = []
    frontier = [start] if start in states else []
    frontier += [r for r in (extra_roots or []) if r in states and r != start]
    while frontier:
        levels.append(frontier)
        seen.update(frontier)
        nxt: list[str] = []
        for s in frontier:
            for t in sorted(goto_targets(states[s])):
                if t in states and t not in seen and t not in nxt:
                    nxt.append(t)
        frontier = nxt
    return levels


def write_svg(states: dict[str, dict], start: str, out_path: Path,
              extra_roots: list[str] | None = None) -> None:
    """BFS-layered transition graph. Not pretty — but chain breaks jump out."""
    levels = _bfs_levels(states, start, extra_roots)
    orphans = unreachable_states(states, start, extra_roots)
    if orphans:
        levels.append(orphans)

    BW, BH, GX, GY, PAD = 170, 34, 26, 64, 20
    pos: dict[str, tuple[int, int]] = {}
    width = PAD * 2 + max((len(lv) for lv in levels), default=1) * (BW + GX)
    for yi, lv in enumerate(levels):
        row_w = len(lv) * (BW + GX) - GX
        x0 = (width - row_w) // 2
        for xi, name in enumerate(lv):
            pos[name] = (x0 + xi * (BW + GX), PAD + yi * (BH + GY))
    height = PAD * 2 + len(levels) * (BH + GY)

    orphan_set = set(orphans)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'font-family="monospace" font-size="11">',
        '<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" '
        'markerHeight="6" orient="auto-start-reverse">'
        '<path d="M0,0 L10,5 L0,10 z" fill="#94a3b8"/></marker></defs>',
    ]
    for name, (x, y) in pos.items():
        for t in goto_targets(states[name]):
            if t in pos:
                x2, y2 = pos[t]
                parts.append(
                    f'<line x1="{x + BW // 2}" y1="{y + BH}" x2="{x2 + BW // 2}" y2="{y2}" '
                    f'stroke="#94a3b8" stroke-width="1" opacity="0.55" marker-end="url(#a)"/>'
                )
    for name, (x, y) in pos.items():
        bad = name in orphan_set
        fill, stroke, txt = ("#ffe4e6", "#f43f5e", "#be123c") if bad else ("#f1f5f9", "#94a3b8", "#0f172a")
        if name == start:
            fill, stroke, txt = "#d1fae5", "#10b981", "#047857"
        label = html.escape(name if len(name) <= 24 else name[:23] + "…")
        parts.append(f'<rect x="{x}" y="{y}" width="{BW}" height="{BH}" rx="6" '
                     f'fill="{fill}" stroke="{stroke}"/>')
        parts.append(f'<text x="{x + BW // 2}" y="{y + BH // 2 + 4}" text-anchor="middle" '
                     f'fill="{txt}">{label}</text>')
    parts.append("</svg>")
    out_path.write_text("\n".join(parts), encoding="utf-8")


def lint(path: Path, svg_dir: Path | None) -> int:
    """Lint one config. Returns 0 clean, 1 findings, 2 load error."""
    try:
        cfg = cfgmod.load(path)
    except cfgmod.ConfigError as e:
        print(f"{path.name}: ERROR {e}")
        return 2

    findings = 0
    routine_roots = [r["goto"] for r in cfg.periodic_routines]
    orphans = unreachable_states(cfg.states, cfg.start_state, extra_roots=routine_roots)
    if orphans:
        findings += len(orphans)
        print(f"{path.name}: {len(orphans)} unreachable state(s): {', '.join(orphans)}")
    for state, detect, pngs in note_detect_mismatches(cfg.states):
        findings += 1
        print(f"{path.name}: hint — state '{state}' detects [{detect}] but its "
              f"_note only names {pngs}")

    if svg_dir is not None:
        svg_dir.mkdir(parents=True, exist_ok=True)
        out = svg_dir / f"{path.stem}.svg"
        write_svg(cfg.states, cfg.start_state, out, routine_roots)
        print(f"{path.name}: graph -> {out}")

    if not findings:
        print(f"{path.name}: OK ({len(cfg.states)} states, all reachable)")
    return 1 if findings else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="lint farm FSM configs")
    ap.add_argument("configs", nargs="+", help="config JSON path(s)")
    ap.add_argument("--svg", metavar="DIR", default=None,
                    help="also write a BFS-layered transition graph per config")
    args = ap.parse_args(argv)

    rc = 0
    for c in args.configs:
        rc = max(rc, lint(Path(c), Path(args.svg) if args.svg else None))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
