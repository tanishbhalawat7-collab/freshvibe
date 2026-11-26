"""The automatic scan workflow:

   image -> barcode decode -> product DB lookup -> OCR -> date extraction
         -> optional AI vision -> evidence fusion -> validation -> decision
         -> (auto-save | ask for confirmation | ask for another capture)

Product identity evidence: barcode lookup  >  AI corroborated by OCR  >  AI alone.
Date evidence:            OCR with label   >  AI corroborated by OCR  >  AI alone (never auto-saved).
"""
from __future__ import annotations

import asyncio
import logging
import re
import uuid
from datetime import datetime, timezone

import numpy as np
from sqlalchemy.orm import Session

from . import ai_vision, barcode, imaging, lookup, ocr, products, settings_store
from .config import config
from .models import Scan

log = logging.getLogger("freshvibe.pipeline")

IMAGES_DIR = config.DATA_DIR / "images"


def store_image(db: Session, jpeg: bytes, source: str) -> tuple[Scan, np.ndarray]:
    bgr = imaging.load_image(jpeg)
    # normalise everything (uploads may be PNG/HEIC-converted/huge) to a sane JPEG
    h, w = bgr.shape[:2]
    if max(h, w) > 2600:
        import cv2
        f = 2600 / max(h, w)
        bgr = cv2.resize(bgr, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        h, w = bgr.shape[:2]
    name = f"{datetime.now(timezone.utc):%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:8]}.jpg"
    (IMAGES_DIR / name).write_bytes(imaging.to_jpeg(bgr, 92) if source == "upload" else jpeg)
    scan = Scan(source=source, image_path=name, width=w, height=h, status="captured")
    db.add(scan)
    db.commit()
    db.refresh(scan)
    return scan, bgr


def load_scan_image(scan: Scan) -> np.ndarray:
    return imaging.load_image((IMAGES_DIR / scan.image_path).read_bytes())


def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _tokens(s: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]{3,}", (s or "").lower())}


def _field(value=None, confidence=0.0, source=None, **extra) -> dict:
    return {"value": value, "confidence": round(float(confidence), 3), "source": source, **extra}


async def run_barcode(bgr: np.ndarray) -> dict:
    return await asyncio.to_thread(barcode.decode, bgr)


async def run_ocr(bgr: np.ndarray) -> dict:
    try:
        return await asyncio.to_thread(ocr.run, bgr, settings_store.get("date_order"))
    except ocr.OCRUnavailable as exc:
        return {"engine": ocr.engine_name(), "error": str(exc), "text": "", "lines": [], "dates": None}


async def run_ai(bgr: np.ndarray) -> dict:
    if not settings_store.get("ai_enabled"):
        return {"used": False, "reason": "AI recognition is switched off in Settings."}
    if not ai_vision.provider():
        return {"used": False, "reason": ai_vision.status()["reason"]}
    try:
        return {"used": True, **(await ai_vision.analyze(bgr))}
    except ai_vision.AIUnavailable as exc:
        return {"used": False, "error": str(exc)}


def fuse(bc: dict, lk: dict | None, oc: dict, ai: dict) -> dict:
    """Combine evidence into per-field values with confidences and sources."""
    f: dict[str, dict] = {}
    ocr_text = oc.get("text") or ""
    ocr_dates = (oc.get("dates") or {})
    ocr_tokens = _tokens(ocr_text)
    ocr_digits_lines = [_digits(d["raw"]) for d in ocr_dates.get("all_dates", [])]

    # ---- barcode
    code = bc["codes"][0] if bc.get("codes") else None
    retail = next((c for c in bc.get("codes", []) if c["is_retail"]), None)
    code = retail or code
    f["barcode"] = _field(code["text"] if code else None, 0.99 if code else 0, "barcode" if code else None,
                          format=code["format"] if code else None)

    # ---- identity
    ai_used = ai.get("used")
    for key, ai_key in (("name", "product_name"), ("brand", "brand"), ("category", "category")):
        if lk and lk.get("found") and lk["product"].get(key):
            f[key] = _field(lk["product"][key], 0.95, f"barcode_db:{lk['source']}")
        elif ai_used and ai.get(ai_key):
            c = float(ai.get("confidence", {}).get(ai_key, 0.5))
            val = ai[ai_key]
            corroborated = key == "category" or (_tokens(val) and len(_tokens(val) & ocr_tokens) / len(_tokens(val)) >= 0.5)
            # AI identity is a guess until a person (or OCR text) backs it up
            conf = min(c, 0.88) if corroborated else min(c, 0.7)
            if key == "category":
                conf = min(c, 0.8)
            f[key] = _field(val, conf, "ai+ocr" if corroborated and key != "category" else "ai",
                            corroborated=bool(corroborated))
        else:
            f[key] = _field(None, 0, None)

    # ---- dates
    ai_dates = ai.get("dates", []) if ai_used else []

    def date_field(kind: str) -> dict:
        cand = ocr_dates.get(kind)
        ai_match = [d for d in ai_dates if d["kind"] == kind and d.get("normalized")]
        if cand:
            conf = cand["confidence"]
            src = "ocr_derived" if cand.get("derived") else "ocr"
            if any(d["normalized"] == cand["value"] for d in ai_match):
                conf, src = min(0.99, conf + 0.1), src + "+ai"
            elif ai_match:
                conf -= 0.25
                src += " (AI read differently: " + ", ".join(d["normalized"] for d in ai_match) + ")"
            return _field(cand["value"], conf, src, precision=cand["precision"], raw=cand["raw"],
                          label=cand.get("label"), notes=cand.get("notes", []), ambiguous=cand.get("ambiguous"))
        if ai_match:
            d = max(ai_match, key=lambda x: x["confidence"])
            # Was this exact string also read by OCR (but without a label)?
            seen_by_ocr = _digits(d["as_printed"]) and any(_digits(d["as_printed"]) in x or x in _digits(d["as_printed"])
                                                           for x in ocr_digits_lines if x)
            conf = min(d["confidence"], 0.7) if seen_by_ocr else min(d["confidence"], 0.45)
            return _field(d["normalized"], conf, "ai+ocr_text" if seen_by_ocr else "ai_only",
                          precision="month" if len(d["normalized"]) == 7 else "day", raw=d["as_printed"],
                          label=d.get("label"), notes=["read by AI; confirm against the pack"])
        return _field(None, 0, None)

    f["expiry_date"] = date_field("expiry")
    mfg = date_field("mfg")
    if not mfg["value"]:
        mfg = date_field("packed")
        if mfg["value"]:
            mfg["notes"] = (mfg.get("notes") or []) + ["packed date used as manufacturing date"]
    f["mfg_date"] = mfg

    # ---- batch
    b = ocr_dates.get("batch")
    if b:
        f["batch_no"] = _field(b["value"], b["confidence"], "ocr")
    elif ai_used and ai.get("batch_no"):
        seen = _digits(ai["batch_no"]) and _digits(ai["batch_no"]) in _digits(ocr_text)
        f["batch_no"] = _field(ai["batch_no"], 0.75 if seen else 0.5, "ai+ocr_text" if seen else "ai")
    else:
        f["batch_no"] = _field(None, 0, None)
    return f


def merge_fields(old: dict, new: dict) -> dict:
    """Combine fields from two captures of the same product (e.g. barcode on the
    back, expiry on the lid): keep the more confident reading per field."""
    out = {}
    for k in set(old) | set(new):
        a, b = old.get(k) or _field(), new.get(k) or _field()
        if a.get("value") and b.get("value") and a["value"] == b["value"]:
            out[k] = {**a, "confidence": round(min(0.99, max(a["confidence"], b["confidence"]) + 0.05), 3)}
        else:
            out[k] = a if (a.get("confidence") or 0) >= (b.get("confidence") or 0) else b
    return out


def decide(fields: dict, oc: dict, bc: dict, quality: dict, threshold: float, lk: dict | None = None) -> dict:
    uncertain, reasons = [], []
    identity_ok = (fields["name"]["value"] and fields["name"]["confidence"] >= threshold)
    if not fields["name"]["value"]:
        if fields["barcode"]["value"] and lk and lk.get("errors") and not lk.get("found"):
            why = " (product databases could not be reached: " + "; ".join(lk["errors"][:2]) + ")."
        elif fields["barcode"]["value"] and lk is not None:
            why = " (barcode not found in any product database)."
        elif fields["barcode"]["value"]:
            why = " (barcode is not a retail EAN/UPC code)."
        else:
            why = " (no barcode visible; AI recognition " + ("found no name)." if ai_vision.provider() else "is not configured).")
        reasons.append("Product name could not be identified" + why)
        uncertain.append("name")
    elif not identity_ok:
        reasons.append(f"Product name '{fields['name']['value']}' is an unconfirmed AI guess.")
        uncertain.append("name")
    for k in ("brand", "category"):
        if fields[k]["value"] and fields[k]["confidence"] < threshold:
            uncertain.append(k)

    exp = fields["expiry_date"]
    if not exp["value"]:
        reasons.append("No expiry date was found on this side of the pack.")
        uncertain.append("expiry_date")
    elif exp["confidence"] < threshold:
        why = "; ".join(exp.get("notes") or []) or "low OCR confidence"
        reasons.append(f"Expiry date {exp['value']} is uncertain ({why}).")
        uncertain.append("expiry_date")
    if fields["mfg_date"]["value"] and fields["mfg_date"]["confidence"] < threshold:
        uncertain.append("mfg_date")
    if fields["batch_no"]["value"] and fields["batch_no"]["confidence"] < threshold:
        uncertain.append("batch_no")

    for issue in ((oc.get("dates") or {}).get("issues") or []):
        reasons.append(issue)

    nothing_read = not bc.get("found") and len((oc.get("text") or "").strip()) < 6
    if nothing_read:
        status = "retake"
        reasons.insert(0, "No barcode and almost no text could be read from this image.")
    elif identity_ok and exp["value"] and exp["confidence"] >= threshold:
        status = "auto_save"
    else:
        status = "needs_confirmation"

    suggest_retake = status != "auto_save" and ("expiry_date" in uncertain or nothing_read)
    tips = list(quality.get("issues") or [])
    if suggest_retake and not fields["expiry_date"]["value"]:
        tips.append("Turn the pack so the printed EXP / BEST BEFORE line faces the camera and capture again.")
    return {"status": status, "reasons": reasons, "uncertain_fields": sorted(set(uncertain)),
            "suggest_retake": suggest_retake, "tips": tips}


def overall_confidence(fields: dict) -> float:
    keys = [k for k in ("name", "expiry_date", "barcode", "brand") if fields[k]["value"]]
    if not keys:
        return 0.0
    return round(sum(fields[k]["confidence"] for k in keys) / len(keys), 3)


def fields_to_product(fields: dict, scan: Scan, oc_text: str, status: str) -> dict:
    v = lambda k: fields[k]["value"]
    return {
        "barcode": v("barcode"), "barcode_format": fields["barcode"].get("format"),
        "name": v("name"), "brand": v("brand"), "category": v("category"),
        "mfg_date": v("mfg_date"), "mfg_precision": fields["mfg_date"].get("precision"),
        "expiry_date": v("expiry_date"), "expiry_precision": fields["expiry_date"].get("precision"),
        "batch_no": v("batch_no"),
        "image_path": scan.image_path, "ocr_text": oc_text, "scan_id": scan.id,
        "confidence": overall_confidence(fields),
        "field_confidence": {k: fields[k]["confidence"] for k in fields},
        "identity_source": (fields["name"]["source"] or "").split(":")[0] or None,
        "expiry_source": fields["expiry_date"]["source"],
        "verification_status": status,
    }


async def process(db: Session, scan: Scan, bgr: np.ndarray, *, use_ai: bool = True,
                  merge_with: Scan | None = None, auto_save: bool = True) -> dict:
    t0 = datetime.now(timezone.utc)
    quality = imaging.quality_report(bgr)
    bc_task = asyncio.create_task(run_barcode(bgr))
    oc_task = asyncio.create_task(run_ocr(bgr))
    ai_task = asyncio.create_task(run_ai(bgr)) if use_ai else None
    bc = await bc_task
    lk = None
    if bc["found"]:
        code = next((c for c in bc["codes"] if c["is_retail"]), None)
        if code:
            lk = await lookup.lookup(db, code["text"])
    oc = await oc_task
    if ai_task:
        ai = await ai_task
    elif not ai_vision.provider():
        ai = {"used": False, "reason": ai_vision.status()["reason"]}
    else:
        ai = {"used": False, "reason": "switched off for this scan"}

    fields = fuse(bc, lk, oc, ai)
    merged_from = None
    if merge_with and merge_with.result and merge_with.result.get("fields"):
        fields = merge_fields(merge_with.result["fields"], fields)
        merged_from = merge_with.id
        oc_text = (merge_with.result.get("ocr", {}).get("text", "") + "\n---\n" + (oc.get("text") or "")).strip()
    else:
        oc_text = oc.get("text") or ""

    threshold = float(settings_store.get("auto_save_min_confidence"))
    decision = decide(fields, oc, bc, quality, threshold, lk)
    if oc.get("error"):
        decision["reasons"].insert(0, f"OCR unavailable: {oc['error']}")
        if decision["status"] == "auto_save":
            decision["status"] = "needs_confirmation"

    saved = None
    if decision["status"] == "auto_save" and auto_save:
        try:
            p, dup = products.create(db, fields_to_product(fields, scan, oc_text, "auto_verified"))
            saved = {"product": products.to_dict(p), "duplicate": dup}
            decision["status"] = "saved"
        except products.ProductError as exc:
            decision["status"] = "needs_confirmation"
            decision["reasons"].append(f"Could not save automatically: {exc}")

    result = {
        "scan_id": scan.id,
        "image_url": f"/api/scans/{scan.id}/image",
        "merged_with_scan_id": merged_from,
        "decision": decision,
        "fields": fields,
        "saved": saved,
        "confidence": overall_confidence(fields),
        "quality": quality,
        "barcode": bc,
        "lookup": lk,
        "ocr": {k: oc.get(k) for k in ("engine", "text", "lines", "mean_confidence", "elapsed_ms", "error", "passes")},
        "dates": oc.get("dates"),
        "ai": ai,
        "threshold": threshold,
        "elapsed_ms": int((datetime.now(timezone.utc) - t0).total_seconds() * 1000),
    }
    scan.status = decision["status"]
    scan.result = _jsonable(result)
    db.commit()
    return result


def _jsonable(obj):
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    return obj
