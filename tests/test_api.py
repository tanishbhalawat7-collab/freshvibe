"""End-to-end API tests against the ESP32 emulator (stands in for real hardware)."""
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import conftest
import esp32_emulator

FX = Path(__file__).parent / "fixtures"
CAM_IMG = Path(conftest.os.environ["DATA_DIR"]) / "camera.jpg"


@pytest.fixture(scope="module")
def client():
    shutil.copy(FX / "pack_full.jpg", CAM_IMG)
    servers = esp32_emulator.serve(CAM_IMG, conftest.CAP, conftest.STR)
    from app.main import app
    with TestClient(app) as c:
        yield c
    for s in servers:
        s.shutdown()


def test_health_and_json_errors(client):
    assert client.get("/api/health").json()["ok"]
    r = client.get("/api/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    r = client.get("/api/products/99999")
    assert r.status_code == 404 and r.json()["error"]["code"] == "product_not_found"


def test_frontend_served(client):
    assert "Fresh Vibe" in client.get("/").text
    assert client.get("/js/app.js").status_code == 200


def test_camera_health_is_real_capture(client):
    r = client.get("/api/camera/health").json()
    assert r["ok"] and r["status"] == "connected" and r["check"]["bytes"] > 1000
    img = client.get("/api/camera/capture")
    assert img.status_code == 200 and img.content[:2] == b"\xff\xd8"


def test_camera_ip_configurable_and_validated(client):
    assert client.put("/api/settings", json={"camera_ip": "8.8.8.8"}).status_code == 422
    assert client.put("/api/settings", json={"camera_stream_port": conftest.CAP}).status_code == 422
    # point at a dead port -> must NOT be connected
    r = client.post("/api/camera/connect", json={"camera_ip": "127.0.0.1", "camera_capture_port": 9}).json()
    assert not r["ok"] and r["status"] == "disconnected" and r["error"]["code"] in ("refused", "unreachable", "timeout")
    r = client.post("/api/scan/process", data={"source": "camera"})
    assert r.status_code == 503 and r.json()["error"]["code"].startswith("camera_")
    r = client.post("/api/camera/connect", json={"camera_capture_port": conftest.CAP}).json()
    assert r["ok"]


def test_stream_relay(client):
    """Relay real MJPEG frames from the emulated port-81 stream (TestClient can't
    consume an endless response, so drive the hub directly)."""
    import asyncio

    from app.camera import CameraBridge, validate_jpeg

    async def grab():
        bridge = CameraBridge()
        frames = []
        async for f in bridge.stream.subscribe():
            frames.append(f)
            if len(frames) == 3:
                break
        await bridge.stream.shutdown()
        return frames, bridge.stream.status()

    frames, status = asyncio.run(grab())
    assert len(frames) == 3 and all(validate_jpeg(f) == (1024, 768) for f in frames)
    assert status["frames"] >= 3


def test_scan_needs_confirmation_then_auto_saves_and_dedupes(client):
    r = client.post("/api/scan/process", data={"source": "camera"}).json()
    assert r["decision"]["status"] == "needs_confirmation"  # name unknown, lookup disabled
    f = r["fields"]
    assert f["barcode"]["value"] == "8906010501235" and f["expiry_date"]["value"] == "2027-05-11"
    assert f["mfg_date"]["value"] == "2026-05-12" and "name" in r["decision"]["uncertain_fields"]
    body = {"scan_id": r["scan_id"], "name": "Organic Peanut Butter", "brand": "Green Valley", "category": "Grocery",
            "barcode": f["barcode"]["value"], "expiry_date": f["expiry_date"]["value"],
            "mfg_date": f["mfg_date"]["value"], "batch_no": f["batch_no"]["value"]}
    saved = client.post("/api/products", json=body).json()
    assert not saved["duplicate"] and saved["product"]["verification_status"] == "user_verified"
    # barcode is now known locally -> second scan is saved automatically, as a duplicate (qty 2)
    r2 = client.post("/api/scan/process", data={"source": "camera"}).json()
    assert r2["decision"]["status"] == "saved" and r2["saved"]["duplicate"]
    assert r2["saved"]["product"]["quantity"] == 2


def test_upload_and_merge_two_sides(client):
    a = client.post("/api/scan/process", files={"image": ("b.jpg", (FX / "bc_EAN13.jpg").read_bytes(), "image/jpeg")}).json()
    assert a["fields"]["barcode"]["value"] == "8901063010147" and not a["fields"]["expiry_date"]["value"]
    b = client.post("/api/scan/process", data={"merge_with": a["scan_id"]},
                    files={"image": ("d.jpg", (FX / "pack_month_only.jpg").read_bytes(), "image/jpeg")}).json()
    assert b["fields"]["barcode"]["value"] == "8901063010147" and b["fields"]["expiry_date"]["value"] == "2026-09"


def test_barcode_and_ocr_endpoints(client):
    r = client.post("/api/scan/barcode", files={"image": ("q.jpg", (FX / "bc_QRCode.jpg").read_bytes(), "image/jpeg")}).json()
    assert r["codes"][0]["format"] == "QR Code"
    r = client.post("/api/scan/ocr", files={"image": ("p.jpg", (FX / "pack_shelf_life.jpg").read_bytes(), "image/jpeg")}).json()
    assert r["dates"]["expiry"]["value"] == "2027-10"
    assert client.post("/api/scan/ocr", files={"image": ("x.txt", b"hello", "text/plain")}).status_code == 415


def test_products_crud_status_and_notifications(client):
    today = date.today()
    mk = lambda **k: client.post("/api/products", json=k).json()["product"]
    tomorrow = mk(name="Milk", category="Dairy", expiry_date=(today + timedelta(days=1)).isoformat())
    expired = mk(name="Bread", category="Bakery", expiry_date=(today - timedelta(days=2)).isoformat())
    month = mk(name="Syrup", category="Medicine", expiry_date=today.strftime("%Y-%m"), expiry_precision="month")
    unknown = mk(name="Soap", category="Personal Care")
    assert tomorrow["status"] == "expiring_soon" and expired["status"] == "expired"
    assert month["status"] == "expiring_soon" and month["expiry_date"] == today.strftime("%Y-%m")
    assert unknown["status"] == "unknown"
    assert client.post("/api/products", json={"name": "X", "expiry_date": "2027-02-30"}).status_code == 422
    n1 = client.get("/api/notifications").json()
    kinds = {(n["product_id"], n["kind"]) for n in n1["items"]}
    assert (tomorrow["id"], "tomorrow") in kinds and (expired["id"], "expired") in kinds
    n2 = client.get("/api/notifications").json()
    assert len(n2["items"]) == len(n1["items"])  # no duplicates
    upd = client.put(f"/api/products/{tomorrow['id']}", json={"expiry_date": (today + timedelta(days=200)).isoformat()}).json()
    assert upd["status"] == "fresh"
    s = client.get("/api/expiry/summary").json()
    assert s["expired"] >= 1 and s["unknown"] >= 1
    assert client.get("/api/products?status=expired&sort=name").json()["total"] >= 1
    assert client.delete(f"/api/products/{unknown['id']}").json()["ok"]


def test_diagnostics(client):
    d = client.get("/api/diagnostics").json()
    assert d["database"]["ok"] and d["camera"]["ok"] and d["barcode"]["ok"] and d["ocr"]["ok"]
    assert d["ai"]["configured"] is False


def test_token_auth(client, monkeypatch):
    from app.config import config
    monkeypatch.setattr(config, "API_TOKEN", "s3cret-token")
    assert client.get("/api/products").status_code == 401
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/products", headers={"Authorization": "Bearer s3cret-token"}).status_code == 200
    assert client.post("/api/auth/login", json={"token": "wrong"}).status_code == 401
    assert client.post("/api/auth/login", json={"token": "s3cret-token"}).status_code == 200
    assert client.get("/api/products").status_code == 200  # cookie
    assert client.post("/api/products", json={"name": "csrf"}).status_code == 403  # cookie w/o header
    client.cookies.clear()
