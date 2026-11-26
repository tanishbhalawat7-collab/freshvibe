from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Body, Depends
from fastapi.responses import FileResponse
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import pipeline, products
from ..database import get_db
from ..errors import api_error
from ..lookup import CATEGORIES
from ..models import Product, Scan

router = APIRouter(prefix="/api/products", tags=["products"])

SORTS = {
    "expiry_asc": lambda p: (p["days_left"] is None, p["days_left"] if p["days_left"] is not None else 0),
    "expiry_desc": lambda p: (p["days_left"] is None, -(p["days_left"] or 0)),
    "name": lambda p: ((p["name"] or p["barcode"] or "").lower(),),
    "scanned_desc": lambda p: (p["scanned_at"] or "",),
}


@router.get("")
def list_products(q: str | None = None, category: str | None = None, status: str | None = None,
                  verification: str | None = None, sort: str = "expiry_asc", limit: int = 500, offset: int = 0,
                  db: Session = Depends(get_db)):
    query = db.query(Product)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Product.name.ilike(like), Product.brand.ilike(like), Product.barcode.ilike(like),
                                 Product.batch_no.ilike(like)))
    if category:
        query = query.filter(Product.category == category)
    if verification:
        query = query.filter(Product.verification_status == verification)
    today = date.today()
    items = [products.to_dict(p, today) for p in query.all()]
    if status:
        wanted = set(status.split(","))
        items = [i for i in items if i["status"] in wanted]
    if sort not in SORTS:
        raise api_error(422, "invalid_sort", f"sort must be one of {', '.join(SORTS)}")
    items.sort(key=SORTS[sort], reverse=(sort == "scanned_desc"))
    total = len(items)
    return {"total": total, "items": items[offset:offset + max(1, min(limit, 1000))], "categories": CATEGORIES}


@router.get("/{product_id}")
def get_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise api_error(404, "product_not_found", f"Product {product_id} does not exist.")
    return products.to_dict(p)


@router.post("", status_code=201)
def create_product(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Manual entry, or confirmation of a scan (pass scan_id; image/OCR text are attached)."""
    data = dict(payload)
    merge = data.pop("merge_duplicates", True)
    scan_id = data.get("scan_id")
    if scan_id:
        scan = db.get(Scan, scan_id)
        if not scan:
            raise api_error(404, "scan_not_found", f"Scan {scan_id} does not exist.")
        data.setdefault("image_path", scan.image_path)
        res = scan.result or {}
        data.setdefault("ocr_text", (res.get("ocr") or {}).get("text"))
        if res.get("fields"):
            data.setdefault("field_confidence", {k: v.get("confidence") for k, v in res["fields"].items()})
            data.setdefault("confidence", res.get("confidence"))
            ident = ((res["fields"].get("name") or {}).get("source") or "").split(":")[0]
            data.setdefault("identity_source", ident or "user")
            src = (res["fields"].get("expiry_date") or {})
            if src.get("value") and src.get("value") == data.get("expiry_date"):
                data.setdefault("expiry_source", (src.get("source") or "") + "+user")
    data.setdefault("expiry_source", "user" if data.get("expiry_date") else None)
    data.setdefault("identity_source", "user")
    data["verification_status"] = "user_verified"
    try:
        p, dup = products.create(db, data, merge_duplicates=bool(merge))
    except (products.ProductError, ValueError, TypeError) as exc:
        raise api_error(422, "invalid_product", str(exc))
    if scan_id:
        s = db.get(Scan, scan_id)
        s.status = "confirmed"
        db.commit()
    return {"product": products.to_dict(p), "duplicate": dup}


@router.put("/{product_id}")
def update_product(product_id: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise api_error(404, "product_not_found", f"Product {product_id} does not exist.")
    data = {k: v for k, v in payload.items() if k in products.EDITABLE}
    try:
        products.update(db, p, data)
    except (products.ProductError, ValueError, TypeError) as exc:
        db.rollback()
        raise api_error(422, "invalid_product", str(exc))
    return products.to_dict(p)


@router.delete("/{product_id}")
def delete_product(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p:
        raise api_error(404, "product_not_found", f"Product {product_id} does not exist.")
    db.delete(p)
    db.commit()
    return {"ok": True, "deleted": product_id}


@router.get("/{product_id}/image")
def product_image(product_id: int, db: Session = Depends(get_db)):
    p = db.get(Product, product_id)
    if not p or not p.image_path:
        raise api_error(404, "image_missing", "This product has no image.")
    path = (pipeline.IMAGES_DIR / p.image_path).resolve()
    if pipeline.IMAGES_DIR.resolve() not in path.parents or not path.exists():
        raise api_error(404, "image_missing", "Image file not found.")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})
