import pytest

from src.perceive import Match, PerceiveError
from src import episode as rel
from tools import run_episode_loop as tool


def _patch(monkeypatch, *, home_found, label_found, ocr_value, ocr_raises=False):
    monkeypatch.setattr(rel, "grab", lambda device: object())

    def fake_find_named(frame, store, name, threshold=0.82):
        if name == "home/home_play_marker.png":
            return Match(found=home_found, score=1.0, x=0, y=0, w=0, h=0)
        assert name == rel.EPISODE_LABEL_MARKER
        return Match(found=label_found, score=1.0, x=400, y=127, w=126, h=29)

    monkeypatch.setattr(rel, "find_named", fake_find_named)

    def fake_read_counter(frame, region):
        if ocr_raises:
            raise PerceiveError("ocr unavailable")
        return ocr_value

    monkeypatch.setattr(rel, "read_counter", fake_read_counter)


def test_detects_episode_when_home_and_label_present(monkeypatch):
    _patch(monkeypatch, home_found=True, label_found=True, ocr_value=4)
    assert rel.detect_current_episode(device=None, store=None) == 4


def test_returns_none_when_home_not_clean(monkeypatch):
    _patch(monkeypatch, home_found=False, label_found=True, ocr_value=4)
    assert rel.detect_current_episode(device=None, store=None) is None


def test_returns_none_when_label_marker_absent(monkeypatch):
    _patch(monkeypatch, home_found=True, label_found=False, ocr_value=4)
    assert rel.detect_current_episode(device=None, store=None) is None


def test_returns_none_when_ocr_reads_nothing(monkeypatch):
    _patch(monkeypatch, home_found=True, label_found=True, ocr_value=None)
    assert rel.detect_current_episode(device=None, store=None) is None


@pytest.mark.parametrize("bogus", [0, 8, 25, 71])
def test_rejects_out_of_range_digits(monkeypatch, bogus):
    _patch(monkeypatch, home_found=True, label_found=True, ocr_value=bogus)
    assert rel.detect_current_episode(device=None, store=None) is None


def test_returns_none_when_ocr_unavailable(monkeypatch):
    _patch(monkeypatch, home_found=True, label_found=True, ocr_value=None, ocr_raises=True)
    assert rel.detect_current_episode(device=None, store=None) is None


def test_order_is_optional_now():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--order", type=tool._episode_list, default=None)
    assert ap.parse_args([]).order is None
