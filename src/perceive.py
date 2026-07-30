"""Perception — locate a template PNG on a screen frame; optional OCR."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


class PerceiveError(RuntimeError):
    pass


@dataclass(frozen=True)
class Match:
    found: bool
    score: float          # peak correlation 0..1
    x: int                # center of matched region (screen px)
    y: int
    w: int                # template size
    h: int


class TemplateStore:
    """Loads and caches template images from a directory.

    Templates are referenced by filename in the config; caching avoids re-reading
    the same PNG from disk on every poll cycle.
    """

    def __init__(self, templates_dir: str | Path):
        self.dir = Path(templates_dir)
        self._cache: dict[str, np.ndarray] = {}

    def get(self, name: str) -> np.ndarray:
        if name not in self._cache:
            path = self.dir / name
            img = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if img is None:
                raise PerceiveError(f"template not found or unreadable: {path}")
            self._cache[name] = img
        return self._cache[name]


def find(
    frame: np.ndarray,
    template: np.ndarray,
    threshold: float = 0.85,
    roi: tuple[int, int, int, int] | None = None,
) -> Match:
    """Single-scale template match. Returns center coords when score >= threshold.

    `roi` = (x, y, w, h) restricts the search to a sub-rectangle. Coordinates in
    the returned Match are still full-frame, so callers never have to un-offset.
    A tight ROI is both faster (matchTemplate cost scales with search area) and
    safer: an in-run obstacle template would otherwise match the same sprite
    drawn anywhere else on screen.
    """
    ox = oy = 0
    if roi is not None:
        ox, oy, rw, rh = roi
        frame = frame[oy : oy + rh, ox : ox + rw]
        if frame.size == 0:
            raise PerceiveError(f"roi {roi} is empty or outside the frame")

    th, tw = template.shape[:2]
    fh, fw = frame.shape[:2]
    if th > fh or tw > fw:
        where = f"roi ({fw}x{fh})" if roi is not None else f"frame ({fw}x{fh})"
        raise PerceiveError(
            f"template ({tw}x{th}) larger than {where} — "
            "captured at a different resolution than the template was cropped?"
        )
    if float(template.std()) < 1.0:
        # TM_CCOEFF_NORMED divides by template variance; a (near-)uniform template
        # makes the score undefined and it reports ~1.0 everywhere (false positive).
        raise PerceiveError(
            "template is (near-)uniform color — matchTemplate scores would be "
            "meaningless; crop a region with actual detail"
        )
    # matchTemplate allocates a (fh-th+1)x(fw-tw+1) float32 result matrix; on a
    # RAM-starved host (LDPlayer alone can eat 1.5-3GB, same pressure noted in
    # capture.py) that alloc can transiently fail. Retry with backoff rather than
    # crashing the whole run over one bad cycle.
    last: cv2.error | None = None
    for attempt in range(3):
        try:
            res = cv2.matchTemplate(frame, template, cv2.TM_CCOEFF_NORMED)
            break
        except cv2.error as e:
            if "Insufficient memory" not in str(e):
                raise
            last = e
            time.sleep(1.0 * (attempt + 1))
    else:
        raise PerceiveError(f"matchTemplate out of memory after 3 attempts: {last}")
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    cx = ox + max_loc[0] + tw // 2
    cy = oy + max_loc[1] + th // 2
    return Match(
        found=bool(max_val >= threshold),
        score=float(max_val),
        x=int(cx), y=int(cy), w=int(tw), h=int(th),
    )


def find_named(
    frame: np.ndarray,
    store: TemplateStore,
    name: str,
    threshold: float = 0.85,
    roi: tuple[int, int, int, int] | None = None,
) -> Match:
    """Convenience: resolve a template by name from the store, then match."""
    return find(frame, store.get(name), threshold, roi=roi)


def read_text(frame: np.ndarray, region: tuple[int, int, int, int] | None = None,
              config: str = "") -> str:
    """OCR a frame (or a sub-region x,y,w,h) via pytesseract. Optional dependency.

    `config` goes straight to tesseract — see read_counter for the digits-only
    invocation a counter needs.
    """
    try:
        import pytesseract  # noqa: PLC0415 — optional, imported lazily
    except ImportError as e:
        raise PerceiveError(
            "OCR requested but pytesseract is not installed (pip install pytesseract "
            "and install the tesseract binary)"
        ) from e
    if region is not None:
        x, y, w, h = region
        frame = frame[y : y + h, x : x + w]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    return pytesseract.image_to_string(gray, config=config).strip()


#: tesseract page-segmentation mode 7 = "treat the image as one text line", which
#: is what a counter pill is; the whitelist keeps it from reading the x in "x3"
#: or the box glyph as a digit.
_COUNTER_CONFIG = "--psm 7 -c tessedit_char_whitelist=0123456789"

#: Upscale before OCR. A counter pill is ~30px tall in a 1080p frame and
#: tesseract is trained on print-sized glyphs; without this it reads mostly noise.
_COUNTER_SCALE = 4


def read_counter(frame: np.ndarray, region: tuple[int, int, int, int] | None = None,
                 *, scale: int = _COUNTER_SCALE) -> int | None:
    """Read a small integer (a box/coin counter) from a frame region.

    Returns None when nothing digit-like is there — a caller must treat that as
    "unknown", not as zero. Everything about a counter fights OCR: the digits are
    tiny, sit on a busy background, and are prefixed by an "x" that reads as a
    number if allowed to. So the region is upscaled, thresholded, and tesseract
    is pinned to one line of digits.

    Raises PerceiveError only when OCR itself is unavailable; a frame that simply
    holds no readable digits is a None, not an error.
    """
    if region is not None:
        x, y, w, h = region
        frame = frame[y : y + h, x : x + w]
    if frame.size == 0:
        return None

    gray = frame if frame.ndim == 2 else cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    if scale > 1:
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # Otsu rather than a fixed cut: the pill's background brightness changes with
    # whatever the level is drawing behind it.
    _, binary = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Digits must end up dark-on-light for tesseract; the pill draws them light.
    if float(binary.mean()) < 127:
        binary = cv2.bitwise_not(binary)

    raw = read_text(binary, config=_COUNTER_CONFIG)
    digits = "".join(c for c in raw if c.isdigit())
    if not digits:
        return None
    return int(digits)
