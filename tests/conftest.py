"""Test setup: isolated data dir + the ESP32 emulator on free local ports."""
import os
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tests"))


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


CAP, STR = _free_port(), _free_port()
os.environ.update({
    "DATA_DIR": tempfile.mkdtemp(prefix="fv-test-"), "CAMERA_IP": "127.0.0.1",
    "CAMERA_CAPTURE_PORT": str(CAP), "CAMERA_STREAM_PORT": str(STR),
    "ENABLE_ONLINE_LOOKUP": "false", "AI_PROVIDER": "", "API_TOKEN": "", "CORS_ORIGINS": "",
})
FIXTURES = ROOT / "tests" / "fixtures"
if not (FIXTURES / "pack_full.jpg").exists():
    import make_fixtures
    make_fixtures.main()
