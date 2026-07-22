"""ADB device wrapper — connect, enumerate, run shell/binary commands."""
from __future__ import annotations

import logging
import subprocess
import time

logger = logging.getLogger("netrunner.device")


class AdbError(RuntimeError):
    pass


class Device:
    """One ADB target (an LDPlayer instance). Wraps `adb -s <serial> ...`."""

    #: A busy emulator (level load, GC pause) can stall a single adb command for
    #: seconds. Those stalls are transient, so retry before giving up — without
    #: this, one hiccup killed a multi-hour farm run.
    retries: int = 2
    retry_backoff_s: float = 1.0

    def __init__(self, serial: str, adb: str = "adb", timeout: float = 15.0):
        self.serial = serial
        self.adb = adb
        self.timeout = timeout

    # --- raw command runners -------------------------------------------------

    def _run(self, args: list[str], *, binary: bool) -> bytes | str:
        cmd = [self.adb, "-s", self.serial, *args]
        last_err: Exception | None = None
        for attempt in range(self.retries + 1):
            try:
                proc = subprocess.run(
                    cmd,
                    capture_output=True,
                    timeout=self.timeout,
                    text=not binary,
                )
            except FileNotFoundError as e:
                raise AdbError(f"adb not found on PATH (tried '{self.adb}')") from e
            except subprocess.TimeoutExpired as e:
                last_err = e
                logger.warning("adb timed out (attempt %d/%d): %s",
                               attempt + 1, self.retries + 1, " ".join(cmd))
            except MemoryError as e:
                # On RAM-starved machines (LDPlayer alone can eat 1.5-3GB), the
                # subprocess pipe's internal reader thread can fail to allocate
                # buffer space for one frame's output — usually transient as
                # other processes free memory a moment later. Retry with a
                # longer backoff instead of letting one bad capture kill the run.
                last_err = e
                logger.warning("adb hit MemoryError (attempt %d/%d), backing off: %s",
                               attempt + 1, self.retries + 1, " ".join(cmd))
                time.sleep(self.retry_backoff_s * 2 * (attempt + 1))
                continue
            else:
                if proc.returncode == 0:
                    return proc.stdout
                err = (proc.stderr if isinstance(proc.stderr, str)
                       else proc.stderr.decode(errors="replace"))
                last_err = AdbError(
                    f"adb failed ({proc.returncode}): {' '.join(cmd)}\n{err.strip()}"
                )
                logger.warning("adb failed (attempt %d/%d): %s",
                               attempt + 1, self.retries + 1, err.strip())
            if attempt < self.retries:
                time.sleep(self.retry_backoff_s * (attempt + 1))

        if isinstance(last_err, subprocess.TimeoutExpired):
            raise AdbError(
                f"adb timed out after {self.retries + 1} attempts: {' '.join(cmd)}"
            ) from last_err
        raise last_err  # type: ignore[misc]

    def shell(self, *args: str) -> str:
        """Run `adb shell <args>` and return decoded stdout."""
        return self._run(["shell", *args], binary=False)  # type: ignore[return-value]

    def exec_out(self, *args: str) -> bytes:
        """Run `adb exec-out <args>` and return raw stdout bytes (no line-ending mangling)."""
        return self._run(["exec-out", *args], binary=True)  # type: ignore[return-value]

    # --- introspection -------------------------------------------------------

    def resolution(self) -> tuple[int, int]:
        """Screen size as (width, height)."""
        out = self.shell("wm", "size")
        # "Physical size: 1280x720"  (may also carry an "Override size:" line)
        line = next((l for l in out.splitlines() if "size:" in l.lower()), "")
        try:
            wh = line.split(":")[-1].strip()
            w, h = wh.lower().split("x")
            return int(w), int(h)
        except (ValueError, IndexError) as e:
            raise AdbError(f"cannot parse resolution from: {out!r}") from e


def connect(address: str, adb: str = "adb", timeout: float = 15.0) -> Device:
    """`adb connect <address>` then return a Device. `address` like 127.0.0.1:5555."""
    try:
        proc = subprocess.run(
            [adb, "connect", address],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise AdbError(f"adb not found on PATH (tried '{adb}')") from e
    out = (proc.stdout + proc.stderr).lower()
    if "cannot" in out or "failed" in out or "unable" in out:
        raise AdbError(f"connect failed for {address}: {proc.stdout.strip()}")
    return Device(address, adb=adb, timeout=timeout)


def list_devices(adb: str = "adb", timeout: float = 15.0) -> list[str]:
    """Serials of devices in the `device` state (skips offline/unauthorized)."""
    try:
        proc = subprocess.run(
            [adb, "devices"],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise AdbError(f"adb not found on PATH (tried '{adb}')") from e
    serials = []
    for line in proc.stdout.splitlines()[1:]:  # skip "List of devices attached"
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials
