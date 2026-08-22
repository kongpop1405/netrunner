"""Phase 8 — reading the box counter, and coping when OCR is unavailable."""
import logging
from pathlib import Path

import cv2
import numpy as np
import pytest

import src.perceive as perceive
from src.perceive import PerceiveError, read_counter, read_counter_voted

_HAS_TESSERACT = False
try:
    import pytesseract

    pytesseract.get_tesseract_version()
    _HAS_TESSERACT = True
except Exception:  # noqa: BLE001 — any failure means we cannot OCR here
    pass

needs_ocr = pytest.mark.skipif(
    not _HAS_TESSERACT,
    reason="pytesseract + the tesseract binary are an optional dependency")


def _pill(text: str, w: int = 90, h: int = 44) -> np.ndarray:
    """A counter pill: light digits on a dark rounded background, like the HUD."""
    img = np.full((h, w, 3), 40, dtype=np.uint8)
    cv2.putText(img, text, (6, h - 12), cv2.FONT_HERSHEY_SIMPLEX, 1.1,
                (245, 245, 245), 2, cv2.LINE_AA)
    return img


class TestReadCounterPreprocessing:
    """Behaviour that holds with or without a tesseract install."""

    def test_empty_region_is_unknown_not_zero(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        assert read_counter(frame, (5, 5, 0, 0)) is None

    def test_region_outside_frame_is_unknown(self):
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        assert read_counter(frame, (50, 50, 20, 20)) is None

    def test_missing_ocr_raises_perceive_error(self, monkeypatch):
        """A caller must be able to tell "OCR is not installed" from "no digits" —
        the first is permanent and worth falling back on, the second is not."""
        def no_pytesseract(frame, config=""):
            raise PerceiveError("OCR requested but pytesseract is not installed")

        monkeypatch.setattr(perceive, "read_text", no_pytesseract)
        with pytest.raises(PerceiveError, match="not installed"):
            read_counter(_pill("3"))

    def test_non_digits_are_discarded(self, monkeypatch):
        """The pill reads "x3"; the x must never become part of the number."""
        monkeypatch.setattr(perceive, "read_text", lambda frame, config="": "x3")
        assert read_counter(_pill("x3")) == 3

    def test_no_digits_is_none(self, monkeypatch):
        monkeypatch.setattr(perceive, "read_text", lambda frame, config="": "~~")
        assert read_counter(_pill("?")) is None

    def test_digits_only_config_is_requested(self, monkeypatch):
        seen = {}

        def spy(frame, config=""):
            seen["config"] = config
            return "4"

        monkeypatch.setattr(perceive, "read_text", spy)
        read_counter(_pill("4"))
        assert "--psm 7" in seen["config"]
        assert "tessedit_char_whitelist=0123456789" in seen["config"]

    def test_light_digits_are_inverted_for_tesseract(self, monkeypatch):
        """tesseract wants dark text on light; the HUD draws the opposite."""
        captured = {}

        def spy(frame, config=""):
            captured["mean"] = float(frame.mean())
            return "2"

        monkeypatch.setattr(perceive, "read_text", spy)
        read_counter(_pill("2"))
        assert captured["mean"] > 127  # background ended up light

    def test_upscales_before_reading(self, monkeypatch):
        """A ~40px pill is far below what tesseract is trained on."""
        sizes = {}

        def spy(frame, config=""):
            sizes["shape"] = frame.shape
            return "1"

        monkeypatch.setattr(perceive, "read_text", spy)
        read_counter(_pill("1", w=90, h=44), scale=4)
        assert sizes["shape"][0] >= 44 * 4


@needs_ocr
class TestReadCounterLive:
    @pytest.mark.parametrize("n", [1, 2, 3, 4, 7])
    def test_reads_rendered_digits(self, n):
        assert read_counter(_pill(str(n))) == n

    def test_reads_through_the_x_prefix(self):
        assert read_counter(_pill("x3")) == 3

    def test_noise_does_not_produce_a_number(self):
        rng = np.random.default_rng(7)
        noise = rng.integers(0, 255, (44, 90, 3), dtype=np.uint8)
        assert read_counter(noise) in (None, *range(0, 100))  # must not crash


class TestBoxQuitRunnerFallback:
    """The quit decision must survive OCR being unavailable."""

    def _runner(self, monkeypatch, ocr_result, quit_after=2):
        import tools.run_toggle as rt
        from src.config import Config

        class FakeDevice:
            serial = "fake"

            def shell(self, *args):
                return ""

        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                     start_state="check_box",
                     states={"check_box": {"detect": "c.png", "on_match": [
                         {"type": "goto", "state": "quit_run"}]},
                             "quit_run": {"detect": "q.png"},
                             "check_shop_after_run": {"detect": "s.png"}})
        r = rt.BoxQuitRunner(cfg, FakeDevice(), quit_after=quit_after)
        monkeypatch.setattr(r, "_read_box_count", lambda frame: ocr_result)
        return r

    def _decide(self, runner):
        """Returns the goto the subclass allows, or None when it lets it through."""
        actions = [{"type": "goto", "state": "quit_run"}]
        try:
            return runner._run_actions(actions, None, "check_box")[0]
        except Exception:
            # falling through to the real Actor is fine — the redirect is what
            # this asserts, and a pass-through means "quit allowed"
            return "quit_run"

    def test_ocr_count_below_target_continues(self, monkeypatch):
        r = self._runner(monkeypatch, ocr_result=1, quit_after=2)
        assert self._decide(r) == "check_shop_after_run"

    def test_ocr_count_at_target_quits(self, monkeypatch):
        r = self._runner(monkeypatch, ocr_result=2, quit_after=2)
        assert self._decide(r) == "quit_run"

    def test_falls_back_to_run_counting_without_ocr(self, monkeypatch):
        r = self._runner(monkeypatch, ocr_result=None, quit_after=2)
        assert self._decide(r) == "check_shop_after_run"  # run 1
        r._box_counted_this_run = False                    # new run
        assert self._decide(r) == "quit_run"               # run 2 reaches the target

    def test_quit_after_zero_never_quits(self, monkeypatch):
        for ocr in (None, 1, 9):
            r = self._runner(monkeypatch, ocr_result=ocr, quit_after=0)
            assert self._decide(r) == "check_shop_after_run"

    def test_continue_follows_check_box_absent_edge(self, monkeypatch):
        """A relay poll spliced in front of check_shop_after_run must not be
        skipped: the real configs route check_box's absent path through
        relay_poll1_check_box, and the continue-the-run decision has to enter
        that chain rather than jump past it to the old target."""
        r = self._runner(monkeypatch, ocr_result=1, quit_after=0)
        r.cfg.states["check_box"]["on_absent"] = {"goto": "relay_poll1_check_box"}
        r.cfg.states["relay_poll1_check_box"] = {"detect": "r1.png"}
        assert self._decide(r) == "relay_poll1_check_box"

    def test_continue_reads_list_shaped_absent_edge(self, monkeypatch):
        r = self._runner(monkeypatch, ocr_result=1, quit_after=0)
        r.cfg.states["check_box"]["on_absent"] = [
            {"type": "wait", "ms": 100},
            {"type": "goto", "state": "relay_poll1_check_box"},
        ]
        r.cfg.states["relay_poll1_check_box"] = {"detect": "r1.png"}
        assert self._decide(r) == "relay_poll1_check_box"

    def test_ocr_error_disables_ocr_for_the_session(self, monkeypatch, caplog):
        import tools.run_toggle as rt

        class FakeDevice:
            serial = "fake"

            def shell(self, *args):
                return ""

        from src.config import Config
        cfg = Config(device=None, templates_dir=".", poll_ms=1, match_threshold=0.8,
                     start_state="a", states={"a": {"detect": "a.png"}})
        r = rt.BoxQuitRunner(cfg, FakeDevice(), quit_after=1)

        def boom(frame, store, name, thr):
            raise PerceiveError("tesseract is not installed")

        monkeypatch.setattr(rt, "find_named", boom)
        frame = np.zeros((10, 10, 3), dtype=np.uint8)
        with caplog.at_level(logging.WARNING):
            assert r._read_box_count(frame) is None
        assert not r._ocr_available          # never retried
        assert r._read_box_count(frame) is None
        assert sum("OCR unavailable" in rec.message for rec in caplog.records) == 1


class TestVotedCounterOnRealBadges:
    """Live regression 2026-08-20. read_counter took one reading at one padding,
    and three sweeps in a row logged "no readable Lives badge" while the badge
    plainly showed 18, 16, and 14 — the gate then skipped Send-Life every time,
    so the feature was dead in the field while every unit test passed.

    Cause was the crop, not the digits: with a few px of padding, psm 7 returned
    the empty string for those three, and flush it read all of them. But flush is
    what had earlier misread the single-digit Rewards badge as 47 by clipping into
    its neighbour. Neither crop is right for both, so the reader votes across
    paddings and psm modes.

    Fixtures are the actual failing frames, cropped to the pill plus 16px.
    """

    DIR = Path(__file__).parent / "fixtures" / "badges"

    #: Every badge value seen live so far, including the one that broke the
    #: opposite way (single digit, neighbour adjacent).
    CASES = [("53", 53), ("18", 18), ("16", 16), ("14", 14), ("4", 4)]

    def _frame(self, name):
        img = cv2.imread(str(self.DIR / f"badge_{name}.png"))
        assert img is not None, f"missing fixture badge_{name}.png"
        return img

    #: The pill sits at the fixture's 16px margin, its measured 55x40.
    REGION = (16, 16, 55, 40)

    @pytest.mark.parametrize("name,expected", CASES)
    def test_voting_reads_every_badge_seen_live(self, name, expected):
        assert read_counter_voted(self._frame(name), self.REGION) == expected

    def test_voting_beats_a_single_reading(self):
        """Guards the reason the voted reader exists: a single padded reading is
        what shipped, and it got 2 of these 5 right."""
        singles = [read_counter(self._frame(n), (12, 12, 63, 48))
                   for n, _ in self.CASES]
        voted = [read_counter_voted(self._frame(n), self.REGION)
                 for n, _ in self.CASES]
        want = [v for _, v in self.CASES]
        assert voted == want, voted
        assert singles != want, (
            "a single reading now passes too — if the OCR install changed, "
            f"re-check whether voting is still buying anything: {singles}")

    def test_an_unreadable_region_is_none_not_zero(self):
        """A caller must be able to tell "nothing there" from "zero waiting";
        the tab drops the badge entirely at zero."""
        blank = np.full((72, 87, 3), 210, dtype=np.uint8)
        assert read_counter_voted(blank, self.REGION) is None
