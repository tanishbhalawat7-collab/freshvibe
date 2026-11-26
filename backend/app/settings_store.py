"""Runtime settings stored in the database and editable from the Settings page."""
from __future__ import annotations

import ipaddress
import re
import threading
from typing import Any

from .config import config
from .database import session_scope
from .models import Setting

DEFAULTS: dict[str, Any] = {
    "camera_ip": config.CAMERA_IP,
    "camera_capture_port": config.CAMERA_CAPTURE_PORT,
    "camera_stream_port": config.CAMERA_STREAM_PORT,
    "camera_timeout_s": 8.0,
    "camera_retries": 3,
    "camera_monitor_interval_s": 30,
    # expiry status thresholds (days)
    "fresh_days": 30,  # > fresh_days remaining  -> Fresh; 1..fresh_days -> Expiring soon
    "notify_days": [30, 7, 1],
    # pipeline
    "auto_save_min_confidence": 0.75,
    "date_order": "DMY",  # how to read ambiguous 03/04/2026: DMY (India/EU) or MDY (US)
    "ai_enabled": True,
}

_lock = threading.Lock()
_cache: dict[str, Any] | None = None

_HOST_RE = re.compile(r"^(?=.{1,253}$)([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$")


class SettingsError(ValueError):
    pass


def _load() -> dict[str, Any]:
    global _cache
    with _lock:
        if _cache is None:
            data = dict(DEFAULTS)
            with session_scope() as db:
                for row in db.query(Setting).all():
                    if row.key in DEFAULTS:
                        data[row.key] = row.value
            _cache = data
        return dict(_cache)


def get_all() -> dict[str, Any]:
    return _load()


def get(key: str) -> Any:
    return _load()[key]


def validate_camera_host(host: str) -> str:
    host = (host or "").strip()
    host = re.sub(r"^https?://", "", host).split("/")[0]
    if ":" in host and host.count(":") == 1:  # strip a port someone pasted
        host = host.split(":")[0]
    if not host:
        raise SettingsError("Camera IP / hostname is required.")
    try:
        ip = ipaddress.ip_address(host)
        if not config.ALLOW_PUBLIC_CAMERA_IP and not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise SettingsError(
                f"{host} is a public address. The ESP32-CAM must stay on your LAN "
                "(set ALLOW_PUBLIC_CAMERA_IP=true only if you really know why)."
            )
        return str(ip)
    except ValueError as exc:
        if isinstance(exc, SettingsError):
            raise
    if not _HOST_RE.match(host):
        raise SettingsError(f"'{host}' is not a valid IP address or hostname.")
    return host


def update(changes: dict[str, Any]) -> dict[str, Any]:
    global _cache
    clean: dict[str, Any] = {}
    for key, value in changes.items():
        if key not in DEFAULTS:
            raise SettingsError(f"Unknown setting '{key}'.")
        if key == "camera_ip":
            value = validate_camera_host(str(value))
        elif key in {"camera_capture_port", "camera_stream_port"}:
            value = int(value)
            if not 1 <= value <= 65535:
                raise SettingsError(f"{key} must be 1-65535.")
        elif key == "camera_timeout_s":
            value = float(value)
            if not 1 <= value <= 60:
                raise SettingsError("camera_timeout_s must be between 1 and 60 seconds.")
        elif key == "camera_retries":
            value = int(value)
            if not 1 <= value <= 10:
                raise SettingsError("camera_retries must be 1-10.")
        elif key == "camera_monitor_interval_s":
            value = int(value)
            if not (value == 0 or 10 <= value <= 3600):
                raise SettingsError("camera_monitor_interval_s must be 0 (off) or 10-3600.")
        elif key == "fresh_days":
            value = int(value)
            if not 1 <= value <= 3650:
                raise SettingsError("fresh_days must be 1-3650.")
        elif key == "notify_days":
            if not isinstance(value, list):
                raise SettingsError("notify_days must be a list of day counts.")
            value = sorted({int(v) for v in value if 1 <= int(v) <= 3650}, reverse=True)
            if not value:
                raise SettingsError("notify_days needs at least one value.")
        elif key == "auto_save_min_confidence":
            value = float(value)
            if not 0.3 <= value <= 1:
                raise SettingsError("auto_save_min_confidence must be 0.3-1.0.")
        elif key == "date_order":
            value = str(value).upper()
            if value not in {"DMY", "MDY"}:
                raise SettingsError("date_order must be DMY or MDY.")
        elif key == "ai_enabled":
            value = bool(value)
        clean[key] = value

    if "camera_capture_port" in clean or "camera_stream_port" in clean:
        cur = _load()
        cp = clean.get("camera_capture_port", cur["camera_capture_port"])
        sp = clean.get("camera_stream_port", cur["camera_stream_port"])
        if cp == sp:
            raise SettingsError(
                "Capture and stream ports must differ (CameraWebServer: capture on 80, stream on 81)."
            )

    with session_scope() as db:
        for key, value in clean.items():
            row = db.get(Setting, key)
            if row:
                row.value = value
            else:
                db.add(Setting(key=key, value=value))
    with _lock:
        _cache = None
    return get_all()
