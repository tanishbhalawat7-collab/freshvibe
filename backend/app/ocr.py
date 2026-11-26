"""OCR engines. Tesseract is the default; EasyOCR / PaddleOCR are used when
installed and selected with OCR_ENGINE (they read dot-matrix / inkjet date
codes noticeably better, at the cost of a large install)."""
from __future__ import annotations

import os
import shutil
import time
from functools import lru_cache

import cv2
import numpy as np

from . import dates as dates_mod
from . import imaging
from .config import config

ENGINE = os.getenv("OCR_ENGINE", "tesseract").strip().lower()


class OCRUnavailable(RuntimeError):
    pass


# ----------------------------------------------------------------- tesseract
def _tesseract():
    import pytesseract

    if config.TESSERACT_CMD:
        pytesseract.pytesseract.tesseract_cmd = config.TESSERACT_CMD
    elif not shutil.which("tesseract"):
        for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"):
            if os.path.exists(p):
                pytesseract.pytesseract.tesseract_cmd = p
                break
    return pytesseract


def _tess_lines(img: np.ndarray, psm: int) -> list[tuple[str, float]]:
    pt = _tesseract()
    try:
        data = pt.image_to_data(img, lang=config.OCR_LANG, config=f"--oem 1 --psm {psm}",
                                output_type=pt.Output.DICT, timeout=40)
    except pt.TesseractNotFoundError as exc:
        raise OCRUnavailable("Tesseract is not installed or not on PATH (set TESSERACT_CMD).") from exc
    except RuntimeError as exc:  # timeout
        raise OCRUnavailable(f"Tesseract failed: {exc}") from exc
    lines: dict[tuple, list[tuple[str, float, int]]] = {}
    for i, word in enumerate(data["text"]):
        w = (word or "").strip()
        conf = float(data["conf"][i])
        if not w or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((w, conf, data["left"][i]))
    out = []
    for key in sorted(lines):
        words = sorted(lines[key], key=lambda x: x[2])
        text = " ".join(w for w, _, _ in words)
        conf = sum(c for _, c, _ in words) / len(words) / 100
        out.append((text, round(conf, 3)))
    return out


# --------------------------------------------------------- easyocr / paddle
@lru_cache(maxsize=1)
def _easy_reader():
    import easyocr  # type: ignore

    return easyocr.Reader(["en"], gpu=False, verbose=False)


def _group_boxes(items: list[tuple[list, str, float]]) -> list[tuple[str, float]]:
    """Group (box, text, conf) detections into reading-order lines."""
    rows: list[list] = []
    for box, text, conf in sorted(items, key=lambda x: (np.mean([p[1] for p in x[0]]), x[0][0][0])):
        cy = float(np.mean([p[1] for p in box]))
        h = float(max(p[1] for p in box) - min(p[1] for p in box)) or 10
        for row in rows:
            if abs(row[0] - cy) < h * 0.6:
                row[1].append((box, text, conf))
                break
        else:
            rows.append([cy, [(box, text, conf)]])
    out = []
    for _, items_ in sorted(rows, key=lambda r: r[0]):
        items_.sort(key=lambda x: x[0][0][0])
        out.append((" ".join(t for _, t, _ in items_), round(float(np.mean([c for *_, c in items_])), 3)))
    return out


def _easy_lines(img: np.ndarray) -> list[tuple[str, float]]:
    res = _easy_reader().readtext(img)
    return _group_boxes([(b, t, float(c)) for b, t, c in res])


@lru_cache(maxsize=1)
def _paddle():
    from paddleocr import PaddleOCR  # type: ignore

    return PaddleOCR(use_angle_cls=True, lang="en", show_log=False)


def _paddle_lines(img: np.ndarray) -> list[tuple[str, float]]:
    res = _paddle().ocr(img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR), cls=True)
    items = []
    for page in res or []:
        for box, (text, conf) in page or []:
            items.append((box, text, float(conf)))
    return _group_boxes(items)


# ----------------------------------------------------------------- pipeline
def engine_name() -> str:
    return ENGINE if ENGINE in {"easyocr", "paddleocr"} else "tesseract"


def engine_version() -> str:
    try:
        if engine_name() == "tesseract":
            return f"Tesseract {_tesseract().get_tesseract_version()}"
        if engine_name() == "easyocr":
            import easyocr  # type: ignore
            return f"EasyOCR {easyocr.__version__}"
        import paddleocr  # type: ignore
        return f"PaddleOCR {paddleocr.__version__}"
    except Exception as exc:
        raise OCRUnavailable(str(exc)) from exc


def _passes(bgr: np.ndarray):
    g = imaging.gray(bgr)
    up = imaging.upscale_to(g, 1400)
    enh = imaging.sharpen(imaging.clahe(up))
    yield "enhanced/sparse", enh, 11
    yield "binary/block", imaging.adaptive_bin(enh), 6


def run(bgr: np.ndarray, date_order: str = "DMY", deep: bool = True) -> dict:
    t0 = time.perf_counter()
    eng = engine_name()
    passes_out = []
    extractions = []

    def do(name, img, psm, rotation=0):
        if rotation:
            img = cv2.rotate(img, {90: cv2.ROTATE_90_CLOCKWISE, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}[rotation])
        if eng == "easyocr":
            lines = _easy_lines(img)
        elif eng == "paddleocr":
            lines = _paddle_lines(img)
        else:
            lines = _tess_lines(img, psm)
        ex = dates_mod.extract(lines, date_order=date_order)
        passes_out.append({"pass": name + (f"/rot{rotation}" if rotation else ""), "lines": lines})
        extractions.append(ex)
        return ex

    if imaging.edge_density(imaging.gray(bgr)) < 0.003:
        empty = dates_mod.merge_passes([])
        return {"engine": eng, "text": "", "lines": [], "passes": [], "mean_confidence": 0.0, "dates": empty,
                "skipped": "image has no visible detail", "elapsed_ms": int((time.perf_counter() - t0) * 1000)}

    if eng == "tesseract":
        variants = list(_passes(bgr))
        for name, img, psm in variants:
            do(name, img, psm)
        # Expiry codes are often printed sideways. If nothing labelled was found, try rotations.
        if deep and not any(e["expiry"] or e["mfg"] or e["packed"] for e in extractions):
            for rot in (90, 270):
                ex = do(variants[0][0], variants[0][1], 11, rot)
                if ex["expiry"] or ex["mfg"]:
                    break
    else:
        do(eng, bgr, 0)

    merged = dates_mod.merge_passes(extractions)
    # human-readable text: the pass with the most confident characters
    best = max(passes_out, key=lambda p: sum(len(t) * c for t, c in p["lines"])) if passes_out else {"lines": []}
    text = "\n".join(t for t, _ in best["lines"])
    all_conf = [c for p in passes_out for _, c in p["lines"]]
    return {
        "engine": eng,
        "text": text,
        "lines": [{"text": t, "confidence": c} for t, c in best["lines"]],
        "passes": [{"pass": p["pass"], "line_count": len(p["lines"]),
                    "text": "\n".join(t for t, _ in p["lines"])} for p in passes_out],
        "mean_confidence": round(float(np.mean(all_conf)), 3) if all_conf else 0.0,
        "dates": merged,
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def self_test() -> dict:
    """Render known text and check the engine reads it and the parser labels it."""
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (900, 220), "white")
    d = ImageDraw.Draw(img)
    font = None
    for f in ("DejaVuSans-Bold.ttf", "arialbd.ttf", "Arial Bold.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf"):
        try:
            font = ImageFont.truetype(f, 44)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    d.text((30, 30), "MFG: 05/2026", fill="black", font=font)
    d.text((30, 120), "EXP: 04/2028", fill="black", font=font)
    bgr = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
    try:
        r = run(bgr, deep=False)
    except OCRUnavailable as exc:
        return {"ok": False, "error": str(exc), "engine": engine_name()}
    exp = (r["dates"]["expiry"] or {}).get("value")
    mfg = (r["dates"]["mfg"] or {}).get("value")
    ok = exp == "2028-04" and mfg == "2026-05"
    return {"ok": ok, "engine": engine_name(), "version": engine_version(), "read_text": r["text"],
            "expected": {"expiry": "2028-04", "mfg": "2026-05"}, "got": {"expiry": exp, "mfg": mfg},
            "elapsed_ms": r["elapsed_ms"]}
