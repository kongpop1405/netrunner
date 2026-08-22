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


def test_refuses_to_tap_through_the_exit_dialog(wired, monkeypatch):
    """Snapped live 2026-08-20 09:13:55 on the frame where all three map taps
    failed: the game's "Exit the game?" dialog was centred over home and
    home_play_marker still scored 1.000 through it (Play! bottom-right, dialog
    centred, no overlap). The old guard saw Play!, passed, and tapped the Episode
    button into the modal — then reported the MAP as the thing that failed, which
    is the misdiagnosis its own comment warns about. Episodes 3-7 failed this way
    three cycles running, and the Episode restore with them."""
    taps, store = wired
    screen = Screen(**{"home/home_play_marker.png": [True],
                       "home/exitgame_marker.png": [True]})
    monkeypatch.setattr(se, "find_named", screen.find)

    with pytest.raises(se.SwitchEpisodeError, match="Exit the game"):
        se.switch_episode(FakeDevice(), store, 2)
    assert taps == [], f"tapped with the dialog up: {taps}"


def test_the_dialog_clearing_lets_the_switch_proceed(wired, monkeypatch):
    """A dialog that goes away (something dismissed it) must not poison the rest
    of the wait — the guard has to re-read, not latch."""
    taps, store = wired
    screen = Screen(
        **{"home/exitgame_marker.png": [True, True, False],
           "home/home_play_marker.png": [True],
           "episode/episodemap_marker.png": [True],
           "episode/ep7_banner.png": [True],
           "episode/episodeenter_marker.png": [True]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)
    se.switch_episode(FakeDevice(), store, 7)  # must not raise
    assert se.EPISODE_BUTTON in taps, taps


def test_the_dialog_is_checked_before_play(wired, monkeypatch):
    """Order matters: both markers hit 1.000 on the ambiguous frame, so reading
    Play! first and breaking would never look at the dialog at all."""
    taps, store = wired
    screen = Screen(**{"home/home_play_marker.png": [True],
                       "home/exitgame_marker.png": [True]})
    monkeypatch.setattr(se, "find_named", screen.find)
    with pytest.raises(se.SwitchEpisodeError):
        se.switch_episode(FakeDevice(), store, 2)
    first = screen.calls[0]
    assert first == "home/exitgame_marker.png", (
        f"the guard read {first} first — with both at 1.000 that decides before "
        f"the dialog is ever considered")


def test_a_failure_after_the_map_opens_closes_it(wired, monkeypatch):
    """Live 2026-08-20 14:13-14:14: Episode 6's banner was not found after 6
    swipes, switch_episode raised, and the Episode Map stayed open. Every later
    step then failed on that screen instead of its own merits — Episode 7 and the
    restore of Episode 2 both got "not on home after 15s" (the guard doing its
    job), so the farm loop was left on the wrong Episode and the progress watchdog
    fired 1619s later. Closing the map on the way out is what keeps one episode's
    failure from taking the rest of the pass down with it.

    Measured that day: the map's X at (1841,75) drops it and home comes straight
    back (episodemap 1.000 -> 0.173, home_play 0.308 -> 1.000)."""
    taps, store = wired
    screen = Screen(
        **{"home/home_play_marker.png": [True],
           "episode/episodemap_marker.png": [True],
           "episode/ep7_banner.png": [True],
           # the target banner never shows up -> the swipe search gives up
           "episode/ep2_banner.png": [False]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)

    with pytest.raises(se.SwitchEpisodeError, match="not found after"):
        se.switch_episode(FakeDevice(), store, 2)
    assert se.MAP_CLOSE in taps, (
        f"the map was left open — later steps will fail on it, not on their own "
        f"problem: {taps}")


def test_the_map_is_not_closed_when_it_never_opened(wired, monkeypatch):
    """No map, nothing to close: tapping its X blind would land on whatever IS
    on screen."""
    taps, store = wired
    screen = Screen(**{"home/home_play_marker.png": [True],
                       "episode/episodemap_marker.png": [False]})
    monkeypatch.setattr(se, "find_named", screen.find)
    with pytest.raises(se.SwitchEpisodeError, match="did not open"):
        se.switch_episode(FakeDevice(), store, 2)
    assert se.MAP_CLOSE not in taps, taps


def test_a_successful_switch_does_not_tap_the_map_close(wired, monkeypatch):
    """Entering an Episode closes the map itself; an extra tap would land on the
    reloading home screen."""
    taps, store = wired
    screen = Screen(
        **{"home/home_play_marker.png": [True],
           "episode/episodemap_marker.png": [True],
           "episode/ep7_banner.png": [True],
           "episode/episodeenter_marker.png": [True]}
    )
    monkeypatch.setattr(se, "find_named", screen.find)
    se.switch_episode(FakeDevice(), store, 7)
    assert se.MAP_CLOSE not in taps, taps


def test_cleanup_checks_the_map_is_up_before_tapping_its_x(wired, monkeypatch):
    """The map can already be gone by the time a failure unwinds (the game closed
    it, a stray tap did). Tapping its X then lands on whatever IS on screen —
    (1841,75) on home is empty space today, but "blind tap on an unknown screen"
    is the exact class of bug this whole chain of fixes is about."""
    taps, store = wired
    # The map opens, the banner search fails, and the map is GONE by cleanup time.
    seen = {"n": 0}

    def find(frame, store_, name, threshold=0.82):
        if name == "episode/episodemap_marker.png":
            seen["n"] += 1
            # The marker is read exactly twice: once to confirm the map opened,
            # once by the cleanup. Present for the first, gone by the second.
            return _hit(seen["n"] == 1)
        if name == "home/home_play_marker.png":
            return _hit(True)
        if name == "episode/ep7_banner.png":
            return _hit(True)
        return _hit(False)

    monkeypatch.setattr(se, "find_named", find)
    with pytest.raises(se.SwitchEpisodeError, match="not found after"):
        se.switch_episode(FakeDevice(), store, 2)
    assert se.MAP_CLOSE not in taps, (
        f"tapped the map's X when no map was up: {taps}")


def test_the_close_coordinate_is_the_measured_one(wired):
    """Measured live 2026-08-20 on the stranded frame: (1841,75) took episodemap
    1.000 -> 0.173 and home_play 0.308 -> 1.000. A drifted value would tap the
    map's own content — top-right of the map is empty water, but the banners and
    the Episode button are close enough that a wrong guess acts rather than
    no-ops."""
    assert se.MAP_CLOSE == (1841, 75)


def test_the_reset_swipes_until_the_left_edge_stops_moving(wired, monkeypatch):
    """Live 2026-08-20: Episode 6 could not be reached and Episode 5 failed the
    same way on the restore an hour later, both with "not found after 6 swipes".
    Counting the swipes per attempt showed why — the reset stopped after 2 left
    swipes for Episode 6 while the attempts that WORKED reset with 3 or 4:

        ep2 LLLL RRR ok | ep3 LLLL RRR ok | ep4 LLL RR ok
        ep5 LLL R ok    | ep6 LL RRRRRR FAILED

    ep7_banner matches as soon as any part of it scrolls into view, so a reset
    can stop with the map still short of its actual left edge; the rightward
    search then starts past the target and walks away from it — exactly the
    failure LEFT_EDGE_MARKER's own comment describes. The stranded map frame
    confirms where it ended up: ep1 at 1.000 and ep2 at 0.946 on screen, i.e.
    the far RIGHT of a map whose left edge is ep7.

    Seeing the marker once is therefore not enough — the reset has to keep going
    until the marker's position stops changing."""
    taps, store = wired
    positions = iter([100, 300, 500, 500, 500])  # settles on the third read

    def find(frame, store_, name, threshold=0.82):
        if name == "home/home_play_marker.png":
            return _hit(True)
        if name == "episode/episodemap_marker.png":
            return _hit(True)
        if name == se.LEFT_EDGE_MARKER:
            x = next(positions, 500)
            return Match(found=True, score=1.0, x=x, y=100, w=10, h=10)
        if name in ("episode/ep2_banner.png", "episode/episodeenter_marker.png"):
            return _hit(True)
        return _hit(False)

    monkeypatch.setattr(se, "find_named", find)
    se.switch_episode(FakeDevice(), store, 2)
    lefts = [t for t in taps if t == ("swipe",)]
    assert len(lefts) >= 2, (
        f"the reset stopped on the marker's first appearance instead of waiting "
        f"for it to settle: {taps}")


def test_one_settled_read_is_not_enough(wired, monkeypatch):
    """A swipe that under-travels leaves two frames looking alike, so a single
    match-in-place would call the edge reached while the map is still short —
    the same premature stop, one read later."""
    taps, store = wired
    # Reads: 100, 104 (within tolerance but a fluke), then a real move to 400,
    # then it truly settles at 700/700.
    positions = iter([100, 104, 400, 700, 700, 700])

    def find(frame, store_, name, threshold=0.82):
        if name in ("home/home_play_marker.png", "episode/episodemap_marker.png",
                    "episode/ep2_banner.png", "episode/episodeenter_marker.png"):
            return _hit(True)
        if name == se.LEFT_EDGE_MARKER:
            return Match(found=True, score=1.0, x=next(positions, 700),
                         y=100, w=10, h=10)
        return _hit(False)

    monkeypatch.setattr(se, "find_named", find)
    se.switch_episode(FakeDevice(), store, 2)
    swipes = [t for t in taps if t == ("swipe",)]
    assert len(swipes) >= 4, (
        f"stopped on a single settled read — a fluke pair ended the reset while "
        f"the map was still moving: {len(swipes)} swipes")


def test_the_settle_tolerance_is_tighter_than_a_swipe(wired, monkeypatch):
    """A swipe moves the banner hundreds of px; the tolerance only exists to
    absorb template-match wobble. Wide enough and every read looks settled,
    which is the no-op version of this fix."""
    assert se.EDGE_SETTLE_PX <= 40, (
        f"EDGE_SETTLE_PX={se.EDGE_SETTLE_PX} would count a real swipe as "
        f"'not moving' — measured swipe travel is MAP_SWIPE_LEFT's "
        f"{abs(se.MAP_SWIPE_LEFT[0][0] - se.MAP_SWIPE_LEFT[1][0])}px of drag")
    assert se.EDGE_SETTLE_READS >= 2
