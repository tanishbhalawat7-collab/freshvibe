from __future__ import annotations

import httpx
from fastapi import APIRouter, Body, Depends
from fastapi.responses import Response, StreamingResponse
from sqlalchemy.orm import Session

from .. import settings_store
from ..camera import CameraError, StreamHub, add_log, bridge
from ..database import get_db
from ..errors import api_error
from ..models import CameraLog

router = APIRouter(prefix="/api/camera", tags=["camera"])


@router.get("/health")
async def camera_health():
    """Performs a real /capture request. 'connected' only if a valid JPEG came back."""
    return await bridge.health()


@router.get("/state")
async def camera_state():
    """Last known state without contacting the camera (cheap, for polling)."""
    return bridge.snapshot()


@router.post("/connect")
async def camera_connect(payload: dict | None = Body(default=None)):
    """Optionally set a new IP/ports, reset backoff, then run a real health check."""
    if payload:
        changes = {k: payload[k] for k in ("camera_ip", "camera_capture_port", "camera_stream_port") if k in payload}
        if changes:
            try:
                settings_store.update(changes)
            except settings_store.SettingsError as exc:
                raise api_error(422, "invalid_settings", str(exc))
            add_log("info", f"Camera settings changed: {changes}")
    bridge.reset_connection()
    return await bridge.health()


@router.get("/capture")
async def camera_capture():
    """Returns the JPEG captured from the ESP32-CAM (proxied, same-origin)."""
    try:
        res = await bridge.capture(reason="manual capture")
    except CameraError as ce:
        raise api_error(502 if ce.code != "timeout" else 504, ce.code, ce.message, ce.hint)
    return Response(res.jpeg, media_type="image/jpeg", headers={
        "Cache-Control": "no-store", "X-Image-Width": str(res.width), "X-Image-Height": str(res.height),
        "X-Capture-Ms": str(res.elapsed_ms), "X-Capture-Source": res.source})


@router.get("/last")
async def camera_last():
    if not bridge.last_image:
        raise api_error(404, "no_image", "No image has been captured yet.")
    return Response(bridge.last_image, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/stream")
async def camera_stream():
    """MJPEG live view relayed from port 81. Works directly as <img src>."""
    hub = bridge.stream

    async def gen():
        async for frame in hub.subscribe():
            yield (f"--{StreamHub.BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(frame)}\r\n\r\n"
                   ).encode() + frame + b"\r\n"

    return StreamingResponse(gen(), media_type=f"multipart/x-mixed-replace; boundary={StreamHub.BOUNDARY}",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/stream/status")
async def stream_status():
    return bridge.stream.status()


@router.get("/logs")
def camera_logs(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(CameraLog).order_by(CameraLog.id.desc()).limit(max(1, min(limit, 300))).all()
    return {"logs": [{"id": r.id, "level": r.level, "message": r.message,
                      "at": r.created_at.isoformat()} for r in rows]}


@router.delete("/logs")
def clear_logs(db: Session = Depends(get_db)):
    db.query(CameraLog).delete()
    db.commit()
    return {"ok": True}


# CameraWebServer /control?var=..&val=.. -- only safe, known variables
CONTROLS = {
    "framesize": range(0, 14), "quality": range(4, 64), "brightness": range(-2, 3), "contrast": range(-2, 3),
    "saturation": range(-2, 3), "hmirror": range(0, 2), "vflip": range(0, 2), "led_intensity": range(0, 256),
    "awb": range(0, 2), "aec": range(0, 2), "agc": range(0, 2), "special_effect": range(0, 7),
}
FRAMESIZES = {"QVGA 320x240": 5, "VGA 640x480": 8, "SVGA 800x600": 9, "XGA 1024x768": 10,
              "HD 1280x720": 11, "SXGA 1280x1024": 12, "UXGA 1600x1200": 13}


@router.get("/controls")
def list_controls():
    return {"controls": {k: [v.start, v.stop - 1] for k, v in CONTROLS.items()}, "framesizes": FRAMESIZES}


@router.post("/control")
async def camera_control(payload: dict = Body(...)):
    var, val = payload.get("var"), payload.get("val")
    if var not in CONTROLS:
        raise api_error(422, "invalid_control", f"Unsupported control '{var}'.", f"Allowed: {', '.join(CONTROLS)}")
    try:
        val = int(val)
    except (TypeError, ValueError):
        raise api_error(422, "invalid_control", "val must be an integer.")
    if val not in CONTROLS[var]:
        raise api_error(422, "invalid_control", f"{var} must be within {CONTROLS[var].start}..{CONTROLS[var].stop - 1}.")
    s = settings_store.get_all()
    port = int(s["camera_capture_port"])
    base = f"http://{s['camera_ip']}" + ("" if port == 80 else f":{port}")
    try:
        async with httpx.AsyncClient(timeout=float(s["camera_timeout_s"])) as client:
            r = await client.get(f"{base}/control", params={"var": var, "val": val})
    except httpx.HTTPError as exc:
        raise api_error(502, "camera_unreachable", f"Could not reach the camera: {exc.__class__.__name__}")
    if r.status_code == 404:
        raise api_error(502, "control_unsupported", "This firmware has no /control endpoint.",
                        "Use the stock Arduino CameraWebServer example (or firmware/ in this project).")
    if r.status_code != 200:
        raise api_error(502, "control_failed", f"Camera rejected {var}={val} (HTTP {r.status_code}).",
                        "led_intensity needs a CameraWebServer build with the flash LED (GPIO 4) enabled.")
    add_log("info", f"Camera control set: {var}={val}")
    return {"ok": True, "var": var, "val": val}
