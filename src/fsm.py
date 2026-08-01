"""FSM runner — the capture → perceive → act farm loop."""
from __future__ import annotations

import logging
import random
import time
from pathlib import Path

import cv2

from .act import ActError, Actor
from .alert import send_alert, send_alert_with_image
from .capture import grab
from .config import Config, detect_names
from .device import AdbError, Device
from .perceive import Match, PerceiveError, TemplateStore, find_named
from .session import Restarter, SessionError

log = logging.getLogger("netrunner.fsm")

_STOP = "__stop__"

# Consecutive cycles allowed to fail with an adb error before we give up. Device
# retries already cover a brief stall; this covers a longer one (the emulator
# swapping, a heavy level load) so a multi-hour farm survives it instead of
# dying on one timed-out tap.
_ADB_FAIL_TOLERANCE = 5

# consecutive polls stuck on the exact same state before we warn it looks like
# a livelock (e.g. an on_absent chain ping-ponging between states forever, or
# a rescue loop that never resolves). Deliberately generous so long, expected
# waits (heart regen, roll animation) don't false-positive.
_STUCK_STATE_WARN_CYCLES = 100

# Seconds the loop may go without reaching ANY progress state before the screen
# is declared unrecognised and `no_progress_goto` fires. The existing livelock
# detectors both ask "did the bot stop?" — they stayed silent for 13h on
# 2026-07-31 while the bot jumped 389 times into an unrecognised News popup,
# because state kept changing (so same_state_streak reset) and jump/slide count
# as actions (so no_act_streak reset). This one asks the useful question
# instead: "is any of it getting anywhere?" Opt-in per config via
# `progress_states` + `no_progress_goto`.
_NO_PROGRESS_DEFAULT_S = 300

# Extra seconds a recovery gets before the watchdog may judge it. `restart_app`
# plus the relogin chain measured 99s live (2026-08-01), which is longer than a
# tight `no_progress_s` — without this the watchdog fires again while the restart
# is still in flight and stacks another one on top of it.
_RECOVERY_GRACE_S = 180

# Consecutive cycles allowed to fail with a perceive-layer OOM (matchTemplate
# alloc failing on a RAM-starved host) before we give up, mirrors
# _ADB_FAIL_TOLERANCE. Below this we cooldown-sleep and retry rather than crash.
_PERCEIVE_FAIL_TOLERANCE = 5

# Cooldown (seconds) after an OOM'd detect cycle, scaled by how many have hit in
# a row. A tight host won't free memory in one poll interval — backing off gives
# other processes (LDPlayer itself) room to release before we hammer it again,
# instead of retrying at the normal poll cadence and thrashing an already-tight host.
_PERCEIVE_FAIL_COOLDOWN_S = 10


class FsmError(RuntimeError):
    pass


class Runner:
    def __init__(self, cfg: Config, device: Device, *,
                 webhook_url: str | None = None,
                 unknown_dir: str | Path = "unknown_screens",
                 restarter: Restarter | None = None):
        self.cfg = cfg
        self.device = device
        self.store = TemplateStore(cfg.templates_dir)
        self.actor: Actor  # set in run()
        self.webhook_url = webhook_url
        self.unknown_dir = Path(unknown_dir)
        # Injected so the FSM needs no LDPlayer knowledge; built by main.py when
        # the config asks for session resets.
        self.restarter = restarter

    def run(self, *, dry_run: bool = False, max_cycles: int | None = None) -> None:
        self.actor = Actor(
            self.device, self.store,
            dry_run=dry_run, default_threshold=self.cfg.match_threshold,
        )
        # `restart_app` actions cycle the process through the same Restarter the
        # scheduled resets use, so a config gets one without its own plumbing.
        self.actor.restarter = self.restarter
        state = self.cfg.start_state
        entered_at = time.monotonic()
        state_entered_at = time.monotonic()  # reset only when `state` changes
        cycles = 0
        same_state_streak = 0
        stuck_alerted = False
        absent_streak = 0        # consecutive absent polls in the current state
        adb_fail_streak = 0      # consecutive cycles lost to adb errors
        perceive_fail_streak = 0  # consecutive cycles lost to perceive-layer OOM
        no_act_streak = 0        # consecutive polls without any screen-affecting action
        no_act_states: set[str] = set()
        no_act_alerted = False
        # Wall-clock since the loop last reached a state the config calls progress.
        # Unlike the two streak counters this survives both state churn and busy
        # tapping, which is exactly the blind spot the News livelock lived in.
        last_progress_at = time.monotonic()
        no_progress_s = self.cfg.no_progress_s
        progress_watchdog = (self.cfg.no_progress_goto is not None
                             and bool(self.cfg.progress_states))
        # Consecutive fires with no progress in between. The cheap recovery runs
        # first; if it had worked, a progress state would have reset this to 0.
        no_progress_fires = 0
        if progress_watchdog:
            log.info("progress watchdog: %.0fs without %s -> goto '%s'",
                     no_progress_s, sorted(self.cfg.progress_states),
                     self.cfg.no_progress_goto)
        gotos_on_frame = 0       # pure-goto transitions served by the cached frame
        frame = None  # reused across pure-goto transitions; None = must re-grab
        # The first arrival at the inter-game state is the start of game 1, not
        # the end of game 0 — idling there would just delay the first run.
        inter_game_state = self.cfg.inter_game_state or self.cfg.start_state
        pending_inter_game_delay = self.cfg.inter_game_delay_s is not None
        # Side errands on a timer (sending lives, say). A bot that farms for
        # twelve hours and never touches the social screens is as distinctive as
        # one that never pauses. First run is a full interval out, so the farm
        # gets going before detouring anywhere.
        routine_due = {r["name"]: time.monotonic() + random.uniform(*r["interval_s"])
                       for r in self.cfg.periodic_routines}
        # Set when a restart re-enters start_state: that IS a fresh arrival even
        # if it is the same state name, so the entry-only hooks must not skip it.
        force_entry = False
        # True for the single arrival a restart produced: the errand/idle hooks
        # treat it as an entry (so after_reset routines fire) but the inter-game
        # idle must not spend its skip on it — the lap AFTER a reset is the one
        # that should run without idling.
        entered_by_reset = False
        for r in self.cfg.periodic_routines:
            log.info("routine '%s' every %s s at state '%s'%s", r["name"],
                     list(r["interval_s"]), r["at_state"] or inter_game_state,
                     " (+after reset)" if r["after_reset"] else "")
        reset_enabled = (self.cfg.session_reset_s is not None
                         and self.restarter is not None and not dry_run)
        reset_at_state = self.cfg.reset_at_state or inter_game_state
        session_started_at = time.monotonic()
        session_budget_s = (random.uniform(*self.cfg.session_reset_s)
                            if self.cfg.session_reset_s else 0.0)
        if self.cfg.session_reset_s is not None and not reset_enabled:
            log.info("session_reset_s set but resets are off (%s)",
                     "dry_run" if dry_run else "no restarter wired")
        elif reset_enabled:
            log.info("session reset in %.2fh (range %s) at state '%s'",
                     session_budget_s / 3600, list(self.cfg.session_reset_s), reset_at_state)
        log.info("start state=%s device=%s dry_run=%s", state, self.device.serial, dry_run)

        try:
            while True:
                if max_cycles is not None and cycles >= max_cycles:
                    log.info("reached max_cycles=%d, stopping", max_cycles)
                    return
                cycles += 1

                spec = self.cfg.states[state]
                try:
                    if frame is None:
                        frame = grab(self.device)
                        gotos_on_frame = 0
                    thr = float(spec.get("threshold", self.cfg.match_threshold))
                    m, matched = self._detect(frame, spec, thr)
                    log.debug("state=%s detect=%s found=%s score=%.2f",
                              state, matched, m.found, m.score)

                    prev_state = state
                    did_transition = False
                    mt = spec.get("match_timeout_ms")
                    if m.found and mt is not None \
                            and (time.monotonic() - state_entered_at) * 1000 >= mt:
                        # The marker is STILL on screen after the whole budget —
                        # the state's own taps aren't dismissing it. timeout_ms
                        # only fires on the absent path, so a stuck MATCH needs
                        # this separate escape (the old hand-written
                        # mb_reveal_retry chains existed to fake it).
                        target = self._match_timeout_target(spec)
                        if target is None or target == state:
                            raise FsmError(
                                f"state '{state}' still matched after "
                                f"{(time.monotonic() - state_entered_at) * 1000:.0f}ms "
                                f"(match_timeout {mt}ms) with no escape target"
                            )
                        log.warning("state '%s' still matched >= match_timeout %dms -> goto '%s'",
                                    state, mt, target)
                        state = target
                        did_transition = True
                        acted = False
                    elif m.found:
                        absent_streak = 0
                        entered_at = time.monotonic()
                        on_match = spec.get("on_match", [])
                        if isinstance(on_match, dict):  # per-template branch (detect list)
                            on_match = on_match[matched]
                        next_state, acted = self._run_actions(on_match, frame, state)
                        if next_state == _STOP:
                            log.info("stop action reached, ending run")
                            return
                        if next_state is not None:
                            state = next_state
                            did_transition = True
                    else:
                        absent_streak += 1
                        next_state, acted = self._handle_absent(
                            state, spec, entered_at, frame, absent_streak
                        )
                        if next_state == _STOP:
                            return
                        if next_state is not None:
                            state = next_state
                            entered_at = time.monotonic()
                            did_transition = True
                except AdbError as e:
                    adb_fail_streak += 1
                    log.warning("adb error on cycle %d (%d/%d before giving up): %s",
                                cycles, adb_fail_streak, _ADB_FAIL_TOLERANCE, e)
                    if adb_fail_streak >= _ADB_FAIL_TOLERANCE:
                        raise
                    frame = None  # whatever we had is unusable; re-grab next cycle
                    time.sleep(self.cfg.poll_delay_s())
                    continue
                except PerceiveError as e:
                    perceive_fail_streak += 1
                    log.warning("perceive error on cycle %d (%d/%d before giving up): %s",
                                cycles, perceive_fail_streak, _PERCEIVE_FAIL_TOLERANCE, e)
                    if perceive_fail_streak >= _PERCEIVE_FAIL_TOLERANCE:
                        raise FsmError(f"perceive layer failed {_PERCEIVE_FAIL_TOLERANCE} "
                                        f"cycles in a row: {e}")
                    cooldown = _PERCEIVE_FAIL_COOLDOWN_S * perceive_fail_streak
                    if perceive_fail_streak == 2:
                        send_alert(
                            self.webhook_url,
                            "NetRunner: host under memory pressure",
                            f"matchTemplate OOM'd {perceive_fail_streak} cycles in a row "
                            f"(device {self.device.serial}); cooling down {cooldown}s.",
                        )
                    frame = None  # whatever we had is unusable; re-grab next cycle
                    time.sleep(cooldown)
                    continue
                adb_fail_streak = 0
                perceive_fail_streak = 0

                if did_transition:
                    absent_streak = 0
                    # INFO (not debug) so an unattended run's rotated log carries
                    # the full state trace — tools/report_runs.py counts runs,
                    # boxes and stalls from these lines alone.
                    log.info("transition %s -> %s", prev_state, state)
                if acted:
                    frame = None  # taps/waits changed the screen -> stale
                    no_act_streak = 0
                    no_act_states.clear()
                    no_act_alerted = False
                else:
                    no_act_streak += 1
                    no_act_states.add(state)

                if state == prev_state:
                    same_state_streak += 1
                else:
                    same_state_streak = 0
                    stuck_alerted = False
                if state != prev_state or force_entry:
                    force_entry = False
                    state_entered_at = time.monotonic()
                    # Restart before the idle: both hang off state ENTRY, and a
                    # reset makes the idle pointless (the app just went away and
                    # came back, which is a far longer gap than 30-60s).
                    if reset_enabled and state == reset_at_state:
                        elapsed = time.monotonic() - session_started_at
                        if elapsed >= session_budget_s:
                            self._session_reset(elapsed)
                            session_started_at = time.monotonic()
                            session_budget_s = random.uniform(*self.cfg.session_reset_s)
                            log.info("next session reset in %.2fh", session_budget_s / 3600)
                            # Everything the loop believed about the screen is
                            # void — the app restarted behind it.
                            state = self.cfg.start_state
                            frame = None
                            absent_streak = same_state_streak = no_act_streak = 0
                            stuck_alerted = no_act_alerted = False
                            no_act_states.clear()
                            entered_at = state_entered_at = time.monotonic()
                            pending_inter_game_delay = True  # first lap after a reset
                            for r in self.cfg.periodic_routines:
                                if r["after_reset"]:
                                    # cookierun-bot sends lives right after every
                                    # app restart (pending_send_friend_life) —
                                    # bring the routine forward rather than
                                    # waiting out a fresh interval.
                                    routine_due[r["name"]] = time.monotonic()
                            # The re-entry into start_state is a fresh arrival even
                            # when it happens to be the state we reset from, so the
                            # entry-only hooks below must still see it next cycle —
                            # that is what lets an after_reset routine fire now
                            # instead of waiting out a fresh interval.
                            force_entry = entered_by_reset = True
                            continue

                    # Detour into a side errand whose timer is up. Same entry-only
                    # rule as the reset: never interrupt a run mid-flight.
                    routine = self._due_routine(state, inter_game_state, routine_due)
                    if routine is not None:
                        log.info("routine '%s' due -> goto '%s'",
                                 routine["name"], routine["goto"])
                        routine_due[routine["name"]] = (
                            time.monotonic() + random.uniform(*routine["interval_s"]))
                        state = routine["goto"]
                        state_entered_at = entered_at = time.monotonic()
                        absent_streak = 0
                        continue

                    # Idle between games, on ENTRY to the inter-game state only —
                    # checking every poll would re-fire the whole time we sat on
                    # home waiting for its marker to settle. `entered_by_reset`
                    # is consumed here: it only ever suppresses one arrival.
                    was_reset_arrival = entered_by_reset
                    entered_by_reset = False
                    if (self.cfg.inter_game_delay_s is not None
                            and state == inter_game_state
                            and not was_reset_arrival):
                        if pending_inter_game_delay:
                            pending_inter_game_delay = False  # first arrival = game 1
                        else:
                            delay = random.uniform(*self.cfg.inter_game_delay_s)
                            log.info("inter-game delay %.1fs before the next game (range %s)",
                                     delay, list(self.cfg.inter_game_delay_s))
                            time.sleep(delay)
                            frame = None  # the screen moved on while we idled
                            state_entered_at = time.monotonic()  # don't bill the idle
                                                                 # to match_timeout
                # Progress watchdog. Arriving at a progress state is the only
                # thing that clears it — not tapping, not changing state — so a
                # loop that jumps forever into an unrecognised popup trips it
                # even though it looks busy to every other counter here.
                if progress_watchdog:
                    if state in self.cfg.progress_states:
                        last_progress_at = time.monotonic()
                        no_progress_fires = 0  # recovery worked (or never ran)
                    else:
                        stalled_s = time.monotonic() - last_progress_at
                        if stalled_s >= no_progress_s:
                            no_progress_fires += 1
                            # A second fire means the first recovery produced no
                            # progress at all, so repeating it would just stall
                            # again — escalate if the config offers somewhere.
                            target = self.cfg.no_progress_goto
                            if no_progress_fires > 1 and self.cfg.no_progress_escalate_goto:
                                target = self.cfg.no_progress_escalate_goto
                            log.warning(
                                "no progress for %.0fs (fire #%d, last reached one of %s) — "
                                "screen is probably an unrecognised popup; recovering via '%s'",
                                stalled_s, no_progress_fires,
                                sorted(self.cfg.progress_states), target)
                            send_alert(
                                self.webhook_url,
                                "NetRunner: no progress",
                                f"No progress state reached in {stalled_s:.0f}s on device "
                                f"{self.device.serial} (fire #{no_progress_fires}) — "
                                f"recovering via `{target}`.",
                            )
                            self._archive_unknown(frame, state)
                            state = target
                            # Give the recovery a grace window of its own before
                            # it can be judged: restart_app + relogin measured
                            # 99s live on 2026-08-01, so a tight no_progress_s
                            # would fire again mid-restart and stack a second
                            # restart on top of the one still running.
                            last_progress_at = time.monotonic() + _RECOVERY_GRACE_S
                            frame = None
                            absent_streak = same_state_streak = 0
                            entered_at = state_entered_at = time.monotonic()
                            continue

                if same_state_streak >= _STUCK_STATE_WARN_CYCLES and not stuck_alerted:
                    log.warning("state '%s' unchanged for %d consecutive polls — possible livelock",
                                state, same_state_streak)
                    send_alert(
                        self.webhook_url,
                        "NetRunner: possible livelock",
                        f"State `{state}` unchanged for {same_state_streak} consecutive polls "
                        f"(device {self.device.serial}).",
                    )
                    self._archive_unknown(frame, state)
                    stuck_alerted = True
                # ping-pong livelock: states keep changing (so the same-state counter
                # never trips) but nothing on screen is ever acted on — e.g. a goto
                # cycle A→B→A→B waiting for a screen that never comes.
                if (no_act_streak >= _STUCK_STATE_WARN_CYCLES
                        and len(no_act_states) > 1 and not no_act_alerted):
                    cycle = " ⇄ ".join(sorted(no_act_states))
                    log.warning("no action for %d consecutive polls across states %s "
                                "— possible goto-cycle livelock", no_act_streak, cycle)
                    send_alert(
                        self.webhook_url,
                        "NetRunner: possible livelock",
                        f"No screen action for {no_act_streak} consecutive polls while "
                        f"cycling through `{cycle}` (device {self.device.serial}).",
                    )
                    self._archive_unknown(frame, state)
                    no_act_alerted = True

                if did_transition:
                    if frame is not None:
                        gotos_on_frame += 1
                        if gotos_on_frame > len(self.cfg.states):
                            # A pure-goto chain longer than the state count must have
                            # revisited a state on the SAME cached frame — matching is
                            # deterministic, so it would spin on that stale frame
                            # forever. Re-grab and pace to the poll cadence instead.
                            log.debug("pure-goto chain revisited a state on one frame "
                                      "-> re-grab + sleep")
                            frame = None
                            time.sleep(self.cfg.poll_delay_s())
                    continue

                frame = None  # sleeping -> screen will have moved on
                time.sleep(self.cfg.poll_delay_s())
        except FsmError as e:
            log.error("fatal: %s", e)
            send_alert(
                self.webhook_url,
                "NetRunner: bot crashed",
                f"```{e}```\nlast state: `{state}` (device {self.device.serial})",
                critical=True,
            )
            raise
        except AdbError as e:
            log.error("adb unusable after %d consecutive failures: %s",
                      _ADB_FAIL_TOLERANCE, e)
            send_alert(
                self.webhook_url,
                "NetRunner: lost the emulator",
                f"```{e}```\nadb failed {_ADB_FAIL_TOLERANCE} cycles in a row; "
                f"last state: `{state}` (device {self.device.serial})",
                critical=True,
            )
            raise

    def _due_routine(self, state: str, inter_game_state: str,
                     due: dict[str, float]) -> dict | None:
        """The first routine whose timer is up and whose safe state we just entered."""
        now = time.monotonic()
        for r in self.cfg.periodic_routines:
            if state != (r["at_state"] or inter_game_state):
                continue
            if now >= due[r["name"]]:
                return r
        return None

    def _session_reset(self, elapsed_s: float) -> None:
        """Restart the app so no session runs for hours unbroken.

        Failure is fatal-by-alert: if the game will not come back, farming a
        dead screen is worse than stopping, so SessionError propagates.
        """
        log.info("session reset after %.2fh — restarting the app", elapsed_s / 3600)
        send_alert(
            self.webhook_url,
            "NetRunner: session reset",
            f"Restarting the app after {elapsed_s / 3600:.2f}h "
            f"(device {self.device.serial}).",
        )
        try:
            self.restarter.restart()
        except SessionError as e:
            send_alert(
                self.webhook_url,
                "NetRunner: app will not restart",
                f"```{e}```\ndevice {self.device.serial}",
                critical=True,
            )
            raise FsmError(f"session reset failed: {e}") from e

    def _archive_unknown(self, frame, state: str) -> None:
        """Save the screen the loop is stuck on + push it to Discord.

        Piggybacks the livelock alerts' one-shot flags, so it fires once per
        stuck episode. The saved PNG is the raw material for the next popup
        template (crop it, add a probe state) — and for the first real captcha
        frame. Best-effort: archiving must never crash the run.
        """
        try:
            if frame is None:
                frame = grab(self.device)
            self.unknown_dir.mkdir(parents=True, exist_ok=True)
            path = self.unknown_dir / f"{time.strftime('%Y%m%d_%H%M%S')}_{state}.png"
            cv2.imwrite(str(path), frame)
            log.info("archived unrecognized screen -> %s", path)
            send_alert_with_image(
                self.webhook_url,
                "NetRunner: unrecognized screen",
                f"Loop stuck around `{state}` (device {self.device.serial}) — "
                f"frame archived to `{path.name}` for template cropping.",
                path,
            )
        except Exception as e:  # noqa: BLE001 — observability must not kill the farm
            log.warning("could not archive unknown screen: %s", e)

    @staticmethod
    def _match_timeout_target(spec: dict) -> str | None:
        """Escape state for a stuck MATCH: explicit on_match_timeout goto wins,
        else fall back to the on_absent goto (both screens lead the same way out)."""
        omt = spec.get("on_match_timeout")
        if isinstance(omt, dict) and omt.get("goto"):
            return omt["goto"]
        oa = spec.get("on_absent")
        if isinstance(oa, dict):
            return oa.get("goto")
        if isinstance(oa, list):
            return next((a.get("state") for a in oa if a.get("type") == "goto"), None)
        return None

    def _detect(self, frame, spec: dict, threshold: float) -> tuple[Match, str]:
        """Match the state's template(s) against the frame.

        `detect` is one filename or a list (any-of: templates are tried in order,
        first found wins — this is what lets one state watch for several popups
        instead of a chain of single-detect probe states). Returns the found match
        and its template name, or the best-scoring miss for logging.
        """
        best: Match | None = None
        best_name = ""
        for name in detect_names(spec):
            m = find_named(frame, self.store, name, threshold)
            if m.found:
                return m, name
            if best is None or m.score > best.score:
                best, best_name = m, name
        if best is None:
            # No detect names at all — validation normally rejects this, but a
            # tool that patches states post-load (run_toggle) can strip them;
            # an empty miss keeps the loop alive instead of AttributeError.
            return Match(found=False, score=0.0, x=0, y=0, w=0, h=0), best_name
        return best, best_name

    def _run_actions(self, actions: list[dict], frame, state: str) -> tuple[str | None, bool]:
        """Execute actions. Returns (goto_target_or_None, acted).

        `acted` is True when any screen-affecting action ran (tap/swipe/wait/jump/
        key) — the caller must then drop its cached frame. A pure goto/stop chain
        leaves the screen untouched, so the same capture stays valid; this is what
        lets the probe chain (5-6 detect-only states) run on ONE grab (~335ms each
        on LDPlayer) instead of re-capturing per state.
        """
        acted = False
        for action in actions:
            if action.get("type") not in ("goto", "stop"):
                acted = True
            try:
                result = self.actor.run(action, frame)
            except ActError as e:
                # A tap_template whose target vanished between the detect and the
                # tap (a prompt that auto-dismissed, an animation finishing) is a
                # missed opportunity, not a fatal error — skip the rest of this
                # action list and let the next poll re-read the screen.
                log.warning("action failed in state '%s', skipping rest: %s", state, e)
                return None, acted
            if result == Actor.UNSURE:
                # The action refused to answer (an unreadable card puzzle). Its
                # own bail_goto says where that leaves the loop — validation has
                # already checked the state exists.
                target = action["bail_goto"]
                log.warning("action in state '%s' could not act confidently -> goto '%s'",
                            state, target)
                return target, acted
            if result is not None:
                return result, acted  # goto target or _STOP
        return None, acted

    def _handle_absent(
        self, state: str, spec: dict, entered_at: float, frame, absent_streak: int
    ) -> tuple[str | None, bool]:
        """Decide what to do when the current state's marker is NOT on screen.

        Resilience heart of the loop. Order matters: a hard timeout wins over the
        soft on_absent redirect, so a genuinely frozen screen fails loud instead
        of thrashing an on_absent target forever.

        `on_absent` accepts two shapes:
          - a dict {"goto": "state"} -> jump target
          - a list of actions [ {tap...}, {"type":"goto",...} ] -> run each; a goto
            action inside supplies the next state. Used for active polling (e.g.
            tapping the Cookie Relay icon every cycle while a run is in progress).

          1. timeout_ms elapsed -> stuck. Redirect via the on_absent target if
             there is one, else raise FsmError (better to stop than farm a dead screen).
          2. `absent_retries: N` and fewer than N absent polls so far -> stay put
             (optionally sleeping `absent_wait_ms` first). This replaces the old
             hand-written retry chains (state_2/_3/...) — the grace window before
             on_absent fires now lives in one state.
          3. on_absent present -> run it (dict goto, or the action list).
          4. otherwise stay put -> main loop sleeps and re-polls, tolerating brief
             transitions (loading spinners) without churn.
        """
        on_absent = spec.get("on_absent")
        timeout_ms = spec.get("timeout_ms")

        if isinstance(on_absent, dict):
            goto = on_absent.get("goto")
        elif isinstance(on_absent, list):
            goto = next((a.get("state") for a in on_absent if a.get("type") == "goto"), None)
        else:
            goto = None

        if timeout_ms is not None:
            elapsed_ms = (time.monotonic() - entered_at) * 1000
            if elapsed_ms >= timeout_ms:
                if goto is not None and goto != state:
                    log.warning("state '%s' stuck %.0fms >= timeout %dms -> goto '%s'",
                                state, elapsed_ms, timeout_ms, goto)
                    return goto, False
                raise FsmError(
                    f"state '{state}' stuck for {elapsed_ms:.0f}ms "
                    f"(timeout {timeout_ms}ms) with no on_absent target"
                )

        retries = int(spec.get("absent_retries", 0))
        if absent_streak <= retries:
            log.debug("state '%s' marker absent — retry %d/%d", state, absent_streak, retries)
            wait_ms = spec.get("absent_wait_ms")
            if wait_ms:
                time.sleep(int(wait_ms) / 1000)
                return None, True  # slept -> screen may have moved -> frame is stale
            return None, False

        if isinstance(on_absent, list):
            return self._run_actions(on_absent, frame, state)

        if goto is not None and goto != state:
            log.debug("state '%s' marker absent -> goto '%s'", state, goto)
            return goto, False

        return None, False
