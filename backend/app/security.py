"""Optional access-token protection.

When API_TOKEN is set (it must be, whenever the bridge is reachable through a
tunnel), API calls need either
  * header  Authorization: Bearer <token>   /   X-API-Key: <token>, or
  * the signed, HttpOnly session cookie issued by POST /api/auth/login
    (lets <img src> show the live stream and images).
State-changing requests authenticated by cookie must also carry
X-Requested-With: FreshVibe, which forces a CORS pre-flight (CSRF protection).
"""
from __future__ import annotations

import hashlib
import hmac
import time

from fastapi import HTTPException, Request

from .config import config

COOKIE = "fv_session"
SESSION_DAYS = 30
PUBLIC_PATHS = {"/api/health", "/api/auth/login", "/api/auth/status", "/api/auth/logout"}


def enabled() -> bool:
    return bool(config.API_TOKEN)


def _key() -> bytes:
    return hashlib.sha256(("freshvibe-session:" + config.API_TOKEN).encode()).digest()


def make_session() -> str:
    issued = str(int(time.time()))
    sig = hmac.new(_key(), issued.encode(), hashlib.sha256).hexdigest()
    return f"{issued}.{sig}"


def valid_session(value: str | None) -> bool:
    if not value or "." not in value:
        return False
    issued, sig = value.split(".", 1)
    good = hmac.new(_key(), issued.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, good):
        return False
    try:
        return time.time() - int(issued) < SESSION_DAYS * 86400
    except ValueError:
        return False


def token_ok(token: str | None) -> bool:
    return bool(token) and hmac.compare_digest(token.encode(), config.API_TOKEN.encode())


def check(request: Request) -> None:
    if not enabled() or request.url.path in PUBLIC_PATHS or request.method == "OPTIONS":
        return
    auth = request.headers.get("authorization", "")
    bearer = auth[7:].strip() if auth.lower().startswith("bearer ") else None
    if token_ok(bearer) or token_ok(request.headers.get("x-api-key")):
        return
    if valid_session(request.cookies.get(COOKIE)):
        if request.method not in ("GET", "HEAD") and request.headers.get("x-requested-with") != "FreshVibe":
            raise HTTPException(403, detail={"code": "csrf", "message": "Missing X-Requested-With header."})
        return
    raise HTTPException(401, detail={"code": "auth_required",
                                     "message": "This Fresh Vibe bridge requires an access token."})
