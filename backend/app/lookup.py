"""Barcode -> product identity, using (in order):
   1. products already confirmed in the local database
   2. the local lookup cache
   3. Open Food Facts / Open Beauty Facts / Open Products Facts / Open Pet Food Facts
   4. UPCitemdb free trial endpoint (US/EU retail items)
Nothing is invented: if no source knows the code, the result says so."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy.orm import Session

from .barcode import lookup_candidates
from .config import config
from .models import BarcodeCache, Product

log = logging.getLogger("freshvibe.lookup")

CATEGORIES = ["Dairy", "Bakery", "Beverages", "Snacks", "Grocery", "Frozen", "Fruits & Vegetables",
              "Meat & Seafood", "Condiments & Sauces", "Medicine", "Personal Care", "Household",
              "Baby Care", "Pet Care", "Other"]

OFF_SOURCES = [
    ("Open Food Facts", "https://world.openfoodfacts.org"),
    ("Open Beauty Facts", "https://world.openbeautyfacts.org"),
    ("Open Products Facts", "https://world.openproductsfacts.org"),
    ("Open Pet Food Facts", "https://world.openpetfoodfacts.org"),
]
FIELDS = "product_name,product_name_en,generic_name,brands,categories_tags,categories,quantity,image_front_small_url"

_KEYWORDS = [
    ("Dairy", ["dairy", "milk", "cheese", "yogurt", "yoghurt", "butter", "paneer", "curd", "ghee", "cream"]),
    ("Bakery", ["bread", "bakery", "cake", "bun", "rusk", "pastr"]),
    ("Beverages", ["beverage", "drink", "juice", "tea", "coffee", "soda", "water", "cola"]),
    ("Snacks", ["snack", "biscuit", "cookie", "chip", "crisp", "chocolate", "candy", "confection", "namkeen", "sweet"]),
    ("Frozen", ["frozen", "ice-cream", "ice cream"]),
    ("Fruits & Vegetables", ["fruit", "vegetable"]),
    ("Meat & Seafood", ["meat", "chicken", "fish", "seafood", "egg"]),
    ("Condiments & Sauces", ["sauce", "condiment", "ketchup", "spice", "masala", "pickle", "jam", "spread", "oil"]),
    ("Medicine", ["medicine", "drug", "pharma", "tablet", "syrup", "capsule", "supplement", "vitamin"]),
    ("Personal Care", ["cosmetic", "shampoo", "soap", "toothpaste", "skin", "hair", "beauty", "deodorant", "personal care"]),
    ("Household", ["household", "cleaning", "detergent", "dishwash", "cleaner"]),
    ("Baby Care", ["baby", "infant"]),
    ("Pet Care", ["pet", "dog", "cat food"]),
    ("Grocery", ["cereal", "flour", "atta", "rice", "pulse", "dal", "noodle", "pasta", "grocery", "sugar", "salt", "grain"]),
]


def map_category(text: str | None, source: str | None = None) -> str:
    t = (text or "").lower()
    for cat, words in _KEYWORDS:
        if any(w in t for w in words):
            return cat
    if source == "Open Beauty Facts":
        return "Personal Care"
    if source == "Open Pet Food Facts":
        return "Pet Care"
    if source == "Open Food Facts":
        return "Grocery"
    return "Other"


def _from_off(source: str, p: dict) -> dict | None:
    name = (p.get("product_name") or p.get("product_name_en") or p.get("generic_name") or "").strip()
    brand = (p.get("brands") or "").split(",")[0].strip()
    if not name and not brand:
        return None
    cats = " ".join(p.get("categories_tags") or []) + " " + (p.get("categories") or "")
    return {
        "name": name or None, "brand": brand or None,
        "category": map_category(cats + " " + name, source),
        "raw_category": (p.get("categories") or "").split(",")[-1].strip() or None,
        "quantity_text": p.get("quantity") or None,
        "image_url": p.get("image_front_small_url") or None,
    }


async def _query_remote(code: str) -> tuple[dict | None, str | None, list[str]]:
    errors: list[str] = []
    headers = {"User-Agent": config.LOOKUP_USER_AGENT}
    async with httpx.AsyncClient(timeout=httpx.Timeout(8.0, connect=4.0), headers=headers,
                                 follow_redirects=True) as client:
        for name, base in OFF_SOURCES:
            try:
                r = await client.get(f"{base}/api/v2/product/{code}.json", params={"fields": FIELDS})
                if r.status_code == 404:
                    continue
                r.raise_for_status()
                j = r.json()
                if j.get("status") == 1 and j.get("product"):
                    data = _from_off(name, j["product"])
                    if data:
                        return data, name, errors
            except (httpx.HTTPError, ValueError) as exc:
                errors.append(f"{name}: {exc.__class__.__name__}")
        try:
            r = await client.get("https://api.upcitemdb.com/prod/trial/lookup", params={"upc": code})
            if r.status_code == 200:
                items = r.json().get("items") or []
                if items:
                    it = items[0]
                    return {"name": it.get("title"), "brand": it.get("brand") or None,
                            "category": map_category(f"{it.get('category', '')} {it.get('title', '')}"),
                            "raw_category": it.get("category") or None, "quantity_text": None,
                            "image_url": (it.get("images") or [None])[0]}, "UPCitemdb", errors
            elif r.status_code not in (400, 404):
                errors.append(f"UPCitemdb: HTTP {r.status_code}")
        except (httpx.HTTPError, ValueError) as exc:
            errors.append(f"UPCitemdb: {exc.__class__.__name__}")
    return None, None, errors


async def lookup(db: Session, code: str) -> dict:
    """Returns {found, source, product{name,brand,category,...}, errors, cached}."""
    for c in lookup_candidates(code):
        local = (db.query(Product)
                 .filter(Product.barcode == c, Product.verification_status.in_(["user_verified", "auto_verified"]),
                         Product.name.isnot(None))
                 .order_by(Product.updated_at.desc()).first())
        if local:
            return {"found": True, "source": "Your inventory", "cached": False, "errors": [],
                    "product": {"name": local.name, "brand": local.brand, "category": local.category}}

    now = datetime.now(timezone.utc)
    for c in lookup_candidates(code):
        row = db.get(BarcodeCache, c)
        if row:
            fetched = row.fetched_at if row.fetched_at.tzinfo else row.fetched_at.replace(tzinfo=timezone.utc)
            ttl = timedelta(days=30) if row.found else timedelta(days=1)
            if now - fetched < ttl and (row.found or c == code):
                if row.found:
                    return {"found": True, "source": row.source, "cached": True, "errors": [], "product": row.data}

    if not config.ENABLE_ONLINE_LOOKUP:
        return {"found": False, "source": None, "cached": False, "product": None,
                "errors": ["Online lookup disabled (ENABLE_ONLINE_LOOKUP=false)."]}

    all_errors: list[str] = []
    for c in lookup_candidates(code):
        data, source, errors = await _query_remote(c)
        all_errors += errors
        if data:
            _cache(db, c, True, source, data)
            return {"found": True, "source": source, "cached": False, "errors": all_errors, "product": data}
    # only cache "not found" when every source actually answered
    if not all_errors:
        _cache(db, code, False, None, None)
    return {"found": False, "source": None, "cached": False, "product": None, "errors": all_errors}


def _cache(db: Session, code: str, found: bool, source: str | None, data: dict | None) -> None:
    row = db.get(BarcodeCache, code)
    if row is None:
        row = BarcodeCache(barcode=code)
        db.add(row)
    row.found, row.source, row.data, row.fetched_at = found, source, data, datetime.now(timezone.utc)
    db.commit()
