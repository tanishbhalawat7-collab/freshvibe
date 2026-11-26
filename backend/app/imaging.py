"""Image loading and preprocessing shared by the barcode and OCR stages."""
from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageOps


class ImageError(ValueError):
    pass


MAX_UPLOAD_BYTES = 15 * 1024 * 1024


def load_image(data: bytes) -> np.ndarray:
    """Decode bytes (JPEG/PNG/WebP/...) into a BGR array, honouring EXIF rotation."""
    if not data:
        raise ImageError("Empty image.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise ImageError("Image is larger than 15 MB.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im = ImageOps.exif_transpose(im).convert("RGB")
            arr = np.array(im)
    except Exception as exc:
        raise ImageError(f"Unsupported or corrupt image: {exc}") from exc
    if arr.shape[0] < 40 or arr.shape[1] < 40:
        raise ImageError("Image is too small to analyse.")
    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def to_jpeg(bgr: np.ndarray, quality: int = 90) -> bytes:
    ok, buf = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise ImageError("Could not encode JPEG.")
    return buf.tobytes()


def gray(bgr: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY) if bgr.ndim == 3 else bgr


def upscale_to(img: np.ndarray, min_side: int) -> np.ndarray:
    h, w = img.shape[:2]
    short = min(h, w)
    if short >= min_side:
        return img
    f = min(min_side / short, 4.0)
    return cv2.resize(img, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)


def clahe(g: np.ndarray) -> np.ndarray:
    return cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(g)


def sharpen(g: np.ndarray) -> np.ndarray:
    blur = cv2.GaussianBlur(g, (0, 0), 2.0)
    return cv2.addWeighted(g, 1.6, blur, -0.6, 0)


def adaptive_bin(g: np.ndarray) -> np.ndarray:
    g = cv2.medianBlur(g, 3)
    return cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 41, 18)


def otsu(g: np.ndarray) -> np.ndarray:
    _, b = cv2.threshold(cv2.GaussianBlur(g, (3, 3), 0), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return b


def sharpness(g: np.ndarray) -> float:
    """Variance of Laplacian -- low values mean a blurry photo."""
    return float(cv2.Laplacian(g, cv2.CV_64F).var())


def edge_density(g: np.ndarray) -> float:
    """Fraction of edge pixels; ~0 means a blank / fully blurred frame (no text to read)."""
    h, w = g.shape[:2]
    s = cv2.resize(g, (640, max(1, int(640 * h / w)))) if w > 640 else g
    return float(cv2.Canny(cv2.GaussianBlur(s, (3, 3), 0), 60, 150).mean() / 255)


def quality_report(bgr: np.ndarray) -> dict:
    g = gray(bgr)
    h, w = g.shape[:2]
    sharp = sharpness(cv2.resize(g, (640, int(640 * h / w))) if w > 640 else g)
    bright = float(g.mean())
    edges = edge_density(g)
    issues = []
    if edges < 0.003:
        issues.append("The image has almost no detail (lens cap on, pointing at a wall, or completely out of focus).")
    if min(h, w) < 480:
        issues.append(f"Low resolution ({w}x{h}). Set the ESP32-CAM frame size to SVGA (800x600) or higher for reliable text reading.")
    if sharp < 60:
        issues.append("Image looks blurry. Hold the product still, 10-20 cm from the lens, and adjust the lens focus if needed.")
    if bright < 60:
        issues.append("Image is dark. Turn on the flash LED or add light.")
    elif bright > 215:
        issues.append("Image is over-exposed or has glare. Tilt the package away from the light.")
    return {"width": w, "height": h, "sharpness": round(sharp, 1), "brightness": round(bright, 1),
            "edge_density": round(edges, 4), "issues": issues}
