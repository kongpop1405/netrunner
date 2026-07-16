"""Shared test fixtures — synthetic frames and a real template dir on disk."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def _noise(seed: int, shape=(200, 300, 3)) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(0, 255, shape, dtype=np.uint8)


@pytest.fixture
def frame() -> np.ndarray:
    """A deterministic 300x200 BGR frame."""
    return _noise(42)


@pytest.fixture
def tdir(tmp_path: Path, frame: np.ndarray) -> Path:
    """Template dir with marker.png (present in `frame`, center ~(120,65))
    and other.png (from an unrelated frame — never matches)."""
    d = tmp_path / "templates"
    d.mkdir()
    cv2.imwrite(str(d / "marker.png"), frame[50:80, 100:140])
    cv2.imwrite(str(d / "other.png"), _noise(7)[50:80, 100:140])
    return d
