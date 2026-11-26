"""Expiry status rules and notification generation."""
from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import settings_store
from .dates import end_of_period
from .models import Notification, Product


def days_left(p: Product, today: date | None = None) -> int | None:
    if not p.expiry_date:
        return None
    today = today or date.today()
    last_good = end_of_period(p.expiry_date.isoformat(), p.expiry_precision or "day")
    return (last_good - today).days


def status_of(p: Product, today: date | None = None, fresh_days: int | None = None) -> str:
    """fresh | expiring_soon | expired | unknown"""
    if not p.expiry_date or p.verification_status == "unverified":
        return "unknown"
    fresh_days = fresh_days if fresh_days is not None else int(settings_store.get("fresh_days"))
    d = days_left(p, today)
    if d < 0:
        return "expired"
    if d <= fresh_days:
        return "expiring_soon"
    return "fresh"


def _describe(p: Product) -> str:
    label = " ".join(x for x in (p.brand, p.name) if x) or f"Product #{p.id}"
    if p.brand and p.name and p.name.lower().startswith(p.brand.lower()):
        label = p.name
    return label


def expiry_label(p: Product) -> str:
    if not p.expiry_date:
        return "unknown"
    if p.expiry_precision == "month":
        return p.expiry_date.strftime("%b %Y")
    return p.expiry_date.strftime("%d %b %Y")


def notification_kind(d: int, windows: list[int]) -> str | None:
    if d < 0:
        return "expired"
    if d == 0:
        return "today"
    if d == 1:
        return "tomorrow"
    for w in sorted(windows):
        if w > 1 and d <= w:
            return f"within_{w}"
    return None


def generate_notifications(db: Session, today: date | None = None) -> int:
    """Create at most one notification per (product, kind, expiry date)."""
    today = today or date.today()
    windows = settings_store.get("notify_days")
    created = 0
    products = db.query(Product).filter(Product.expiry_date.isnot(None),
                                        Product.verification_status != "unverified").all()
    existing = {(n.product_id, n.kind, n.expiry_key) for n in db.query(Notification).all()}
    for p in products:
        d = days_left(p, today)
        kind = notification_kind(d, windows)
        if not kind:
            continue
        key = (p.id, kind, p.expiry_date.isoformat())
        if key in existing:
            continue
        name = _describe(p)
        when = expiry_label(p)
        msg = {
            "expired": f"{name} expired ({when}).",
            "today": f"{name} expires today ({when}).",
            "tomorrow": f"{name} expires tomorrow ({when}).",
        }.get(kind) or f"{name} expires in {d} days ({when})."
        try:
            with db.begin_nested():
                db.add(Notification(product_id=p.id, kind=kind, expiry_key=p.expiry_date.isoformat(), message=msg))
            created += 1
            existing.add(key)
        except IntegrityError:
            pass
    db.commit()
    return created


SEVERITY = {"expired": 0, "today": 1, "tomorrow": 2}


def notification_dict(n: Notification) -> dict:
    sev = SEVERITY.get(n.kind)
    if sev is None:
        try:
            w = int(n.kind.split("_")[1])
            sev = 3 if w <= 7 else 4
        except (IndexError, ValueError):
            sev = 5
    return {"id": n.id, "product_id": n.product_id, "kind": n.kind, "message": n.message,
            "severity": sev, "created_at": n.created_at.isoformat() if n.created_at else None,
            "read": n.read_at is not None}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
