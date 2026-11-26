"""Deployment configuration, read from environment variables (.env supported).

Runtime-editable settings (camera IP, thresholds, ...) live in the database
(see settings_store.py). Values here are deployment/secret settings only.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
load_dotenv(ROOT_DIR / ".env")


def _bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def _list(name: str, default: str = "") -> list[str]:
    raw = os.getenv(name, default)
    return [x.strip().rstrip("/") for x in raw.split(",") if x.strip()]


class Config:
    # --- server ---
    HOST: str = os.getenv("HOST", "127.0.0.1")
    PORT: int = int(os.getenv("PORT", "8000"))
    SSL_CERTFILE: str | None = os.getenv("SSL_CERTFILE") or None
    SSL_KEYFILE: str | None = os.getenv("SSL_KEYFILE") or None

    # --- storage ---
    DATA_DIR: Path = Path(os.getenv("DATA_DIR") or str(ROOT_DIR / "data"))
    DATABASE_URL: str = os.getenv("DATABASE_URL", "")  # default: sqlite in DATA_DIR

    # --- security ---
    # If set, every /api request (except /api/health) must send
    #   Authorization: Bearer <API_TOKEN>   or   X-API-Key: <API_TOKEN>
    # REQUIRED whenever the bridge is reachable from outside your LAN (tunnel).
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    # Exact origins allowed for cross-origin calls (when the frontend is hosted
    # elsewhere, e.g. https://freshvibe.vercel.app). Same-origin needs nothing.
    CORS_ORIGINS: list[str] = _list("CORS_ORIGINS")

    # --- camera defaults (first run only; then edited in Settings) ---
    CAMERA_IP: str = os.getenv("CAMERA_IP", "192.168.1.65")
    CAMERA_CAPTURE_PORT: int = int(os.getenv("CAMERA_CAPTURE_PORT", "80"))
    CAMERA_STREAM_PORT: int = int(os.getenv("CAMERA_STREAM_PORT", "81"))
    # Only private/LAN camera addresses are accepted unless this is true.
    ALLOW_PUBLIC_CAMERA_IP: bool = _bool("ALLOW_PUBLIC_CAMERA_IP", False)

    # --- OCR ---
    TESSERACT_CMD: str = os.getenv("TESSERACT_CMD", "")  # e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe
    OCR_LANG: str = os.getenv("OCR_LANG", "eng")

    # --- product database lookups ---
    ENABLE_ONLINE_LOOKUP: bool = _bool("ENABLE_ONLINE_LOOKUP", True)
    LOOKUP_USER_AGENT: str = os.getenv(
        "LOOKUP_USER_AGENT", "FreshVibe/1.0 (smart expiry tracker; contact: you@example.com)"
    )

    # --- AI vision (optional) ---
    # "anthropic", "openai" or "" (disabled). Without a key the AI step is
    # reported as "not configured" -- never simulated.
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "").strip().lower()
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL: str = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5-5")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    AI_TIMEOUT_S: float = float(os.getenv("AI_TIMEOUT_S", "45"))


config = Config()
config.DATA_DIR.mkdir(parents=True, exist_ok=True)
(config.DATA_DIR / "images").mkdir(parents=True, exist_ok=True)
