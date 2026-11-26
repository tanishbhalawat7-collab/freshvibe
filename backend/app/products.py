"""Product persistence, validation, serialisation and duplicate handling."""
from __future__ import annotations

import re
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from . import expiry, settings_store
from .lookup import CATEGORIES
from .models import Notification, Product


class ProductError(ValueError):
    pass


def parse_date_field(value, precision: str | None) -> tuple[date | None, str | None]:
    """Accepts 'YYYY-MM-DD' or 'YYYY-MM'. Returns (date, precision)."""
    if value in (None, ""):
        return None, None
    s = str(value).strip()
    if re.fullmatch(r"\d{4}-\d{2}", s):
        y, m = map(int, s.split("-"))
        if not (2000 <= y <= 2100 and 1 <= m <= 12):
            raise ProductError(f"Invalid month '{s}'.")
        return date(y, m, 1), "month"
    try:
        d = date.fromisoformat(s[:10])
    except ValueError as exc:
        raise ProductError(f"Invalid date '{s}'. Use YYYY-MM-DD, or YYYY-MM if only month/year is printed.") from exc
    if not 2000 <= d.year <= 2100:
        raise ProductError(f"Date '{s}' is out of range.")
    if precision == "month":
        return date(d.year, d.month, 1), "month"
    return d, "day"


EDITABLE = {"barcode", "barcode_format", "name", "brand", "category", "quantity", "mfg_date", "expiry_date",
            "mfg_precision", "expiry_precision", "batch_no", "notes"}


def apply_fields(p: Product, data: dict) -> None:
    unknown = set(data) - EDITABLE - {"verification_status", "scan_id", "field_confidence", "confidence",
                                      "identity_source", "expiry_source", "image_path", "ocr_text"}
    if unknown:
        raise ProductError(f"Unknown field(s): {', '.join(sorted(unknown))}")
    for key in ("name", "brand", "batch_no", "notes", "barcode", "barcode_format"):
        if key in data:
            v = data[key]
            v = str(v).strip() if v is not None else None
            if v and len(v) > (2000 if key == "notes" else 255):
                raise ProductError(f"{key} is too long.")
            setattr(p, key, v or None)
    if "barcode" in data and p.barcode and not re.fullmatch(r"[\x20-\x7e]{1,64}", p.barcode):
        raise ProductError("Barcode contains unsupported characters.")
    if "category" in data:
        c = data["category"]
        if c and c not in CATEGORIES:
            raise ProductError(f"Category must be one of: {', '.join(CATEGORIES)}")
        p.category = c or None
    if "quantity" in data:
        q = int(data["quantity"] or 1)
        if not 1 <= q <= 9999:
            raise ProductError("Quantity must be 1-9999.")
        p.quantity = q
    if "mfg_date" in data:
        p.mfg_date, p.mfg_precision = parse_date_field(data["mfg_date"], data.get("mfg_precision"))
    if "expiry_date" in data:
        p.expiry_date, p.expiry_precision = parse_date_field(data["expiry_date"], data.get("expiry_precision"))
    if p.mfg_date and p.expiry_date and p.expiry_date < p.mfg_date:
        raise ProductError("Expiry date cannot be before the manufacturing date.")
    for key in ("verification_status", "scan_id", "field_confidence", "confidence", "identity_source",
                "expiry_source", "image_path", "ocr_text"):
        if key in data:
            setattr(p, key, data[key])
    if not (p.name or p.barcode):
        raise ProductError("A product needs at least a name or a barcode.")


def find_duplicate(db: Session, p: Product, exclude_id: int | None = None) -> Product | None:
    q = db.query(Product)
    if exclude_id:
        q = q.filter(Product.id != exclude_id)
    if p.barcode:
        q = q.filter(Product.barcode == p.barcode)
    elif p.name:
        q = q.filter(func.lower(Product.name) == p.name.lower(),
                     func.lower(func.coalesce(Product.brand, "")) == (p.brand or "").lower())
    else:
        return None
    q = q.filter(Product.batch_no == p.batch_no) if p.batch_no else q.filter(Product.batch_no.is_(None))
    q = q.filter(Product.expiry_date == p.expiry_date) if p.expiry_date else q.filter(Product.expiry_date.is_(None))
    return q.first()


def create(db: Session, data: dict, merge_duplicates: bool = True) -> tuple[Product, bool]:
    """Returns (product, was_duplicate). A duplicate (same barcode/name + batch +
    expiry) increases the existing item's quantity instead of adding a row."""
    p = Product(quantity=1)
    apply_fields(p, data)
    dup = find_duplicate(db, p) if merge_duplicates else None
    if dup:
        dup.quantity = (dup.quantity or 1) + (p.quantity or 1)
        if p.verification_status == "user_verified":
            dup.verification_status = "user_verified"
        if not dup.image_path and p.image_path:
            dup.image_path = p.image_path
        db.commit()
        db.refresh(dup)
        return dup, True
    db.add(p)
    db.commit()
    db.refresh(p)
    expiry.generate_notifications(db)
    return p, False


def update(db: Session, p: Product, data: dict) -> Product:
    old_expiry = p.expiry_date
    apply_fields(p, data)
    if "verification_status" not in data:
        p.verification_status = "user_verified"
    if "expiry_date" in data and "expiry_source" not in data and p.expiry_date != old_expiry:
        p.expiry_source = "user"
    db.commit()
    db.refresh(p)
    if p.expiry_date != old_expiry:
        db.query(Notification).filter(Notification.product_id == p.id,
                                      Notification.expiry_key != (p.expiry_date.isoformat() if p.expiry_date else "")
                                      ).delete()
        db.commit()
    expiry.generate_notifications(db)
    return p


def to_dict(p: Product, today: date | None = None) -> dict:
    fresh_days = int(settings_store.get("fresh_days"))
    def fmt(d, prec):
        if not d:
            return None
        return d.strftime("%Y-%m") if prec == "month" else d.isoformat()
    return {
        "id": p.id, "barcode": p.barcode, "barcode_format": p.barcode_format,
        "name": p.name, "brand": p.brand, "category": p.category, "quantity": p.quantity,
        "mfg_date": fmt(p.mfg_date, p.mfg_precision), "mfg_precision": p.mfg_precision,
        "expiry_date": fmt(p.expiry_date, p.expiry_precision), "expiry_precision": p.expiry_precision,
        "expiry_label": expiry.expiry_label(p), "expiry_source": p.expiry_source,
        "batch_no": p.batch_no,
        "image_url": f"/api/products/{p.id}/image" if p.image_path else None,
        "ocr_text": p.ocr_text, "confidence": p.confidence, "field_confidence": p.field_confidence,
        "identity_source": p.identity_source, "verification_status": p.verification_status,
        "notes": p.notes, "scan_id": p.scan_id,
        "scanned_at": p.scanned_at.isoformat() if p.scanned_at else None,
        "updated_at": p.updated_at.isoformat() if p.updated_at else None,
        "days_left": expiry.days_left(p, today),
        "status": expiry.status_of(p, today, fresh_days),
    }
