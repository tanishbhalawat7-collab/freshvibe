from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from .. import imaging, pipeline
from ..camera import CameraError, bridge
from ..database import get_db
from ..errors import api_error
from ..models import Scan

router = APIRouter(prefix="/api", tags=["scan"])


async def _acquire(db: Session, image: UploadFile | None, source: str | None, scan_id: int | None):
    """Get an image from (in priority) an existing scan, an upload, or the camera."""
    if scan_id:
        scan = db.get(Scan, scan_id)
        if not scan:
            raise api_error(404, "scan_not_found", f"Scan {scan_id} does not exist.")
        try:
            return scan, pipeline.load_scan_image(scan)
        except (OSError, imaging.ImageError) as exc:
            raise api_error(410, "image_missing", f"Image for scan {scan_id} is unavailable: {exc}")
    if image is not None:
        data = await image.read()
        if not (image.content_type or "").startswith("image/") and data[:2] != b"\xff\xd8":
            raise api_error(415, "unsupported_media", "Upload an image file (JPEG, PNG or WebP).")
        try:
            return pipeline.store_image(db, data, "upload")
        except imaging.ImageError as exc:
            raise api_error(422, "invalid_image", str(exc))
    if (source or "camera") == "camera":
        try:
            res = await bridge.capture(reason="scan")
        except CameraError as ce:
            raise api_error(503, "camera_" + ce.code, ce.message, ce.hint)
        try:
            return pipeline.store_image(db, res.jpeg, "camera")
        except imaging.ImageError as exc:
            raise api_error(502, "invalid_image", str(exc))
    raise api_error(422, "no_image", "Provide an image upload, a scan_id, or source=camera.")


@router.post("/scan/image")
async def scan_image(image: UploadFile | None = File(None), source: str | None = Form(None),
                     db: Session = Depends(get_db)):
    """Capture from the ESP32-CAM (default) or accept an upload; store it as a scan."""
    scan, bgr = await _acquire(db, image, source, None)
    return {"scan_id": scan.id, "source": scan.source, "width": scan.width, "height": scan.height,
            "image_url": f"/api/scans/{scan.id}/image", "quality": imaging.quality_report(bgr)}


@router.post("/scan/barcode")
async def scan_barcode(image: UploadFile | None = File(None), source: str | None = Form(None),
                       scan_id: int | None = Form(None), lookup: bool = Form(True),
                       db: Session = Depends(get_db)):
    scan, bgr = await _acquire(db, image, source, scan_id)
    bc = await pipeline.run_barcode(bgr)
    lk = None
    retail = next((c for c in bc["codes"] if c["is_retail"]), None)
    if lookup and retail:
        from .. import lookup as lookup_mod
        lk = await lookup_mod.lookup(db, retail["text"])
    return {"scan_id": scan.id, "image_url": f"/api/scans/{scan.id}/image", **bc, "lookup": lk}


@router.post("/scan/ocr")
async def scan_ocr(image: UploadFile | None = File(None), source: str | None = Form(None),
                   scan_id: int | None = Form(None), db: Session = Depends(get_db)):
    scan, bgr = await _acquire(db, image, source, scan_id)
    oc = await pipeline.run_ocr(bgr)
    if oc.get("error"):
        raise api_error(503, "ocr_unavailable", oc["error"],
                        "Install Tesseract OCR and make sure it is on PATH, or set TESSERACT_CMD.")
    return {"scan_id": scan.id, "image_url": f"/api/scans/{scan.id}/image", **oc}


@router.post("/scan/process")
async def scan_process(image: UploadFile | None = File(None), source: str | None = Form(None),
                       scan_id: int | None = Form(None), merge_with: int | None = Form(None),
                       use_ai: bool = Form(True), auto_save: bool = Form(True),
                       db: Session = Depends(get_db)):
    """Full automatic workflow. Saves automatically only when identity and expiry
    are both above the confidence threshold; otherwise asks for confirmation."""
    prev = db.get(Scan, merge_with) if merge_with else None
    if merge_with and not prev:
        raise api_error(404, "scan_not_found", f"Scan {merge_with} (merge_with) does not exist.")
    scan, bgr = await _acquire(db, image, source, scan_id)
    return await pipeline.process(db, scan, bgr, use_ai=use_ai, merge_with=prev, auto_save=auto_save)


@router.get("/scans/{scan_id}")
def get_scan(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(Scan, scan_id)
    if not scan:
        raise api_error(404, "scan_not_found", f"Scan {scan_id} does not exist.")
    return {"id": scan.id, "source": scan.source, "status": scan.status, "width": scan.width,
            "height": scan.height, "created_at": scan.created_at.isoformat(),
            "image_url": f"/api/scans/{scan.id}/image", "result": scan.result}


@router.get("/scans")
def list_scans(limit: int = 20, db: Session = Depends(get_db)):
    rows = db.query(Scan).order_by(Scan.id.desc()).limit(max(1, min(limit, 100))).all()
    return {"scans": [{"id": s.id, "source": s.source, "status": s.status, "created_at": s.created_at.isoformat(),
                       "image_url": f"/api/scans/{s.id}/image",
                       "name": ((s.result or {}).get("fields", {}).get("name") or {}).get("value")} for s in rows]}


@router.get("/scans/{scan_id}/image")
def scan_image_file(scan_id: int, db: Session = Depends(get_db)):
    scan = db.get(Scan, scan_id)
    if not scan:
        raise api_error(404, "scan_not_found", f"Scan {scan_id} does not exist.")
    path = (pipeline.IMAGES_DIR / scan.image_path).resolve()
    if pipeline.IMAGES_DIR.resolve() not in path.parents or not path.exists():
        raise api_error(404, "image_missing", "Image file not found.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
