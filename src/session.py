"""Restart the game mid-farm so no single session runs for hours on end.

A process that plays without interruption for twelve hours does not look like a
person playing. Periodically force-stopping and relaunching the app breaks the
session into human-sized chunks; cookierun-classic-bot does the same every
1.5-3h (bot.py:179-192).

Restarting is the easy half. The hard half is knowing the game actually came
back: `am start` returns success while the app crashes a second later on a
RAM-tight host, and the FSM would then poll a dead screen until the livelock
warning fires. So a restart is only accepted after the process has been seen
alive across several spaced checks.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from .device import AdbError, Device

log = logging.getLogger("netrunner.session")

#: Cookie Run: OvenBreak — the package every config targets.
DEFAULT_PACKAGE = "com.devsisters.crg"

#: Seconds to let the process die before relaunching. force-stop returns
#: immediately but the process group takes a moment to actually go.
STOP_SETTLE_S = 15.0
#: Seconds after launch before the first liveness check — below this the process
#: may not have appeared in `pidof` yet even on a healthy start.
LAUNCH_SETTLE_S = 15.0
#: Spaced liveness checks that must all pass. A launch that crashes tends to do
#: so within the first minute, which is what these cover.
STABILITY_CHECKS = 3
STABILITY_GAP_S = 20.0
#: Relaunch attempts before giving up and letting the caller alert.
MAX_ATTEMPTS = 5
RETRY_GAP_S = 5.0


class SessionError(RuntimeError):
    pass


@dataclass
class Restarter:
    """Knows how to bring `package` back up on `device`.

    `start_app` is injected because the FSM has no LDPlayer context: main.py
    passes a closure over launcher._start_app (ldconsole runapp, with an
    `am start` fallback) when --launch was used, and otherwise this falls back
    to `am start` alone — which is all a plain adb connection can do.
    """

    device: Device
    package: str = DEFAULT_PACKAGE
    start_app: object = None  # Callable[[], None] | None

    def is_running(self) -> bool:
        try:
            return bool(self.device.shell("pidof", self.package).strip())
        except AdbError as e:
            # An adb hiccup is not proof the app died; treat it as unknown-alive
            # and let the next spaced check decide.
            log.warning("pidof failed, assuming still up: %s", e)
            return True

    def force_stop(self) -> None:
        log.info("force-stopping %s", self.package)
        self.device.shell("am", "force-stop", self.package)

    def _launch(self) -> None:
        if self.start_app is not None:
            self.start_app()
            return
        out = self.device.shell("cmd", "package", "resolve-activity", "--brief", self.package)
        activity = out.strip().splitlines()[-1].strip()
        if "/" not in activity:
            raise SessionError(
                f"cannot resolve a launcher activity for {self.package} "
                f"(got {activity!r}) — pass --launch so ldconsole can start it"
            )
        self.device.shell("am", "start", "-n", activity)

    def _stable(self) -> bool:
        """True when the process survives every spaced check."""
        for i in range(1, STABILITY_CHECKS + 1):
            time.sleep(STABILITY_GAP_S)
            if not self.is_running():
                log.warning("%s died during stability check %d/%d",
                            self.package, i, STABILITY_CHECKS)
                return False
            log.info("stability check %d/%d passed", i, STABILITY_CHECKS)
        return True

    def restart(self) -> None:
        """Force-stop, relaunch, and verify. Raises SessionError if it never sticks."""
        self.force_stop()
        time.sleep(STOP_SETTLE_S)

        for attempt in range(1, MAX_ATTEMPTS + 1):
            log.info("relaunching %s (attempt %d/%d)", self.package, attempt, MAX_ATTEMPTS)
            try:
                self._launch()
            except (AdbError, SessionError) as e:
                log.warning("launch attempt %d failed: %s", attempt, e)
            else:
                time.sleep(LAUNCH_SETTLE_S)
                if self.is_running() and self._stable():
                    log.info("%s is back up and stable", self.package)
                    return
            if attempt < MAX_ATTEMPTS:
                time.sleep(RETRY_GAP_S)

        raise SessionError(
            f"could not get {self.package} to stay running after {MAX_ATTEMPTS} attempts"
        )
