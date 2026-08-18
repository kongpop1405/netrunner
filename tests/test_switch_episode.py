"""switch_episode's preconditions and its post-Enter confirmation.

Both were wrong live on 2026-08-18 and the failure mode was misleading: the
post-Enter check grabbed once, 2.0s after tapping Enter, so a switch that had
actually worked raised "home_play_marker not visible after Enter" while home was
still reloading. That left the game mid-load, and because the Episode-button tap
is blind, every following switch tapped a screen that was not home and reported
"Episode Map did not open" — a marker-shaped message for a state-leak bug
(observed: Episode 2 raised post-Enter, then 4/5/6/7 all failed at map-open,
while Episode 3 happened to land cleanly and switched fine).
"""
import pytest

from src.perceive import Match
from tools import switch_episode as se


class FakeDevice:
    serial = "fake"

    def shell(self, *args):
        return ""


def _hit(found):
    return Match(found=found, score=1.0 if found else 0.1, x=100, y=100, w=10, h=10)


class Screen:
    """Scripted screen: each find_named call consumes the next verdict for that
    marker name, so a test can say "home is absent twice, then present"."""

    def __init__(self, **scripts):
        self.scripts = {k.replace("__", "/"): list(v) for k, v in scripts.items()}
        self.calls = []

    def find(self, frame, store, name, threshold=0.82):
        self.calls.append(name)
        seq = self.scripts.get(name)
        if seq is None:
            return _hit(False)
        return _hit(seq.pop(0) if len(seq) > 1 else seq[0])


@pytest.fixture
def wired(monkeypatch, tmp_path):
    """switch_episode with capture/sleep/Actor stubbed; returns a taps recorder."""
    (tmp_path / "episode").mkdir()
    for n in ("ep2_banner.png", "ep7_banner.png", "episodemap_marker.png",
              "episodeenter_marker.png"):
        (tmp_path / "episode" / n).write_bytes(b"x")

    monkeypatch.setattr(se, "grab", lambda device: object())
    monkeypatch.setattr(se.time, "sleep", lambda s: None)

    taps = []

    class FakeActor:
        def __init__(self, *a, **k):
            pass

        def tap(self, x, y):
            taps.append((x, y))

        def swipe(self, *a, **k):
            taps.append(("swipe",))

    monkeypatch.setattr(se, "Actor", FakeActor)

    class Store:
        dir = tmp_path

    return taps, Store()


def test_refuses_to_tap_when_never_on_home(wired, monkeypatch):
    """The whole point: do not tap the Episode button blind."""
    taps, store = wired
    screen = Screen(home__home_play_marker__png=[False])
    monkeypatch.setattr(se, "find_named", screen.find)

    with pytest.raises(se.SwitchEpisodeError, match="refusing to tap"):
        se.switch_episode(FakeDevice(), store, 2)
    assert taps == [], f"tapped anyway: {taps}"


def test_waits_for_home_then_proceeds(wired, monkeypatch):
    """Home absent on the first polls, then present -> it must go on to tap."""
    taps, store = wired
    # home: absent, absent, then present forever. map opens; banner found;
    # enter found; home comes back.
    screen = Screen(
        **{"home/home_play_marker.png": [False, False, True],
           "episode/episodemap_marker.png": [True],
           "episode/ep7_banner.png": [True],
           "episode/episodeenter_marker.png": [True]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)
    se.switch_episode(FakeDevice(), store, 7)  # must not raise
    assert (se.EPISODE_BUTTON in taps), taps


def test_post_enter_polls_instead_of_grabbing_once(wired, monkeypatch):
    """Home reappearing late must still count as success — the live bug was a
    single grab at a fixed 2.0s calling a working switch a failure."""
    taps, store = wired
    home_seq = [True]                      # on home at the start
    home_seq += [False] * 6                # still loading after Enter
    home_seq += [True]                     # then home is back
    screen = Screen(
        **{"home/home_play_marker.png": home_seq,
           "episode/episodemap_marker.png": [True],
           se.LEFT_EDGE_MARKER: [True],
           "episode/ep2_banner.png": [True],
           "episode/episodeenter_marker.png": [True]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)
    se.switch_episode(FakeDevice(), store, 2)  # must not raise


def test_post_enter_still_fails_when_home_never_returns(wired, monkeypatch):
    """The check must not be toothless: a switch that really did strand the game
    has to raise, otherwise the caller reports success and the next switch taps
    blind again."""
    taps, store = wired
    screen = Screen(
        **{"home/home_play_marker.png": [True] + [False] * 200,
           "episode/episodemap_marker.png": [True],
           se.LEFT_EDGE_MARKER: [True],
           "episode/ep2_banner.png": [True],
           "episode/episodeenter_marker.png": [True]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)
    with pytest.raises(se.SwitchEpisodeError, match="after Enter"):
        se.switch_episode(FakeDevice(), store, 2)
