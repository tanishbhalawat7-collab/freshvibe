"""Real barcode decoding and OCR on rendered camera-like images."""
from pathlib import Path

import pytest

from app import barcode, imaging, ocr

FX = Path(__file__).parent / "fixtures"
EQUIV = {"UPCA": "036000291452", "UPCE": "0012345000065"}


def img(name):
    return imaging.load_image((FX / name).read_bytes())


@pytest.mark.parametrize("fmt", ["EAN13", "EAN8", "UPCA", "UPCE", "Code128", "Code39", "QRCode"])
def test_barcode_formats(fmt):
    expected = (FX / f"bc_{fmt}.txt").read_text()
    got = [c["text"] for c in barcode.decode(img(f"bc_{fmt}.jpg"))["codes"]]
    assert expected in got or EQUIV.get(fmt) in got, got


def test_full_pack():
    bgr = img("pack_full.jpg")
    assert barcode.decode(bgr)["codes"][0]["text"] == "8906010501235"
    d = ocr.run(bgr)["dates"]
    assert d["expiry"]["value"] == "2027-05-11"
    assert d["mfg"]["value"] == "2026-05-12"
    assert d["batch"]["value"] == "GV2417"


def test_month_only_and_rotated():
    for f in ("pack_month_only.jpg", "pack_rotated.jpg"):
        d = ocr.run(img(f))["dates"]
        assert d["expiry"]["value"] == "2026-09" and d["expiry"]["precision"] == "month"
        assert d["packed"]["value"] == "2026-03"


def test_shelf_life_pack():
    d = ocr.run(img("pack_shelf_life.jpg"))["dates"]
    assert d["expiry"]["value"] == "2027-10" and d["expiry"]["derived"]


def test_unlabelled_pack_not_assumed():
    d = ocr.run(img("pack_unlabeled.jpg"))["dates"]
    assert d["expiry"] is None and len([x for x in d["all_dates"] if x["kind"] == "unlabeled"]) == 2


def test_blank_image_reads_nothing():
    r = ocr.run(img("blank.jpg"))
    assert r["text"] == "" and not barcode.decode(img("blank.jpg"))["found"]


def test_self_tests():
    assert ocr.self_test()["ok"] and barcode.self_test()["ok"]
