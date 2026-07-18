"""Auto-launch an LDPlayer instance and start Cookie Run before the FSM runs.

Wraps LDPlayer's `ldconsole.exe`: bring an instance up if it's down, wait for
its ADB to reach `device` state, then start the game and give it time to reach
the title/home screen. Everything here is best-effort and idempotent — if the
instance is already running or the app already foreground, the corresponding
step is a fast no-op, so `--launch` is safe to pass on every run.
"""
from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path

from .device import Device

logger = logging.getLogger("netrunner.launcher")

#: Cookie Run: OvenBreak. All configs target this package.
COOKIE_RUN_PACKAGE = "com.devsisters.crg"

#: adb port an instance answers on = ADB_PORT_BASE + 2*index (LDPlayer's scheme:
#: index 0 -> 5555, 1 -> 5557, ...). The console port (emulator-5554+2*index) is
#: a different number and is NOT what adb connect uses.
ADB_PORT_BASE = 5555


class LauncherError(RuntimeError):
    pass


def _ldconsole_path(adb_path: str) -> Path:
    """Locate ldconsole.exe. It sits next to adb.exe in every LDPlayer install,
    so try there first; when adb is just 'adb' on PATH (no directory), fall back
    to scanning the standard install roots for the newest LDPlayer*.
    """
    if adb_path and ("\\" in adb_path or "/" in adb_path):
        p = Path(adb_path).with_name("ldconsole.exe")
        if p.exists():
            return p

    roots = []
    for base in (r"C:\LDPlayer", r"D:\LDPlayer", r"C:\Program Files\LDPlayer"):
        b = Path(base)
        if b.exists():
            roots += [d for d in b.iterdir() if d.is_dir()]
    # newest install dir first (LDPlayer9 < LDPlayer14 by name is unreliable, so
    # prefer the one that actually has the binary; if several, latest mtime).
    for d in sorted(roots, key=lambda x: x.stat().st_mtime, reverse=True):
        cand = d / "ldconsole.exe"
        if cand.exists():
            return cand

    raise LauncherError(
        "ldconsole.exe not found. Pass --adb pointing at your LDPlayer adb.exe "
        r"(e.g. C:\LDPlayer\LDPlayer14\adb.exe) so ldconsole can be found beside it."
    )


def _ld(ldconsole: Path, *args: str, timeout: float = 30.0) -> str:
    proc = subprocess.run(
        [str(ldconsole), *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise LauncherError(
            f"ldconsole {' '.join(args)} failed (rc={proc.returncode}): "
            f"{proc.stderr.strip() or proc.stdout.strip()}"
        )
    return proc.stdout


def _is_running(ldconsole: Path, index: int) -> bool:
    """list2 row: index,name,topHwnd,binHwnd,android,pid,... — pid == -1 is down."""
    for line in _ld(ldconsole, "list2").splitlines():
        parts = line.split(",")
        if len(parts) >= 6 and parts[0].strip() == str(index):
            return parts[5].strip() not in ("-1", "")
    raise LauncherError(f"no LDPlayer instance with index {index} (check ldconsole list2)")


def address_for_index(index: int) -> str:
    return f"127.0.0.1:{ADB_PORT_BASE + 2 * index}"


def running_instances(ldconsole: Path) -> list[int]:
    """Indices of every LDPlayer instance currently up (pid != -1), in list order."""
    out = []
    for line in _ld(ldconsole, "list2").splitlines():
        parts = line.split(",")
        if len(parts) >= 6 and parts[0].strip().isdigit() and parts[5].strip() not in ("-1", ""):
            out.append(int(parts[0].strip()))
    return out


def resolve_index(adb_path: str, requested: int | None, hint_address: str | None) -> int:
    """Pick which instance --launch should target.

    Priority: an explicit --instance wins. Otherwise reuse whatever instance is
    ALREADY running (so we never spawn a second window next to a live one) —
    this is the common case where the user left one emulator open. Only when
    nothing is running do we fall back to the index implied by the address, or 0.
    A running instance is preferred over the config's stale device port, which
    is why this beats deriving from hint_address first.
    """
    if requested is not None:
        return requested
    ldconsole = _ldconsole_path(adb_path)
    up = running_instances(ldconsole)
    if len(up) == 1:
        logger.info("reusing the running LDPlayer instance %d", up[0])
        return up[0]
    if len(up) > 1:
        # several open — disambiguate by the requested address if it points at one
        if hint_address and ":" in hint_address:
            try:
                port = int(hint_address.rsplit(":", 1)[1])
                idx = (port - ADB_PORT_BASE) // 2
                if idx in up:
                    return idx
            except ValueError:
                pass
        logger.warning("multiple instances running %s; using %d "
                       "(set --instance to choose)", up, up[0])
        return up[0]
    # none running -> derive from address, else default 0
    if hint_address and ":" in hint_address:
        try:
            port = int(hint_address.rsplit(":", 1)[1])
            if port >= ADB_PORT_BASE:
                return (port - ADB_PORT_BASE) // 2
        except ValueError:
            pass
    return 0


def _wait_adb_ready(adb_path: str, address: str, boot_timeout: float) -> None:
    """Poll `adb connect` + getprop until the instance answers as a live device.

    A freshly launched instance shows up in `adb devices` as `offline` for a
    while, then `device`; and even then the Android side may still be booting.
    We gate on sys.boot_completed so the game launch doesn't race the boot.
    """
    deadline = time.time() + boot_timeout
    # Poll adb directly, NOT via Device.shell: during boot every call fails with
    # 'device offline', and Device's retry+warn would spam three warnings per
    # poll. Offline-until-ready is the expected path here, so keep it quiet.
    while time.time() < deadline:
        subprocess.run([adb_path, "connect", address], capture_output=True, text=True)
        try:
            proc = subprocess.run(
                [adb_path, "-s", address, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=10.0,
            )
            if proc.returncode == 0 and proc.stdout.strip() == "1":
                return
        except subprocess.TimeoutExpired:
            pass  # a hung getprop during boot — just retry
        time.sleep(2.0)
    raise LauncherError(
        f"{address} did not finish booting within {boot_timeout:.0f}s "
        "(raise --boot-timeout, or check the instance in LDPlayer)."
    )


def _app_foreground(dev: Device, package: str) -> bool:
    """True if `package` is the current foreground app (best-effort).

    No shell pipes: `adb shell a | grep b` runs the pipe on the HOST, not the
    device, so we pull the full dumpsys and match in Python instead.
    """
    try:
        out = dev.shell("dumpsys", "activity", "activities")
    except Exception:
        return False
    for line in out.splitlines():
        if ("topResumedActivity" in line or "ResumedActivity" in line
                or "mCurrentFocus" in line or "mFocusedApp" in line) and package in line:
            return True
    return False


def ensure_ready(
    index: int,
    adb_path: str,
    *,
    package: str = COOKIE_RUN_PACKAGE,
    boot_timeout: float = 120.0,
    app_settle_s: float = 25.0,
) -> str:
    """Bring instance `index` up and Cookie Run to the foreground.

    Returns the adb address to hand the FSM. Idempotent: skips launch when the
    instance already runs and skips runapp when the game is already foreground.
    """
    ldconsole = _ldconsole_path(adb_path)
    address = address_for_index(index)

    if _is_running(ldconsole, index):
        logger.info("LDPlayer instance %d already running (%s)", index, address)
    else:
        logger.info("launching LDPlayer instance %d ...", index)
        _ld(ldconsole, "launch", "--index", str(index))

    _wait_adb_ready(adb_path, address, boot_timeout)
    logger.info("instance %d booted, adb ready at %s", index, address)

    dev = Device(address, adb=adb_path, timeout=15.0)
    if _app_foreground(dev, package):
        logger.info("%s already in foreground", package)
    else:
        logger.info("starting %s ...", package)
        _start_app(ldconsole, index, dev, package)
        logger.info("waiting %.0fs for the game to reach home ...", app_settle_s)
        time.sleep(app_settle_s)

    return address


def _start_app(ldconsole: Path, index: int, dev: Device, package: str) -> None:
    """Foreground the game. Prefer ldconsole runapp (LDPlayer-native, no monkey
    dependency); fall back to `am start` via the app's launcher activity if the
    LDPlayer build lacks runapp. monkey is intentionally avoided — several
    LDPlayer images ship without it (`monkey: inaccessible or not found`).
    """
    try:
        _ld(ldconsole, "runapp", "--index", str(index), "--packagename", package)
        return
    except LauncherError as e:
        logger.warning("ldconsole runapp failed (%s); trying am start", e)
    try:
        out = dev.shell("cmd", "package", "resolve-activity", "--brief", package)
        activity = out.strip().splitlines()[-1].strip()
        if "/" in activity:
            dev.shell("am", "start", "-n", activity)
            return
    except Exception as e:
        logger.warning("am start fallback failed: %s", e)
    raise LauncherError(
        f"could not start {package}: ldconsole runapp and am start both failed. "
        "Open the game once manually, or check the package name."
    )
