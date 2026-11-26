"""Barcode decoding with zxing-cpp (the maintained C++ port of ZXing)."""
from __future__ import annotations

import cv2
import numpy as np
import zxingcpp

from . import imaging

SUPPORTED = ["EAN13", "EAN8", "UPCA", "UPCE", "Code128", "Code39", "QRCode", "DataMatrix"]
FORMATS = zxingcpp.barcode_formats_from_str(",".join(SUPPORTED))
RETAIL = {"EAN-13", "EAN-8", "UPC-A", "UPC-E"}


def _variants(bgr: np.ndarray):
    g = imaging.gray(bgr)
    yield "original", g
    up = imaging.upscale_to(g, 900)
    if up is not g:
        yield "upscaled", up
    yield "contrast", imaging.clahe(up)
    yield "sharpened", imaging.sharpen(imaging.clahe(up))
    yield "binary", imaging.otsu(up)


def _checksum_ok(code: str) -> bool:
    if not code.isdigit() or len(code) not in (8, 12, 13, 14):
        return True
    digits = [int(c) for c in code]
    body, check = digits[:-1], digits[-1]
    total = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(body)))
    return (10 - total % 10) % 10 == check


def decode(bgr: np.ndarray) -> dict:
    found: dict[tuple[str, str], dict] = {}
    tried = []
    for name, img in _variants(bgr):
        tried.append(name)
        try:
            results = zxingcpp.read_barcodes(img, formats=FORMATS, try_rotate=True, try_downscale=True,
                                             try_invert=True)
        except TypeError:  # very old zxing-cpp
            results = zxingcpp.read_barcodes(img, formats=FORMATS)
        for r in results:
            if not getattr(r, "valid", True) or not r.text:
                continue
            fmt = str(r.format)
            text = r.text.strip()
            if fmt == "EAN-13" and len(text) == 13 and text.startswith("0"):
                fmt, text = "UPC-A", text[1:]  # a UPC-A symbol is an EAN-13 with a leading 0
            if fmt in RETAIL and not _checksum_ok(text):
                continue
            key = (fmt, text)
            if key not in found:
                p = r.position
                found[key] = {
                    "text": text,
                    "format": fmt,
                    "variant": name,
                    "is_retail": fmt in RETAIL,
                    "position": [[p.top_left.x, p.top_left.y], [p.top_right.x, p.top_right.y],
                                 [p.bottom_right.x, p.bottom_right.y], [p.bottom_left.x, p.bottom_left.y]],
                }
        # retail barcode found on an easy variant -> no need to keep trying
        if any(v["is_retail"] for v in found.values()):
            break
    codes = sorted(found.values(), key=lambda c: (not c["is_retail"], c["format"]))
    return {"found": bool(codes), "codes": codes, "variants_tried": tried, "library": f"zxing-cpp {zxing_version()}"}


def lookup_candidates(code: str) -> list[str]:
    """Alternate spellings worth trying in product databases (UPC-A <-> EAN-13)."""
    c = [code]
    if code.isdigit():
        if len(code) == 12:
            c.append("0" + code)
        elif len(code) == 13 and code.startswith("0"):
            c.append(code[1:])
    return c


def zxing_version() -> str:
    try:
        from importlib.metadata import version
        return version("zxing-cpp")
    except Exception:
        return "unknown"


def self_test() -> dict:
    """Render an EAN-13 and a QR code with zxing-cpp and decode them back."""
    out = {}
    for fmt, text in (("EAN13", "8901063010147"), ("QRCode", "FRESHVIBE-SELFTEST")):
        try:
            img = np.array(zxingcpp.create_barcode(text, zxingcpp.barcode_format_from_str(fmt)).to_image(scale=4))
            img = cv2.copyMakeBorder(img, 30, 30, 30, 30, cv2.BORDER_CONSTANT, value=255)
            res = zxingcpp.read_barcodes(img)
            out[fmt] = bool(res) and res[0].text == text
        except Exception as exc:  # pragma: no cover - depends on version
            out[fmt] = f"error: {exc}"
    return {"ok": all(v is True for v in out.values()), "checks": out, "library": f"zxing-cpp {zxing_version()}"}
