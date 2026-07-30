"""Summarize farm runs from the rotated log files into an HTML report.

    python tools/report_runs.py                     # logs/ -> docs/reports/runs.html
    python tools/report_runs.py --logs logs --out docs/reports/runs.html

Reads `logs/netrunner.log*` (hourly rotation, 72h retained) and counts what the
FSM already writes at INFO: state transitions, adb/perceive failures, livelock
warnings, archived unknown screens. Nothing new has to be instrumented — the
point is that the numbers exist but nobody reads them back.

Why it matters: Phase 1-2 of the parity plan (inter-game delay, session reset)
deliberately trade throughput for a less bot-like cadence. Without a before
number there is no way to say how much was traded.

The active `netrunner.log` has no date in its name and the log lines carry only
HH:MM:SS, so timestamps are reconstructed: rotated files take their date from
the `.YYYY-MM-DD_HH` suffix, the active file from its mtime, and a clock that
goes backwards inside one file is treated as passing midnight.
"""
from __future__ import annotations

import argparse
import html
import re
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

_LINE = re.compile(
    r"^(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2}) "
    r"(?P<level>DEBUG|INFO|WARNING|ERROR|CRITICAL) "
    r"(?P<logger>[\w.]+): (?P<msg>.*)$"
)
_ROTATED = re.compile(r"\.(?P<date>\d{4}-\d{2}-\d{2})_(?P<hour>\d{2})$")

_TRANSITION = re.compile(r"^transition (?P<src>\S+) -> (?P<dst>\S+)$")

#: Events counted by substring. Kept as (key, needle) so a message reword only
#: breaks the one counter, and stays visible as a zero in the report.
_EVENTS = (
    ("adb_fail", "adb error on cycle"),
    ("perceive_fail", "perceive error on cycle"),
    ("livelock", "possible livelock"),
    ("unknown_screen", "archived unrecognized screen"),
    ("match_timeout", "match_timeout"),
    ("session_start", "start state="),
    ("crash", "fatal:"),
    ("adb_lost", "adb unusable after"),
    ("close_retry", "still on screen"),
)

#: Transitions that mark progress worth counting per hour. Config-name agnostic:
#: every boxrun/coinrun config uses these state names.
_RUN_STARTED = "running"
_RUN_FINISHED = "run_result"
_BOX_STATES = ("mb_open", "mystery_box_recheck")


def _file_start(path: Path) -> datetime:
    """Wall-clock date the first line of this file belongs to."""
    m = _ROTATED.search(path.name)
    if m:
        d = datetime.strptime(m.group("date"), "%Y-%m-%d")
        return d.replace(hour=int(m.group("hour")))
    # Active file: mtime is the last write, and an hourly file spans <= 1h.
    mt = datetime.fromtimestamp(path.stat().st_mtime)
    return mt.replace(minute=0, second=0, microsecond=0)


def parse_file(path: Path) -> list[dict]:
    """Rows of {ts, level, logger, msg} with reconstructed absolute timestamps."""
    base = _file_start(path)
    day = base.date()
    prev_clock: tuple[int, int, int] | None = None
    rows: list[dict] = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = _LINE.match(raw)
        if not m:
            continue  # continuation line of a traceback
        clock = (int(m.group("h")), int(m.group("m")), int(m.group("s")))
        if prev_clock is not None and clock < prev_clock:
            day += timedelta(days=1)  # clock went backwards -> crossed midnight
        prev_clock = clock
        rows.append({
            "ts": datetime.combine(day, datetime.min.time()).replace(
                hour=clock[0], minute=clock[1], second=clock[2]),
            "level": m.group("level"),
            "logger": m.group("logger"),
            "msg": m.group("msg"),
        })
    return rows


def collect(log_dir: Path) -> list[dict]:
    files = sorted(log_dir.glob("netrunner.log*"), key=_file_start)
    rows: list[dict] = []
    for f in files:
        rows.extend(parse_file(f))
    rows.sort(key=lambda r: r["ts"])
    return rows


def summarize(rows: list[dict]) -> dict:
    events = Counter()
    per_hour: dict[str, Counter] = {}
    transitions = Counter()
    states_visited = Counter()

    for r in rows:
        msg = r["msg"]
        hour = r["ts"].strftime("%Y-%m-%d %H:00")
        bucket = per_hour.setdefault(hour, Counter())

        for key, needle in _EVENTS:
            if needle in msg:
                events[key] += 1
                bucket[key] += 1

        t = _TRANSITION.match(msg)
        if t:
            src, dst = t.group("src"), t.group("dst")
            transitions[f"{src} -> {dst}"] += 1
            states_visited[dst] += 1
            if dst == _RUN_STARTED and src != _RUN_STARTED:
                events["runs_started"] += 1
                bucket["runs_started"] += 1
            if dst == _RUN_FINISHED:
                events["runs_finished"] += 1
                bucket["runs_finished"] += 1
            if dst in _BOX_STATES and src not in _BOX_STATES:
                events["boxes_seen"] += 1
                bucket["boxes_seen"] += 1

    span_h = 0.0
    if rows:
        span_h = (rows[-1]["ts"] - rows[0]["ts"]).total_seconds() / 3600
    return {
        "events": events,
        "per_hour": per_hour,
        "transitions": transitions,
        "states": states_visited,
        "span_h": span_h,
        "first": rows[0]["ts"] if rows else None,
        "last": rows[-1]["ts"] if rows else None,
        "lines": len(rows),
        "warnings": [r for r in rows if r["level"] in ("WARNING", "ERROR", "CRITICAL")],
    }


_CSS = """
:root{--bg:#fff;--elev:#f8fafc;--elev2:#f1f5f9;--bd:#e2e8f0;--tx:#0f172a;--dim:#475569;
--faint:#94a3b8;--ac:#0ea5e9;--gn:#10b981;--am:#f59e0b;--rd:#f43f5e;--in:#6366f1}
@media(prefers-color-scheme:dark){:root{--bg:#020617;--elev:#0f172a;--elev2:#1e293b;
--bd:#1e293b;--tx:#f1f5f9;--dim:#94a3b8;--faint:#64748b;--ac:#38bdf8;--gn:#34d399;
--am:#fbbf24;--rd:#fb7185;--in:#818cf8}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--tx);
font:14px/1.6 Inter,ui-sans-serif,system-ui,sans-serif}
.wrap{max-width:1080px;margin:0 auto;padding:40px 20px 80px}
h1{font-size:25px;margin:0 0 6px;letter-spacing:-.02em}
.sub{color:var(--dim);font-size:13px;margin-bottom:28px}
h2{font-size:18px;margin:34px 0 12px}
.stats{display:grid;grid-template-columns:repeat(auto-fit,minmax(140px,1fr));gap:10px}
.stat{background:var(--elev);border:1px solid var(--bd);border-radius:10px;padding:13px 15px}
.stat .l{font-size:10.5px;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
color:var(--faint)}.stat .v{font:700 19px/1.2 ui-monospace,monospace;margin-top:3px}
.tw{overflow-x:auto}table{width:100%;border-collapse:collapse;background:var(--elev);
border-radius:10px;overflow:hidden;font-size:13px}
th{text-align:left;font-size:10.5px;text-transform:uppercase;letter-spacing:.05em;
color:var(--dim);padding:9px 12px;background:var(--elev2);border-bottom:1px solid var(--bd)}
td{padding:8px 12px;border-bottom:1px solid var(--bd);vertical-align:top}
tr:last-child td{border-bottom:none}
td.n{font-family:ui-monospace,monospace;text-align:right;white-space:nowrap}
code{font-family:ui-monospace,monospace;font-size:12px;background:var(--elev2);
padding:1px 6px;border-radius:4px;color:var(--in)}
.bar{height:6px;background:var(--elev2);border-radius:3px;overflow:hidden;min-width:60px}
.bar i{display:block;height:100%;background:var(--ac);border-radius:3px}
.empty{background:var(--elev);border:1px dashed var(--bd);border-radius:10px;
padding:28px;text-align:center;color:var(--faint)}
.note{background:var(--elev);border:1px solid var(--bd);border-left:3px solid var(--ac);
border-radius:8px;padding:12px 14px;font-size:13px;color:var(--dim);margin-top:14px}
"""


def _stat(label: str, value, color: str | None = None) -> str:
    style = f' style="color:var(--{color})"' if color else ""
    return (f'<div class="stat"><div class="l">{html.escape(label)}</div>'
            f'<div class="v"{style}>{value}</div></div>')


def render(s: dict, out: Path, log_dir: Path) -> None:
    ev = s["events"]
    span = s["span_h"]
    per_h = (lambda n: f"{n / span:.1f}" if span >= 0.05 else "—")

    if not s["lines"]:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            f'<meta charset="utf-8"><title>NetRunner run report</title><style>{_CSS}</style>'
            f'<div class="wrap"><h1>NetRunner — run report</h1>'
            f'<div class="sub">no parsable lines under {html.escape(str(log_dir))}</div>'
            f'<div class="empty">Nothing to summarize yet — run the bot, then re-run this tool.<br>'
            f'Baseline numbers matter most <b>before</b> Phase 1–2 change the pacing.</div></div>',
            encoding="utf-8")
        return

    parts = [
        '<meta charset="utf-8"><title>NetRunner run report</title>',
        f"<style>{_CSS}</style>", '<div class="wrap">',
        "<h1>NetRunner — run report</h1>",
        f'<div class="sub">{html.escape(str(log_dir))} · '
        f'{s["first"]:%Y-%m-%d %H:%M} → {s["last"]:%Y-%m-%d %H:%M} '
        f'({span:.1f}h, {s["lines"]:,} lines)</div>',
        "<h2>Throughput</h2>", '<div class="stats">',
        _stat("Runs started", ev["runs_started"], "gn"),
        _stat("Runs finished", ev["runs_finished"], "gn"),
        _stat("Runs / hour", per_h(ev["runs_started"])),
        _stat("Boxes seen", ev["boxes_seen"]),
        _stat("Boxes / hour", per_h(ev["boxes_seen"])),
        _stat("Sessions", ev["session_start"]),
        "</div>",
        "<h2>Health</h2>", '<div class="stats">',
        _stat("adb failures", ev["adb_fail"], "am" if ev["adb_fail"] else None),
        _stat("perceive OOM", ev["perceive_fail"], "am" if ev["perceive_fail"] else None),
        _stat("Livelocks", ev["livelock"], "rd" if ev["livelock"] else None),
        _stat("Match timeouts", ev["match_timeout"], "am" if ev["match_timeout"] else None),
        _stat("Unknown screens", ev["unknown_screen"], "in" if ev["unknown_screen"] else None),
        _stat("close_popup retries", ev["close_retry"]),
        _stat("Crashes", ev["crash"], "rd" if ev["crash"] else None),
        _stat("adb lost", ev["adb_lost"], "rd" if ev["adb_lost"] else None),
        "</div>",
    ]

    hours = sorted(s["per_hour"])
    if hours:
        peak = max((s["per_hour"][h]["runs_started"] for h in hours), default=0) or 1
        parts += ["<h2>Per hour</h2>", '<div class="tw"><table>',
                  "<tr><th>Hour</th><th>Runs</th><th></th><th>Boxes</th>"
                  "<th>adb fail</th><th>OOM</th><th>Livelock</th></tr>"]
        for h in hours:
            b = s["per_hour"][h]
            runs = b["runs_started"]
            parts.append(
                f'<tr><td>{html.escape(h)}</td><td class="n">{runs}</td>'
                f'<td style="width:34%"><div class="bar"><i style="width:'
                f'{round(runs / peak * 100)}%"></i></div></td>'
                f'<td class="n">{b["boxes_seen"]}</td><td class="n">{b["adb_fail"]}</td>'
                f'<td class="n">{b["perceive_fail"]}</td><td class="n">{b["livelock"]}</td></tr>')
        parts.append("</table></div>")

    top_t = s["transitions"].most_common(15)
    if top_t:
        parts += ["<h2>Hottest transitions</h2>", '<div class="tw"><table>',
                  "<tr><th>Transition</th><th>Count</th></tr>"]
        parts += [f'<tr><td><code>{html.escape(k)}</code></td><td class="n">{v}</td></tr>'
                  for k, v in top_t]
        parts.append("</table></div>")
        parts.append('<div class="note">A transition pair dominating the count is usually a '
                     'probe chain being walked far more often than the flow needs — the '
                     'cheapest place to cut wasted captures.</div>')

    warns = Counter(re.sub(r"\d+", "N", w["msg"])[:130] for w in s["warnings"])
    if warns:
        parts += ["<h2>Warnings &amp; errors (digit-normalized)</h2>", '<div class="tw"><table>',
                  "<tr><th>Message</th><th>Count</th></tr>"]
        parts += [f'<tr><td>{html.escape(k)}</td><td class="n">{v}</td></tr>'
                  for k, v in warns.most_common(20)]
        parts.append("</table></div>")

    parts.append('<div class="note"><b>Use as a baseline.</b> Phase 1 (inter-game delay) and '
                 'Phase 2 (session reset) intentionally lower runs/hour in exchange for a less '
                 'bot-like cadence. Snapshot this report before enabling them, then compare.</div>')
    parts.append("</div>")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(parts), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="summarize netrunner logs into an HTML report")
    ap.add_argument("--logs", default="logs", help="log directory (default: logs)")
    ap.add_argument("--out", default="docs/reports/runs.html", help="output HTML path")
    args = ap.parse_args(argv)

    log_dir = Path(args.logs)
    if not log_dir.is_dir():
        print(f"error: log dir not found: {log_dir}")
        return 2
    rows = collect(log_dir)
    s = summarize(rows)
    out = Path(args.out)
    render(s, out, log_dir)
    ev = s["events"]
    print(f"{s['lines']:,} lines over {s['span_h']:.1f}h -> {out}")
    print(f"  runs={ev['runs_started']} boxes={ev['boxes_seen']} "
          f"adb_fail={ev['adb_fail']} livelock={ev['livelock']} "
          f"unknown={ev['unknown_screen']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
