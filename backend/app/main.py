"""Fresh Vibe backend + ESP32-CAM bridge.

Run:  python -m app            (from the backend/ folder; reads ../.env)
"""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from . import expiry, security
from .camera import bridge
from .config import ROOT_DIR, config
from .database import init_db, session_scope
from .routes import camera_routes, product_routes, scan_routes, system_routes

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("freshvibe")
FRONTEND = ROOT_DIR / "frontend"


async def _notification_loop():
    while True:
        try:
            with session_scope() as db:
                n = expiry.generate_notifications(db)
                if n:
                    log.info("created %d expiry notification(s)", n)
        except Exception:
            log.exception("notification job failed")
        await asyncio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    bridge.start()
    task = asyncio.create_task(_notification_loop())
    log.info("Fresh Vibe ready. Camera: %s", bridge.snapshot()["capture_url"])
    yield
    task.cancel()
    await bridge.stop()


app = FastAPI(title="Fresh Vibe - AI Smart Expiry Tracker", version=system_routes.VERSION, lifespan=lifespan,
              dependencies=[Depends(security.check)])

if config.CORS_ORIGINS:
    if "*" in config.CORS_ORIGINS:
        raise RuntimeError("CORS_ORIGINS must list exact origins; '*' is not allowed.")
    app.add_middleware(
        CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "X-API-Key", "Content-Type", "X-Requested-With"],
        expose_headers=["X-Image-Width", "X-Image-Height", "X-Capture-Ms", "X-Capture-Source"], max_age=600)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers.setdefault("X-Content-Type-Options", "nosniff")
    resp.headers.setdefault("Referrer-Policy", "same-origin")
    resp.headers.setdefault("X-Frame-Options", "DENY")
    if request.url.path.startswith("/api/"):
        resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ---------------------------------------------------------- JSON errors
def _err(status: int, code: str, message: str, hint: str = "", **extra):
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message, "hint": hint, **extra}})


@app.exception_handler(HTTPException)
async def http_exc(request: Request, exc: HTTPException):
    d = exc.detail
    if isinstance(d, dict):
        return _err(exc.status_code, d.get("code", "error"), d.get("message", "Error"), d.get("hint", ""),
                    **{k: v for k, v in d.items() if k not in ("code", "message", "hint")})
    code = {404: "not_found", 405: "method_not_allowed", 401: "auth_required"}.get(exc.status_code, "error")
    return _err(exc.status_code, code, str(d))


@app.exception_handler(RequestValidationError)
async def validation_exc(request: Request, exc: RequestValidationError):
    errs = [{"field": ".".join(str(x) for x in e.get("loc", [])), "message": e.get("msg")} for e in exc.errors()]
    return _err(422, "validation_error", "Request is not valid.", "", details=errs)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return _err(500, "internal_error", "Unexpected server error.", f"{exc.__class__.__name__}: {exc}")


for r in (system_routes.router, camera_routes.router, scan_routes.router, product_routes.router):
    app.include_router(r)


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE"], include_in_schema=False)
async def api_404(path: str):
    return _err(404, "not_found", f"No API endpoint /api/{path}.")


# ------------------------------------------------------------- frontend
# Served from the same origin as the API: no CORS, no mixed content, one tunnel.
if FRONTEND.exists():
    app.mount("/", StaticFiles(directory=FRONTEND, html=True), name="frontend")
