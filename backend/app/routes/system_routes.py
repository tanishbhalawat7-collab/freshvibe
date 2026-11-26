from __future__ import annotations

import asyncio
import platform
import time
from collections import Counter
from datetime import date, datetime, timezone

import httpx
from fastapi import APIRouter, Body, Depends, Request, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from .. import ai_vision, barcode, expiry, ocr, products, security, settings_store
from ..camera import bridge
from ..config import config
from ..database import IS_SQLITE, engine, get_db
from ..errors import api_error
from ..lookup import CATEGORIES
from ..models import Notification, Product

router = APIRouter(prefix="/api", tags=["system"])
STARTED = time.time()
VERSION = "1.0.0"


@router.get("/health")
def health():
    return {"ok": True, "service": "fresh-vibe-backend", "version": VERSION,
            "uptime_s": int(time.time() - STARTED), "time": datetime.now(timezone.utc).isoformat(),
            "auth_required": security.enabled()}


# ------------------------------------------------------------------ auth
@router.get("/auth/status")
def auth_status(request: Request):
    return {"auth_required": security.enabled(),
            "authenticated": (not security.enabled()) or security.valid_session(request.cookies.get(security.COOKIE))}


@router.post("/auth/login")
def login(response: Response, request: Request, payload: dict = Body(...)):
    if not security.enabled():
        return {"ok": True, "auth_required": False}
    if not security.token_ok(str(payload.get("token", ""))):
        time.sleep(0.5)
        raise api_error(401, "bad_token", "Access token is not correct.")
    cross_site = bool(config.CORS_ORIGINS)
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    response.set_cookie(security.COOKIE, security.make_session(), max_age=security.SESSION_DAYS * 86400,
                        httponly=True, secure=https, samesite="none" if (cross_site and https) else "strict", path="/")
    return {"ok": True}


@router.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(security.COOKIE, path="/")
    return {"ok": True}


# -------------------------------------------------------------- settings
@router.get("/settings")
def get_settings():
    return {"settings": settings_store.get_all(), "categories": CATEGORIES, "ai": ai_vision.status(),
            "ocr_engine": ocr.engine_name(), "auth_required": security.enabled()}


@router.put("/settings")
def put_settings(payload: dict = Body(...)):
    try:
        new = settings_store.update(payload)
    except (settings_store.SettingsError, ValueError, TypeError) as exc:
        raise api_error(422, "invalid_settings", str(exc))
    if {"camera_ip", "camera_capture_port", "camera_stream_port"} & set(payload):
        bridge.reset_connection()
    return {"settings": new}


# ---------------------------------------------------------------- expiry
@router.get("/expiry/summary")
def expiry_summary(db: Session = Depends(get_db)):
    today = date.today()
    items = [products.to_dict(p, today) for p in db.query(Product).all()]
    counts = Counter(i["status"] for i in items)
    by_cat: dict[str, Counter] = {}
    for i in items:
        by_cat.setdefault(i["category"] or "Uncategorised", Counter())[i["status"]] += 1
    soon = sorted([i for i in items if i["status"] in ("expiring_soon", "expired")],
                  key=lambda i: i["days_left"])
    recent = sorted(items, key=lambda i: i["scanned_at"] or "", reverse=True)[:8]
    # expiries per month for the next 6 months
    months = []
    y, m = today.year, today.month
    for _ in range(6):
        key = f"{y:04d}-{m:02d}"
        months.append({"month": key, "count": sum(1 for i in items if (i["expiry_date"] or "").startswith(key))})
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return {
        "total": len(items), "total_units": sum(i["quantity"] or 1 for i in items),
        "fresh": counts["fresh"], "expiring_soon": counts["expiring_soon"],
        "expired": counts["expired"], "unknown": counts["unknown"],
        "thresholds": {"fresh_days": settings_store.get("fresh_days")},
        "categories": [{"category": k, "total": sum(v.values()), **dict(v)} for k, v in
                       sorted(by_cat.items(), key=lambda kv: -sum(kv[1].values()))],
        "attention": soon[:12], "recent": recent, "upcoming_by_month": months,
        "verification": dict(Counter(i["verification_status"] for i in items)),
    }


# --------------------------------------------------------- notifications
@router.get("/notifications")
def list_notifications(unread_only: bool = False, db: Session = Depends(get_db)):
    expiry.generate_notifications(db)
    q = db.query(Notification)
    if unread_only:
        q = q.filter(Notification.read_at.is_(None))
    rows = q.order_by(Notification.created_at.desc()).limit(200).all()
    items = sorted((expiry.notification_dict(n) for n in rows), key=lambda n: (n["read"], n["severity"]))
    return {"unread": sum(1 for n in items if not n["read"]), "items": items}


@router.post("/notifications/{nid}/read")
def read_notification(nid: int, db: Session = Depends(get_db)):
    n = db.get(Notification, nid)
    if not n:
        raise api_error(404, "notification_not_found", "No such notification.")
    n.read_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True}


@router.post("/notifications/read-all")
def read_all(db: Session = Depends(get_db)):
    db.query(Notification).filter(Notification.read_at.is_(None)).update(
        {Notification.read_at: datetime.now(timezone.utc)})
    db.commit()
    return {"ok": True}


# ----------------------------------------------------------- diagnostics
async def _timed(fn, *a):
    t0 = time.perf_counter()
    try:
        res = await fn(*a) if asyncio.iscoroutinefunction(fn) else await asyncio.to_thread(fn, *a)
    except Exception as exc:  # report, never hide
        res = {"ok": False, "error": f"{exc.__class__.__name__}: {exc}"}
    res["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return res


def _db_check():
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
        n = c.execute(text("SELECT COUNT(*) FROM products")).scalar()
    return {"ok": True, "engine": "SQLite" if IS_SQLITE else engine.dialect.name, "products": n,
            "url": str(engine.url).split("@")[-1] if not IS_SQLITE else str(engine.url)}


async def _lookup_check():
    if not config.ENABLE_ONLINE_LOOKUP:
        return {"ok": False, "error": "Online lookup disabled (ENABLE_ONLINE_LOOKUP=false)"}
    try:
        async with httpx.AsyncClient(timeout=6, headers={"User-Agent": config.LOOKUP_USER_AGENT}) as c:
            r = await c.get("https://world.openfoodfacts.org/api/v2/product/3017620422003.json",
                            params={"fields": "product_name"})
        return {"ok": r.status_code == 200, "detail": f"Open Food Facts HTTP {r.status_code}"}
    except httpx.HTTPError as exc:
        return {"ok": False, "error": f"Open Food Facts unreachable ({exc.__class__.__name__}). "
                                      "Barcodes still decode; product names will need AI or manual entry."}


async def _camera_check():
    return await bridge.health()


@router.get("/diagnostics")
async def diagnostics(request: Request):
    db_r, cam_r, bc_r, ocr_r, lk_r = await asyncio.gather(
        _timed(_db_check), _timed(_camera_check), _timed(barcode.self_test), _timed(ocr.self_test),
        _timed(_lookup_check))
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"
    host = request.url.hostname or ""
    return {
        "time": datetime.now(timezone.utc).isoformat(),
        "backend": {"ok": True, "version": VERSION, "python": platform.python_version(),
                    "uptime_s": int(time.time() - STARTED)},
        "database": db_r,
        "camera": cam_r,
        "barcode": bc_r,
        "ocr": ocr_r,
        "product_lookup": lk_r,
        "ai": ai_vision.status() | {"ok": ai_vision.status()["configured"], "optional": True},
        "security": {
            "https": https, "secure_context": https or host in ("localhost", "127.0.0.1", "::1"),
            "auth_required": security.enabled(), "cors_origins": config.CORS_ORIGINS,
            "warnings": [w for w in [
                None if (https or host in ("localhost", "127.0.0.1", "::1")) else
                "Served over plain HTTP on a non-localhost address. Use the HTTPS setup (see README) "
                "- browser notifications and phone cameras need a secure context.",
                None if security.enabled() or host in ("localhost", "127.0.0.1", "::1") else
                "API_TOKEN is not set. Anyone who can reach this server can use the camera and data.",
            ] if w],
        },
    }
