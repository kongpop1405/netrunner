"""Watch the emulator screen and report when it stops changing.

The log tells you what the bot *thinks* it sees; this tells you what is actually on
the glass. That gap is not academic — the SDK-handshake dialog on 2026-08-14 held the
screen for ten hours while the log looked busy (restart_app every ~7 min), and nobody
knew what the screen showed until a frame was opened by hand.

Method: grab a frame every `--interval` seconds and compare it to the previous one with
a cheap perceptual hash (8x8 mean-threshold aHash over a downscaled grayscale). Frames
that hash within `--tolerance` bits are "the same screen". When the same screen persists
for `--stuck-after` seconds, emit one line naming the closest matching template — or
UNKNOWN if nothing matches — and save the frame. One line per stuck episode, plus one
when it clears, so the event stream stays readable.

Screens that are *supposed* to sit still are declared in IDLE_SCREENS and reported with
a longer patience, because heart-regen waits and roll animations are not faults.

Stdout is the event stream (Monitor consumes it); everything else goes to stderr.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.perceive import TemplateStore, find  # noqa: E402

# Screens that legitimately hold still. Name -> seconds of stillness tolerated before
# it is worth mentioning. Everything else uses --stuck-after.
IDLE_SCREENS = {
    "boxrun/heart_empty.png": 1800,      # heart regen is a long, correct wait
    "home/home_play_marker.png": 600,    # sitting on home between games
    # Send-Life re-opens the SAME dialog for each friend in turn, so the glass
    # barely changes while the bot is working at full speed — only the friend's
    # name and portrait differ, which an 8x8 aHash cannot see. Reported stuck
    # 263s on 2026-08-21 while the log showed scan -> confirm_dialog ->
    # message_sent cycling every ~5s, and it cleared itself 30s later. Measured
    # across 46 real runs, one episode's pass lasts 10s to 6074s, so this has to
    # tolerate a long hold; sendlife.json's own progress watchdog (180s without a
    # state change) is what actually catches this screen genuinely hanging.
    "mailbox/confirm_btn.png": 1800,
}


def sh(*cmd: str) -> bytes:
    return subprocess.run(cmd, capture_output=True, timeout=30).stdout


def grab(device: str) -> np.ndarray | None:
    raw = sh("adb", "-s", device, "exec-out", "screencap", "-p")
    if not raw:
        return None
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    return img


def ahash(img: np.ndarray) -> int:
    g = cv2.cvtColor(cv2.resize(img, (8, 8), interpolation=cv2.INTER_AREA),
                     cv2.COLOR_BGR2GRAY)
    bits = (g > g.mean()).flatten()
    out = 0
    for b in bits:
        out = (out << 1) | int(b)
    return out


def dist(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def identify(frame, store, names, threshold=0.82):
    """Closest template on this frame: (name, score) or (None, best_score)."""
    best_name, best = None, 0.0
    for n in names:
        try:
            m = find(frame, store.get(n), threshold)
        except Exception:
            continue
        if m.score > best:
            best_name, best = n, m.score
    return (best_name, best) if best >= threshold else (None, best)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="127.0.0.1:5555")
    ap.add_argument("--interval", type=float, default=20.0)
    ap.add_argument("--stuck-after", type=float, default=180.0)
    ap.add_argument("--tolerance", type=int, default=4,
                    help="aHash bit distance still counted as the same screen")
    ap.add_argument("--templates", default="templates/cookierun")
    ap.add_argument("--outdir", default="unknown_screens")
    args = ap.parse_args()

    store = TemplateStore(args.templates)
    root = Path(args.templates)
    names = sorted(str(p.relative_to(root)).replace("\\", "/")
                   for p in root.rglob("*.png") if "_archive" not in p.parts)
    print(f"[watch] {len(names)} templates, every {args.interval:.0f}s, "
          f"stuck after {args.stuck_after:.0f}s", file=sys.stderr, flush=True)

    prev_hash = None
    still_since = time.monotonic()
    reported = False
    fails = 0

    while True:
        frame = grab(args.device)
        if frame is None:
            fails += 1
            # A device that cannot be grabbed at all is itself worth one event.
            if fails == 3:
                print("SCREEN adb screencap returned nothing 3x — emulator gone?",
                      flush=True)
            time.sleep(args.interval)
            continue
        fails = 0

        h = ahash(frame)
        now = time.monotonic()

        if prev_hash is None or dist(h, prev_hash) > args.tolerance:
            if reported:
                held = now - still_since
                print(f"SCREEN cleared after {held:.0f}s", flush=True)
            prev_hash, still_since, reported = h, now, False
            time.sleep(args.interval)
            continue

        held = now - still_since
        if reported:
            time.sleep(args.interval)
            continue

        name, score = identify(frame, store, names)
        patience = IDLE_SCREENS.get(name or "", args.stuck_after)
        if held >= patience:
            stamp = time.strftime("%Y%m%d_%H%M%S")
            out = Path(args.outdir) / f"stuck_{stamp}.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), frame)
            what = f"{name} ({score:.2f})" if name else f"UNKNOWN (best {score:.2f})"
            print(f"SCREEN stuck {held:.0f}s on {what} -> {out}", flush=True)
            reported = True

        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
