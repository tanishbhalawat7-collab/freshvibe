"""TEST TOOL ONLY - emulates the HTTP interface of the AI Thinker CameraWebServer
sketch so the automated tests can exercise the bridge without hardware:
  * GET :<capture_port>/capture -> JPEG file
  * GET :<stream_port>/stream   -> multipart/x-mixed-replace MJPEG
  * GET /status                 -> 404 (like the user's device)
The application never starts or depends on this. Use your real ESP32-CAM.

    python tests/esp32_emulator.py tests/fixtures/pack_full.jpg --capture-port 8080 --stream-port 8081
"""
from __future__ import annotations

import argparse
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

BOUNDARY = "123456789000000000000987654321"


def make_handler(image_path: Path, role: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            jpeg = image_path.read_bytes()
            if role == "capture" and self.path.startswith("/capture"):
                self.send_response(200)
                self.send_header("Content-Type", "image/jpeg")
                self.send_header("Content-Length", str(len(jpeg)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(jpeg)
            elif role == "capture" and self.path.startswith("/control"):
                self.send_response(200)
                self.end_headers()
            elif role == "stream" and self.path.startswith("/stream"):
                self.send_response(200)
                self.send_header("Content-Type", f"multipart/x-mixed-replace;boundary={BOUNDARY}")
                self.end_headers()
                try:
                    while True:
                        part = (f"\r\n--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n"
                                f"X-Timestamp: {time.time():.6f}\r\n\r\n").encode()
                        self.wfile.write(part + jpeg)
                        self.wfile.flush()
                        time.sleep(0.1)
                except (BrokenPipeError, ConnectionResetError):
                    return
            else:
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"Not Found")
    return H


def serve(image: Path, capture_port: int, stream_port: int, host: str = "127.0.0.1"):
    servers = [ThreadingHTTPServer((host, capture_port), make_handler(image, "capture")),
               ThreadingHTTPServer((host, stream_port), make_handler(image, "stream"))]
    for s in servers:
        s.daemon_threads = True
        threading.Thread(target=s.serve_forever, daemon=True).start()
    return servers


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("image", type=Path)
    ap.add_argument("--capture-port", type=int, default=8080)
    ap.add_argument("--stream-port", type=int, default=8081)
    a = ap.parse_args()
    serve(a.image, a.capture_port, a.stream_port)
    print(f"emulator: capture :{a.capture_port}/capture  stream :{a.stream_port}/stream  (Ctrl+C to stop)")
    while True:
        time.sleep(3600)
