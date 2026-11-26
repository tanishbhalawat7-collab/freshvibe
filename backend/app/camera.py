"""ESP32-CAM bridge.

The browser never talks to the camera. This module (running on a machine on the
same LAN as the ESP32-CAM) fetches:
  * still images from  http://<ip>:<capture_port>/capture   (port 80 by default)
  * MJPEG video from   http://<ip>:<stream_port>/stream     (port 81 by default)
and re-serves them through the backend's own (HTTPS-able) API.

Health is defined as: a /capture request returned HTTP 200 with a decodable
JPEG. The firmware's /status endpoint is never used.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx
from PIL import Image

from . import settings_store
from .database import session_scope
from .models import CameraLog

log = logging.getLogger("freshvibe.camera")

MAX_LOG_ROWS = 300


class CameraError(Exception):
    def __init__(self, code: str, message: str, hint: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.hint = hint

    def as_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "hint": self.hint}


@dataclass
class CaptureResult:
    jpeg: bytes
    width: int
    height: int
    elapsed_ms: int
    source: str  # "capture" or "stream_frame"
    url: str


@dataclass
class CameraState:
    status: str = "unknown"  # unknown | connecting | connected | disconnected
    last_success_at: datetime | None = None
    last_attempt_at: datetime | None = None
    last_error: dict | None = None
    last_resolution: tuple[int, int] | None = None
    last_latency_ms: int | None = None
    consecutive_failures: int = 0
    auto_reconnect_paused: bool = False
    reconnect_attempt: int = 0
    next_check_at: datetime | None = None


def now() -> datetime:
    return datetime.now(timezone.utc)


def add_log(level: str, message: str) -> None:
    getattr(log, {"warn": "warning"}.get(level, level), log.info)(message)
    try:
        with session_scope() as db:
            db.add(CameraLog(level=level, message=message[:600]))
            count = db.query(CameraLog).count()
            if count > MAX_LOG_ROWS:
                cutoff = (
                    db.query(CameraLog.id).order_by(CameraLog.id.desc()).offset(MAX_LOG_ROWS).limit(1).scalar()
                )
                if cutoff:
                    db.query(CameraLog).filter(CameraLog.id <= cutoff).delete()
    except Exception:  # logging must never break the camera path
        log.exception("could not persist camera log")


def capture_url() -> str:
    s = settings_store.get_all()
    port = int(s["camera_capture_port"])
    host = s["camera_ip"]
    return f"http://{host}/capture" if port == 80 else f"http://{host}:{port}/capture"


def stream_url() -> str:
    s = settings_store.get_all()
    return f"http://{s['camera_ip']}:{int(s['camera_stream_port'])}/stream"


def validate_jpeg(data: bytes) -> tuple[int, int]:
    if len(data) < 500:
        raise CameraError("invalid_image", f"Camera returned only {len(data)} bytes, not a JPEG image.",
                          "The sensor may have failed to grab a frame. Try again, or press RESET on the ESP32-CAM.")
    if data[:2] != b"\xff\xd8":
        snippet = data[:60].decode("latin-1", "replace")
        raise CameraError("invalid_image", "Response is not a JPEG (missing FFD8 header).",
                          f"First bytes: {snippet!r}. Make sure the IP belongs to the ESP32-CAM running CameraWebServer.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            return im.size
    except Exception as exc:
        raise CameraError("invalid_image", f"JPEG could not be decoded: {exc}",
                          "The frame was probably truncated (weak Wi-Fi). Move the camera closer to the router.")


def _classify(exc: Exception, url: str, timeout: float) -> CameraError:
    host = url.split("//", 1)[1].split("/", 1)[0]
    if isinstance(exc, httpx.ConnectTimeout):
        return CameraError("timeout", f"No answer from {host} within {timeout:.0f}s.",
                           "Check the ESP32-CAM is powered, on the same Wi-Fi/LAN as this bridge computer, and that the IP "
                           "matches the one printed in the Arduino Serial Monitor.")
    if isinstance(exc, httpx.ReadTimeout):
        return CameraError("timeout", f"{host} accepted the connection but did not send an image within {timeout:.0f}s.",
                           "The camera may be busy or low on power. Use a 5V/2A supply; close other viewers of the stream.")
    if isinstance(exc, httpx.ConnectError):
        msg = str(exc) or exc.__class__.__name__
        if "refused" in msg.lower():
            return CameraError("refused", f"{host} refused the connection.",
                               "A device answers at this IP but nothing listens on that port. Capture is port 80, stream is 81.")
        return CameraError("unreachable", f"Cannot reach {host}: {msg}",
                           "This computer and the ESP32-CAM must be on the same network. A cloud server cannot reach "
                           "a 192.168.x.x address -- run the bridge on your LAN.")
    if isinstance(exc, httpx.RemoteProtocolError):
        return CameraError("protocol", f"{host} closed the connection mid-response.",
                           "Usually a Wi-Fi drop or brown-out. Retry; check power supply.")
    return CameraError("network", f"{exc.__class__.__name__}: {exc}", "")


class CameraBridge:
    def __init__(self) -> None:
        self.state = CameraState()
        self._capture_lock = asyncio.Lock()
        self.last_image: bytes | None = None
        self.last_image_at: datetime | None = None
        self.stream = StreamHub(self)
        self._monitor_task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    # ------------------------------------------------------------------ capture
    async def capture(self, *, retries: int | None = None, allow_stream_frame: bool = True,
                      reason: str = "capture") -> CaptureResult:
        s = settings_store.get_all()
        timeout = float(s["camera_timeout_s"])
        retries = int(retries or s["camera_retries"])
        url = capture_url()
        last_err: CameraError | None = None
        async with self._capture_lock:
            if self.state.status != "connected":
                self.state.status = "connecting"
            for attempt in range(1, retries + 1):
                self.state.last_attempt_at = now()
                t0 = time.perf_counter()
                try:
                    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=min(timeout, 5.0))) as client:
                        resp = await client.get(url, headers={"Cache-Control": "no-cache"})
                    if resp.status_code != 200:
                        hint = ("Is the CameraWebServer sketch running? /capture lives on port 80."
                                if resp.status_code == 404 else "")
                        raise CameraError("http_error", f"Camera answered HTTP {resp.status_code} for /capture.", hint)
                    w, h = validate_jpeg(resp.content)
                    ms = int((time.perf_counter() - t0) * 1000)
                    self._mark_ok(w, h, ms, reason)
                    self.last_image, self.last_image_at = resp.content, now()
                    return CaptureResult(resp.content, w, h, ms, "capture", url)
                except CameraError as ce:
                    last_err = ce
                except httpx.HTTPError as he:
                    last_err = _classify(he, url, timeout)
                add_log("warn", f"{reason}: attempt {attempt}/{retries} failed - {last_err.message}")
                if attempt < retries:
                    await asyncio.sleep(min(0.6 * 2 ** (attempt - 1), 4))

            # Direct capture failed. If the live stream is currently delivering
            # real frames, a frame from the last 2 s is still a genuine image.
            frame = self.stream.recent_frame(max_age_s=2.0) if allow_stream_frame else None
            if frame:
                w, h = validate_jpeg(frame)
                add_log("info", f"{reason}: used live-stream frame because /capture was busy")
                self._mark_ok(w, h, 0, reason, quiet=True)
                return CaptureResult(frame, w, h, 0, "stream_frame", stream_url())

            self._mark_fail(last_err)
            raise last_err

    def _mark_ok(self, w: int, h: int, ms: int, reason: str, quiet: bool = False) -> None:
        was = self.state.status
        st = self.state
        st.status, st.last_success_at, st.last_error = "connected", now(), None
        st.last_resolution, st.consecutive_failures = (w, h), 0
        st.reconnect_attempt, st.auto_reconnect_paused = 0, False
        if ms:
            st.last_latency_ms = ms
        if was != "connected" and not quiet:
            add_log("info", f"Camera connected ({w}x{h} JPEG in {ms} ms via {reason}).")

    def _mark_fail(self, err: CameraError) -> None:
        st = self.state
        if st.status == "connected":
            add_log("error", f"Camera connection lost: {err.message}")
        else:
            add_log("error", f"Camera unavailable: {err.message}")
        st.status, st.last_error = "disconnected", err.as_dict()
        st.consecutive_failures += 1

    async def health(self) -> dict:
        """Real health check: a full capture; nothing is cached."""
        try:
            res = await self.capture(reason="health check", allow_stream_frame=False)
            return {"ok": True, **self.snapshot(),
                    "check": {"bytes": len(res.jpeg), "width": res.width, "height": res.height,
                              "latency_ms": res.elapsed_ms}}
        except CameraError as ce:
            return {"ok": False, **self.snapshot(), "error": ce.as_dict()}

    def snapshot(self) -> dict:
        st = self.state
        s = settings_store.get_all()
        return {
            "status": st.status,
            "camera_ip": s["camera_ip"],
            "capture_url": capture_url(),
            "stream_url": stream_url(),
            "last_success_at": st.last_success_at.isoformat() if st.last_success_at else None,
            "last_attempt_at": st.last_attempt_at.isoformat() if st.last_attempt_at else None,
            "last_error": st.last_error,
            "resolution": list(st.last_resolution) if st.last_resolution else None,
            "latency_ms": st.last_latency_ms,
            "consecutive_failures": st.consecutive_failures,
            "auto_reconnect_paused": st.auto_reconnect_paused,
            "reconnect_attempt": st.reconnect_attempt,
            "next_check_at": st.next_check_at.isoformat() if st.next_check_at else None,
            "last_image_at": self.last_image_at.isoformat() if self.last_image_at else None,
            "stream": self.stream.status(),
        }

    def reset_connection(self) -> None:
        """Called after the IP/ports change or when the user presses Connect."""
        self.state = CameraState()
        self.last_image = None
        self.last_image_at = None
        self.stream.restart()
        self._wake.set()

    # ----------------------------------------------------------- auto reconnect
    MAX_AUTO_RECONNECT = 6

    async def monitor(self) -> None:
        """Periodic real-capture health checks with bounded exponential backoff."""
        await asyncio.sleep(2)
        while True:
            interval = int(settings_store.get("camera_monitor_interval_s"))
            st = self.state
            if interval == 0 or st.auto_reconnect_paused:
                delay = 30.0
            elif st.status == "disconnected":
                if st.reconnect_attempt >= self.MAX_AUTO_RECONNECT:
                    st.auto_reconnect_paused = True
                    add_log("warn", f"Auto-reconnect paused after {self.MAX_AUTO_RECONNECT} failed attempts. "
                                    "Press 'Connect' on the Camera page to try again.")
                    delay = 30.0
                else:
                    delay = min(5 * 2 ** st.reconnect_attempt, 300)
            else:
                delay = float(interval)
            st.next_check_at = datetime.fromtimestamp(time.time() + delay, timezone.utc)
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=delay)
                continue  # woken by settings change / connect -> recompute
            except asyncio.TimeoutError:
                pass
            st = self.state
            if interval == 0 or st.auto_reconnect_paused:
                continue
            # don't hammer /capture while a stream is live and healthy
            if self.stream.recent_frame(max_age_s=3):
                self._mark_ok(*(st.last_resolution or (0, 0)), 0, "stream", quiet=True)
                continue
            if st.status == "disconnected":
                st.reconnect_attempt += 1
                add_log("info", f"Auto-reconnect attempt {st.reconnect_attempt}/{self.MAX_AUTO_RECONNECT}")
            try:
                await self.capture(retries=1 if st.status == "disconnected" else None,
                                   reason="background check", allow_stream_frame=False)
            except CameraError:
                pass
            except Exception:
                log.exception("monitor error")

    def start(self) -> None:
        if self._monitor_task is None:
            self._monitor_task = asyncio.create_task(self.monitor())

    async def stop(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()
        await self.stream.shutdown()


class StreamHub:
    """One upstream MJPEG connection to the ESP32 fanned out to any number of
    browser viewers (the ESP32 firmware only serves one stream client)."""

    BOUNDARY = "freshvibeframe"

    def __init__(self, bridge: CameraBridge) -> None:
        self.bridge = bridge
        self.subscribers: set[asyncio.Queue] = set()
        self._task: asyncio.Task | None = None
        self.latest: bytes | None = None
        self.latest_at: float = 0.0
        self.error: dict | None = None
        self.connected = False
        self.frames = 0
        self._fps_window: list[float] = []

    def status(self) -> dict:
        return {
            "active": self._task is not None and not self._task.done(),
            "connected": self.connected,
            "viewers": len(self.subscribers),
            "fps": round(self.fps(), 1),
            "frames": self.frames,
            "last_frame_age_s": round(time.time() - self.latest_at, 1) if self.latest_at else None,
            "error": self.error,
        }

    def fps(self) -> float:
        cutoff = time.time() - 3
        w = [t for t in self._fps_window if t > cutoff]
        return len(w) / 3 if w else 0.0

    def recent_frame(self, max_age_s: float) -> bytes | None:
        if self.connected and self.latest and time.time() - self.latest_at <= max_age_s:
            return self.latest
        return None

    def restart(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None
        self.connected = False
        self.latest = None
        if self.subscribers:
            self._ensure()

    async def shutdown(self) -> None:
        if self._task:
            self._task.cancel()
        for q in list(self.subscribers):
            q.put_nowait(None)

    def _ensure(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run())

    def _publish(self, frame: bytes) -> None:
        self.latest, self.latest_at = frame, time.time()
        self.frames += 1
        self._fps_window.append(self.latest_at)
        if len(self._fps_window) > 120:
            self._fps_window = self._fps_window[-60:]
        for q in list(self.subscribers):
            if q.full():
                try:
                    q.get_nowait()  # drop the oldest frame for slow viewers
                except asyncio.QueueEmpty:
                    pass
            q.put_nowait(frame)

    async def _run(self) -> None:
        url = stream_url()
        fails = 0
        while self.subscribers:
            try:
                timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    async with client.stream("GET", url) as resp:
                        if resp.status_code != 200:
                            raise CameraError("http_error", f"Stream answered HTTP {resp.status_code}.",
                                              "The live stream is served on port 81 at /stream.")
                        ctype = resp.headers.get("content-type", "")
                        if "multipart" not in ctype:
                            raise CameraError("invalid_stream", f"Unexpected stream content-type '{ctype}'.",
                                              "Expected multipart/x-mixed-replace from CameraWebServer port 81.")
                        add_log("info", f"Live stream connected ({url}).")
                        self.error = None
                        buf = bytearray()
                        async for chunk in resp.aiter_bytes():
                            buf.extend(chunk)
                            for frame in _extract_jpegs(buf):
                                if not self.connected:
                                    self.connected = True
                                fails = 0
                                self._publish(frame)
                            if len(buf) > 4_000_000:  # corrupt stream guard
                                buf.clear()
                            if not self.subscribers:
                                break
                if not self.subscribers:
                    break
                raise CameraError("stream_ended", "Camera closed the live stream.", "")
            except asyncio.CancelledError:
                raise
            except CameraError as ce:
                err = ce
            except httpx.HTTPError as he:
                err = _classify(he, url, 10.0)
            except Exception as exc:  # pragma: no cover
                err = CameraError("stream_error", str(exc), "")
            self.connected = False
            self.error = err.as_dict()
            fails += 1
            add_log("warn", f"Live stream error ({fails}/5): {err.message}")
            if fails >= 5:
                add_log("error", "Live stream stopped after 5 failed reconnects.")
                for q in list(self.subscribers):
                    q.put_nowait(None)
                break
            await asyncio.sleep(min(1.0 * 2 ** (fails - 1), 8))
        self.connected = False

    async def subscribe(self):
        q: asyncio.Queue = asyncio.Queue(maxsize=2)
        self.subscribers.add(q)
        self._ensure()
        try:
            # wait for the first real frame before sending any bytes
            first = await asyncio.wait_for(q.get(), timeout=12)
            if first is None:
                return
            yield first
            while True:
                frame = await asyncio.wait_for(q.get(), timeout=15)
                if frame is None:
                    return
                yield frame
        except asyncio.TimeoutError:
            return
        finally:
            self.subscribers.discard(q)


def _extract_jpegs(buf: bytearray):
    """Pull complete JPEG frames out of a multipart buffer (in place)."""
    while True:
        start = buf.find(b"\xff\xd8")
        if start < 0:
            if len(buf) > 2:
                del buf[:-2]
            return
        # Prefer the part's Content-Length header (exact), fall back to EOI marker.
        header_zone = bytes(buf[max(0, start - 300):start])
        length = None
        idx = header_zone.lower().rfind(b"content-length:")
        if idx >= 0:
            try:
                length = int(header_zone[idx + 15:].split(b"\r\n", 1)[0].strip())
            except ValueError:
                length = None
        if length:
            if len(buf) < start + length:
                return
            frame = bytes(buf[start:start + length])
            del buf[:start + length]
        else:
            end = buf.find(b"\xff\xd9", start + 2)
            if end < 0:
                return
            frame = bytes(buf[start:end + 2])
            del buf[:end + 2]
        if frame.endswith(b"\xff\xd9"):
            yield frame


bridge = CameraBridge()
