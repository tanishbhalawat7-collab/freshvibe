"""Render realistic-ish packaging test images (barcode + printed text) into tests/fixtures.
These are test inputs for the automated suite -- the app itself never uses them."""
from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np
import zxingcpp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).parent / "fixtures"


def font(size, bold=False):
    for f in (("DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"), "arial.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def barcode_img(text, fmt, scale=3):
    return Image.fromarray(np.array(zxingcpp.create_barcode(text, zxingcpp.barcode_format_from_str(fmt)).to_image(scale=scale)))


def camera_like(img: Image.Image, blur=0.8, noise=6, jpeg=82) -> bytes:
    img = img.filter(ImageFilter.GaussianBlur(blur))
    a = np.array(img).astype(np.int16)
    a += np.random.default_rng(1).normal(0, noise, a.shape).astype(np.int16)
    a = np.clip(a, 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", cv2.cvtColor(a, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, jpeg])
    return buf.tobytes()


def pack_full():
    """Barcode + name + labelled MFD/EXP + batch -- everything on one side."""
    img = Image.new("RGB", (1024, 768), (236, 240, 232))
    d = ImageDraw.Draw(img)
    d.rectangle([40, 40, 984, 728], fill=(255, 255, 255), outline=(30, 90, 60), width=6)
    d.text((80, 80), "GREEN VALLEY", fill=(20, 80, 50), font=font(54, True))
    d.text((80, 150), "Organic Peanut Butter", fill=(30, 30, 30), font=font(40))
    d.text((80, 300), "BATCH NO: GV2417", fill=(0, 0, 0), font=font(34, True))
    d.text((80, 360), "MFD: 12/05/2026", fill=(0, 0, 0), font=font(34, True))
    d.text((80, 420), "EXP: 11/05/2027", fill=(0, 0, 0), font=font(34, True))
    d.text((80, 480), "MRP Rs. 249.00 (Incl. of all taxes)", fill=(60, 60, 60), font=font(26))
    img.paste(barcode_img("8906010501235", "EAN13", 3), (620, 330))
    return img


def pack_month_only():
    img = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 60), "Instant Noodles Masala", fill="black", font=font(40, True))
    d.text((60, 200), "PKD: MAR 2026", fill="black", font=font(38, True))
    d.text((60, 270), "BEST BEFORE: SEP 2026", fill="black", font=font(38, True))
    return img


def pack_shelf_life():
    img = Image.new("RGB", (900, 600), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 80), "Mfg. Date: 05/2026", fill="black", font=font(38, True))
    d.text((60, 160), "Best before 18 months", fill="black", font=font(38, True))
    d.text((60, 220), "from manufacture", fill="black", font=font(38, True))
    return img


def pack_unlabeled():
    img = Image.new("RGB", (900, 500), "white")
    d = ImageDraw.Draw(img)
    d.text((60, 100), "14/02/2026", fill="black", font=font(44, True))
    d.text((60, 220), "13/02/2028", fill="black", font=font(44, True))
    return img


def barcodes_sheet():
    img = Image.new("RGB", (1300, 900), "white")
    items = [("8901063010147", "EAN13"), ("96385074", "EAN8"), ("036000291452", "UPCA"), ("01234565", "UPCE"),
             ("FV-CODE128-42", "Code128"), ("CODE39TEST", "Code39"), ("https://freshvibe.local/p/42", "QRCode")]
    out = {}
    for text, fmt in items:
        bc = barcode_img(text, fmt, 3 if fmt != "QRCode" else 8)
        im = Image.new("RGB", (bc.width + 160, bc.height + 160), "white")
        im.paste(bc, (80, 80))
        out[fmt] = (text, im)
    return out


def main():
    OUT.mkdir(exist_ok=True)
    (OUT / "pack_full.jpg").write_bytes(camera_like(pack_full()))
    (OUT / "pack_month_only.jpg").write_bytes(camera_like(pack_month_only()))
    (OUT / "pack_shelf_life.jpg").write_bytes(camera_like(pack_shelf_life()))
    (OUT / "pack_unlabeled.jpg").write_bytes(camera_like(pack_unlabeled()))
    (OUT / "pack_rotated.jpg").write_bytes(camera_like(pack_month_only().rotate(90, expand=True)))
    blank = Image.new("RGB", (800, 600), (128, 128, 128))
    (OUT / "blank.jpg").write_bytes(camera_like(blank, blur=3))
    for fmt, (text, im) in barcodes_sheet().items():
        (OUT / f"bc_{fmt}.jpg").write_bytes(camera_like(im, blur=0.6, noise=5))
        (OUT / f"bc_{fmt}.txt").write_text(text)
    print("fixtures written to", OUT)


if __name__ == "__main__":
    sys.exit(main())
