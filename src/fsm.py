"""FSM runner — the capture → perceive → act farm loop."""
from __future__ import annotations

import logging
import time

from .act import Actor
from .capture import grab
from .config import Config
from .device import Device
from .perceive import TemplateStore, find_named

log = logging.getLogger("netrunner.fsm")

_STOP = "__stop__"


class FsmError(RuntimeError):
    pass


class Runner:
    def __init__(self, cfg: Config, device: Device):
        self.cfg = cfg
        self.device = device
        self.store = TemplateStore(cfg.templates_dir)
        self.actor: Actor  # set in run()

    def run(self, *, dry_run: bool = False, max_cycles: int | None = None) -> None:
        self.actor = Actor(
            self.device, self.store,
            dry_run=dry_run, default_threshold=self.cfg.match_threshold,
        )
        state = self.cfg.start_state
        entered_at = time.monotonic()
        cycles = 0
        frame = None  # reused across pure-goto transitions; None = must re-grab
        log.info("start state=%s device=%s dry_run=%s", state, self.device.serial, dry_run)

        while True:
            if max_cycles is not None and cycles >= max_cycles:
                log.info("reached max_cycles=%d, stopping", max_cycles)
                return
            cycles += 1

            spec = self.cfg.states[state]
            if frame is None:
                frame = grab(self.device)
            marker = spec["detect"]
            m = find_named(frame, self.store, marker, self.cfg.match_threshold)
            log.debug("state=%s detect=%s found=%s score=%.2f",
                      state, marker, m.found, m.score)

            if m.found:
                entered_at = time.monotonic()
                next_state, acted = self._run_actions(spec.get("on_match", []), frame, state)
                if acted:
                    frame = None  # taps/waits changed the screen -> stale
                if next_state == _STOP:
                    log.info("stop action reached, ending run")
                    return
                if next_state is not None:
                    state = next_state
                    continue
            else:
                next_state, acted = self._handle_absent(state, spec, entered_at, frame)
                if acted:
                    frame = None
                if next_state == _STOP:
                    return
                if next_state is not None:
                    state = next_state
                    entered_at = time.monotonic()
                    continue

            frame = None  # sleeping -> screen will have moved on
            time.sleep(self.cfg.poll_ms / 1000)

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
            result = self.actor.run(action, frame)
            if result is not None:
                return result, acted  # goto target or _STOP
        return None, acted

    def _handle_absent(
        self, state: str, spec: dict, entered_at: float, frame
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
          2. on_absent present -> run it (dict goto, or the action list).
          3. otherwise stay put -> main loop sleeps and re-polls, tolerating brief
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

        if isinstance(on_absent, list):
            return self._run_actions(on_absent, frame, state)

        if goto is not None and goto != state:
            log.debug("state '%s' marker absent -> goto '%s'", state, goto)
            return goto, False

        return None, False
