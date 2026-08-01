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
    #: this, one hiccup killed a multi-hour farm run. On RAM-starved machines
    #: the emulator can freeze for 5-10s at a time, longer than the old 2s max
    #: backoff covered, so a stall there raced past all 3 attempts and surfaced
    #: as a fatal AdbError mid-run.
    retries: int = 4
    retry_backoff_s: float = 1.5

    def __init__(self, serial: str, adb: str = "adb", timeout: float = 15.0):
        self.serial = serial
        self.adb = adb
        self.timeout = timeout
        self._persistent_shell: subprocess.Popen | None = None

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
        if isinstance(last_err, AdbError):
            raise last_err
        # MemoryError (or anything else non-adb) must still surface as AdbError:
        # the FSM's fail-streak tolerance only catches AdbError, so a bare
        # MemoryError from a tap would kill a whole run — the exact class of
        # crash the retry loop above exists to survive. (The capture path was
        # already shielded by grab(); the tap path was not.)
        raise AdbError(
            f"adb failed after {self.retries + 1} attempts "
            f"({type(last_err).__name__}): {' '.join(cmd)}"
        ) from last_err

    def shell(self, *args: str) -> str:
        """Run `adb shell <args>` and return decoded stdout."""
        return self._run(["shell", *args], binary=False)  # type: ignore[return-value]

    def exec_out(self, *args: str) -> bytes:
        """Run `adb exec-out <args>` and return raw stdout bytes (no line-ending mangling)."""
        return self._run(["exec-out", *args], binary=True)  # type: ignore[return-value]

    # --- persistent shell (fast tap for tight loops) --------------------------

    def _ensure_persistent_shell(self) -> subprocess.Popen | None:
        """Open (or reuse) a long-lived `adb shell`, or None if it can't start.

        Spawning `adb -s <serial> shell input tap x y` per call measures ~45ms —
        almost all of it process/adb-server overhead, not the tap itself. Piping
        commands into one shell's stdin instead measures ~9.5ms, which matters
        for fsm.py's "dodge" state: a detect-jump cycle has to fit inside a
        pit's ~1.5-2s window, and spawn overhead alone eats a third of that
        budget. Only worth this complexity for that tight loop — every other
        caller keeps using shell()/exec_out(), which is simpler and already
        proven reliable.
        """
        if self._persistent_shell is not None and self._persistent_shell.poll() is None:
            return self._persistent_shell
        try:
            proc = subprocess.Popen(
                [self.adb, "-s", self.serial, "shell"],
                stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except (FileNotFoundError, OSError) as e:
            logger.warning("could not open persistent shell, falling back to spawn: %s", e)
            self._persistent_shell = None
            return None
        self._persistent_shell = proc
        return proc

    def fast_tap(self, x: int, y: int) -> None:
        """Tap via the persistent shell; falls back to shell() if that fails.

        Fire-and-forget: no return code or stderr comes back over this path
        (writing to a live shell's stdin, not waiting on a fresh process exit),
        so a tap the device itself rejects would not surface as an AdbError
        here. That trade is what buys the speed — see _ensure_persistent_shell.
        A dead pipe (the shell process exited) is detected before the write and
        triggers the same one-shot fallback as a failed open.
        """
        proc = self._ensure_persistent_shell()
        if proc is not None:
            try:
                proc.stdin.write(f"input tap {x} {y}\n".encode())
                proc.stdin.flush()
                return
            except (BrokenPipeError, OSError) as e:
                logger.warning("persistent shell write failed, falling back to spawn: %s", e)
                self._persistent_shell = None
        self.shell("input", "tap", str(x), str(y))

    def close_persistent_shell(self) -> None:
        """Terminate the persistent shell, if one is open. Safe to call anytime."""
        if self._persistent_shell is not None:
            try:
                self._persistent_shell.stdin.close()
            except OSError:
                pass
            self._persistent_shell.terminate()
            self._persistent_shell = None

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
    except subprocess.TimeoutExpired as e:
        # A hung adb daemon must surface as AdbError like every other failure —
        # callers catch AdbError, not a raw TimeoutExpired traceback.
        raise AdbError(f"adb connect {address} timed out after {timeout:.0f}s") from e
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
    except subprocess.TimeoutExpired as e:
        raise AdbError(f"adb devices timed out after {timeout:.0f}s") from e
    serials = []
    for line in proc.stdout.splitlines()[1:]:  # skip "List of devices attached"
        parts = line.split()
        if len(parts) == 2 and parts[1] == "device":
            serials.append(parts[0])
    return serials
