from __future__ import annotations

from datetime import date, datetime, timezone

from sqlalchemy import (JSON, Date, DateTime, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from .database import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Product(Base):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    barcode: Mapped[str | None] = mapped_column(String(64), index=True)
    barcode_format: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(255))
    brand: Mapped[str | None] = mapped_column(String(255))
    category: Mapped[str | None] = mapped_column(String(120), index=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)

    mfg_date: Mapped[date | None] = mapped_column(Date)
    mfg_precision: Mapped[str | None] = mapped_column(String(8))  # day | month
    expiry_date: Mapped[date | None] = mapped_column(Date, index=True)
    # 'day' -> exact date; 'month' -> only MM/YYYY printed (expiry_date stores the 1st,
    # status calculations treat the product as good until the end of that month)
    expiry_precision: Mapped[str | None] = mapped_column(String(8))
    expiry_source: Mapped[str | None] = mapped_column(String(32))  # ocr | ai_confirmed | derived | user
    batch_no: Mapped[str | None] = mapped_column(String(64))

    image_path: Mapped[str | None] = mapped_column(String(255))
    ocr_text: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    field_confidence: Mapped[dict | None] = mapped_column(JSON)
    identity_source: Mapped[str | None] = mapped_column(String(32))  # barcode_db | ai | ocr | user
    # auto_verified: saved automatically, all key fields above threshold
    # user_verified: confirmed/edited by a person
    # unverified: saved with at least one uncertain field
    verification_status: Mapped[str] = mapped_column(String(20), default="unverified")
    notes: Mapped[str | None] = mapped_column(Text)
    scan_id: Mapped[int | None] = mapped_column(ForeignKey("scans.id", ondelete="SET NULL"))

    scanned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Scan(Base):
    """Every captured/uploaded image and the raw evidence extracted from it."""

    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16))  # camera | upload
    image_path: Mapped[str] = mapped_column(String(255))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="captured")
    result: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BarcodeCache(Base):
    __tablename__ = "barcode_cache"

    barcode: Mapped[str] = mapped_column(String(64), primary_key=True)
    found: Mapped[bool] = mapped_column(default=False)
    source: Mapped[str | None] = mapped_column(String(64))
    data: Mapped[dict | None] = mapped_column(JSON)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (UniqueConstraint("product_id", "kind", "expiry_key", name="uq_notification"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))  # within_30 | within_7 | tomorrow | expired
    expiry_key: Mapped[str] = mapped_column(String(16))  # expiry date the alert was made for
    message: Mapped[str] = mapped_column(String(400))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)


class CameraLog(Base):
    __tablename__ = "camera_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    level: Mapped[str] = mapped_column(String(8))  # info | warn | error
    message: Mapped[str] = mapped_column(String(600))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
