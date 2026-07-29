"""Persistent logging + Discord webhook alerts for unattended bot runs."""
from __future__ import annotations

import json
import logging
import time
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

import requests

logger = logging.getLogger("netrunner.alert")

_ROTATE_WHEN = "H"
_ROTATE_INTERVAL = 1
_BACKUP_HOURS = 72


def setup_file_logging(log_dir: str | Path = "logs", verbose: bool = False) -> Path:
    """Add an hourly-rotating file handler alongside the existing console one.

    Active file is `logs/netrunner.log`; each hour it rolls to a timestamped
    backup (`netrunner.log.2026-07-10_14`), keeping the last `_BACKUP_HOURS`
    hours and deleting older ones automatically.
    """
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "netrunner.log"

    handler = TimedRotatingFileHandler(
        log_path,
        when=_ROTATE_WHEN,
        interval=_ROTATE_INTERVAL,
        backupCount=_BACKUP_HOURS,
        encoding="utf-8",
    )
    handler.suffix = "%Y-%m-%d_%H"
    handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
    return log_path


def send_alert(webhook_url: str | None, title: str, message: str, *, critical: bool = False) -> None:
    """POST a Discord embed to the webhook. Never raises — a dead webhook must not crash the bot."""
    if not webhook_url:
        return
    color = 0xE74C3C if critical else 0xF1C40F  # red vs yellow
    payload = {
        "embeds": [{
            "title": ("🔴 " if critical else "🟡 ") + title,
            "description": message,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }],
    }
    if critical:
        payload["content"] = "@here"
    try:
        requests.post(webhook_url, json=payload, timeout=10)
    except requests.RequestException as e:
        logger.warning("discord alert failed: %s", e)


def send_alert_with_image(
    webhook_url: str | None, title: str, message: str, image_path: str | Path, *, critical: bool = False
) -> None:
    """Same as send_alert but attaches a screenshot — used to archive unrecognized
    screens (candidate popups/bugs) to Discord so they can be reviewed/analyzed
    later without needing local disk access to the machine that captured them.
    """
    if not webhook_url:
        return
    image_path = Path(image_path)
    color = 0xE74C3C if critical else 0xF1C40F
    payload = {
        "embeds": [{
            "title": ("🔴 " if critical else "🟡 ") + title,
            "description": message,
            "color": color,
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "image": {"url": f"attachment://{image_path.name}"},
        }],
    }
    if critical:
        payload["content"] = "@here"
    try:
        with open(image_path, "rb") as f:
            requests.post(
                webhook_url,
                data={"payload_json": json.dumps(payload)},
                files={"file": (image_path.name, f, "image/png")},
                timeout=15,
            )
    except (requests.RequestException, OSError) as e:
        logger.warning("discord alert with image failed: %s", e)
