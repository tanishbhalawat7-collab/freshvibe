# Fresh Vibe – AI Smart Expiry Tracker

Fresh Vibe uses an AI Thinker ESP32-CAM to photograph groceries, medicines and household products. It decodes the barcode, looks the product up, reads the printed packaging text with OCR, and works out which date is the **expiry** date and which is the **manufacturing** date. Then it saves the product or asks you to confirm any field it is unsure about.

```
 Browser (HTTPS or localhost)            Bridge computer on your Wi-Fi             ESP32-CAM
 ┌────────────────────────┐   HTTPS   ┌──────────────────────────────────┐  HTTP  ┌───────────────┐
 │ Fresh Vibe web app     │ ────────▶ │ FastAPI backend + camera bridge  │ ─────▶ │ :80 /capture  │
 │ (served by the bridge) │ ◀──────── │ barcode · OCR · AI · SQLite/PG   │ ◀───── │ :81 /stream   │
 └────────────────────────┘  /api/*   └──────────────────────────────────┘  LAN   └───────────────┘
```

* The browser **never** contacts `192.168.1.65` directly, so there are no mixed-content, CORS or private-network errors. The backend fetches `/capture` on port 80 and `/stream` on port 81 and re-serves them as `/api/camera/capture` and `/api/camera/stream`.
* The camera only counts as **connected** after a real `/capture` returns a decodable JPEG. `/status` is never used.
* The frontend is served from the same origin as the API, so one HTTPS tunnel covers everything.

---

## 1. Requirements

| What | Version |
|---|---|
| Python | 3.10 – 3.13 |
| Tesseract OCR | 5.x |
| AI Thinker ESP32-CAM | running the Arduino **CameraWebServer** example |
| A computer on the same Wi-Fi as the camera | Windows / macOS / Linux / Raspberry Pi 4 |

### Install Tesseract
* **Windows:** install from <https://github.com/UB-Mannheim/tesseract/wiki>. Then either tick *Add to PATH* or set `TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe` in `.env`.
* **macOS:** `brew install tesseract`
* **Ubuntu / Raspberry Pi OS:** `sudo apt install tesseract-ocr`

No Node.js or build step is needed. The frontend is plain HTML/CSS/JS modules.

---

## 2. Quick start (local)

**Windows (PowerShell):**
```powershell
cd fresh-vibe
py -3 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
cd backend
..\.venv\Scripts\python -m app
```

**macOS / Linux:**
```bash
cd fresh-vibe
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
cd backend && ../.venv/bin/python -m app
```

Alternatively, run `scripts\run.bat` or `./scripts/run.sh`, which do all of the above.

Open **http://localhost:8000**. Browsers treat `localhost` as a secure context, so notifications and every other feature work there without certificates.

Then:
1. Go to **Connect Camera**, enter the IP from the Serial Monitor (`192.168.1.65`), and press **Save & connect**. The status turns green only when a JPEG has actually been received.
2. Set **Frame size** to SVGA (800×600) or XGA. QVGA is too small to read printed dates.
3. Open **Diagnostics** and press **Run all checks**.
4. Go to **Scan Product** and press **Scan with ESP32-CAM**.

---

## 3. ESP32-CAM setup (Arduino IDE)

1. Install *esp32 by Espressif Systems* in Boards Manager.
2. Open **File → Examples → ESP32 → Camera → CameraWebServer**.
3. In `CameraWebServer.ino`, keep only `#define CAMERA_MODEL_AI_THINKER` and set your `ssid` and `password`.
4. Set Board = **AI Thinker ESP32-CAM**, Partition = **Huge APP**, PSRAM = **Enabled**. Flash it, then press RESET.
5. The Serial Monitor (115200 baud) prints `Camera Ready! Use 'http://192.168.1.65' to connect`.

Tips:
* Give the camera a **DHCP reservation** in your router so its IP doesn't change. If it does change, update it on the Connect Camera page; nothing is hard-coded.
* Use a solid **5 V / 2 A** supply. Brown-outs cause truncated JPEGs and dropped streams, which the logs report as *protocol* errors.
* The OV2640 lens is fixed-focus at about 40 cm+. For small print, carefully **twist the lens** a little to focus at 10–20 cm. This is the most effective single improvement for OCR accuracy.
* The brightness, flip and flash-LED controls use the firmware's `/control` endpoint. If your build does not have it, those controls report "unsupported" and everything else still works.

See `firmware/README.md` for details.

---

## 4. How a scan works

| Step | What happens | Where |
|---|---|---|
| 1. Capture | Bridge fetches `/capture`, checks the JPEG, and stores it | `camera.py`, `pipeline.store_image` |
| 2. Barcode | zxing-cpp tries original, upscaled, contrast and binarised images; checks EAN/UPC checksums | `barcode.py` |
| 3. Identity | Your own confirmed products → Open Food/Beauty/Products/Pet Food Facts → UPCitemdb | `lookup.py` |
| 4. OCR | Tesseract runs two passes (enhanced/sparse and adaptive-binary/block), plus 90°/270° passes if no labelled date was found | `ocr.py` |
| 5. Dates | Finds every date, attaches the nearest label (EXP / BEST BEFORE / USE BY / MFG / MFD / PKD…), normalises to `YYYY-MM-DD` or `YYYY-MM`, and validates the calendar date | `dates.py` |
| 6. AI (optional) | A vision model reads the name, brand, category and dates. Its output is treated as unverified evidence | `ai_vision.py` |
| 7. Validate | Merges evidence per field, assigns confidences and cross-checks (for example, expiry must be after MFG) | `pipeline.fuse/decide` |
| 8–10. Decide | Saves automatically only if the **name and expiry** are both above the threshold (default 75%). Otherwise it asks you to confirm the highlighted fields or capture another image | `pipeline.process` |

Date rules:
* A date with no label is **never** treated as the expiry date. The app asks you which one it is.
* `MFD`, `PKD` and similar labels never become expiry dates.
* `EXP 05/2027` keeps **month precision**. It is stored as `2027-05` and counts as good until 31 May 2027. No day is invented.
* For ambiguous dates like `03/04/2027`, the order setting decides (DD/MM by default, for India). The field is flagged and loses some confidence.
* Invalid dates like `30/02/2027` are rejected, and the app asks for another image.
* `Best before 18 months from manufacture` + `MFD 05/2026` → derived expiry `2027-10`. This only happens when the manufacturing date was actually read.
* Each date's original OCR text is kept and shown under **Evidence**.
* Barcodes never supply dates.

**Two-sided products** (barcode on the back, date on the lid): after a scan, press **Capture another side**, or use **Barcode Scanner → Now scan the expiry date**. The two captures are merged field by field.

**Duplicates:** the same barcode (or name+brand), batch and expiry date increases the existing item's quantity instead of adding a row. A toast offers **Undo**.

---

## 5. AI recognition (optional)

Add one provider to `.env`:
```
AI_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```
or
```
AI_PROVIDER=openai
OPENAI_API_KEY=sk-...
```
Without a key, the AI step shows **Not configured**. It is never simulated. AI-only product names are capped at 70% confidence, and AI-only dates at 45%, so they always need your confirmation unless OCR read the same text.

## 6. Better OCR for dot-matrix / inkjet dates

Tesseract handles clean print well. Laser-etched or dot-matrix date codes are harder. For those:
```bash
pip install -r requirements-ocr-extra.txt   # EasyOCR, about a 1 GB download with PyTorch
# .env
OCR_ENGINE=easyocr
```

---

## 7. Secure deployment

### A. Same computer (simplest)
`HOST=127.0.0.1` and open `http://localhost:8000`. Nothing else is reachable from outside.

### B. Phones on the same Wi-Fi (HTTPS on the LAN)
```bash
./scripts/make_cert.sh 192.168.1.20        # your bridge PC's IP (or use mkcert for a trusted cert)
```
Set in `.env`:
```
HOST=0.0.0.0
SSL_CERTFILE=../certs/cert.pem
SSL_KEYFILE=../certs/key.pem
API_TOKEN=<python -c "import secrets;print(secrets.token_urlsafe(32))">
```
Then open `https://192.168.1.20:8000` on the phone. Accept the certificate once, or install the mkcert root CA, and sign in with the token.

### C. From anywhere (HTTPS tunnel; the camera stays private)
Keep `HOST=127.0.0.1`, **set `API_TOKEN`**, and run one of these:

* **Cloudflare Tunnel:** `cloudflared tunnel --url http://localhost:8000`. This prints an `https://…trycloudflare.com` URL. For a permanent hostname, create a named tunnel in the Cloudflare dashboard.
* **Tailscale:** `tailscale serve --bg 8000` (private to your tailnet). Use `tailscale funnel 8000` for public access.

The tunnel only exposes the bridge (port 8000). The ESP32-CAM is never exposed. A cloud server can't reach `192.168.1.65`, which is why the bridge runs on your LAN.

### D. Frontend hosted elsewhere (Vercel / Netlify), optional
1. Deploy the `frontend/` folder as a static site.
2. In `frontend/config.js`, set `API_BASE: "https://your-tunnel-hostname"`.
3. In the bridge `.env`: `CORS_ORIGINS=https://your-site.vercel.app` (exact origin; `*` is refused).

Login uses an HttpOnly session cookie (`SameSite=None; Secure` in this mode) plus a bearer token. Option C is simpler and more robust, because some browsers block third-party cookies, which affects image and stream loading in mode D.

### PostgreSQL (production)
```bash
pip install "psycopg[binary]"
# .env
DATABASE_URL=postgresql://freshvibe:password@localhost:5432/freshvibe
```
Tables are created automatically on start.

### Run as a service (Linux / Raspberry Pi)
`/etc/systemd/system/freshvibe.service`:
```ini
[Unit]
Description=Fresh Vibe bridge
After=network-online.target
[Service]
WorkingDirectory=/home/pi/fresh-vibe/backend
ExecStart=/home/pi/fresh-vibe/.venv/bin/python -m app
Restart=always
User=pi
[Install]
WantedBy=multi-user.target
```
Then: `sudo systemctl enable --now freshvibe`

---

## 8. Testing

### Automated (no hardware needed)
```bash
pip install -r requirements-dev.txt
python tests/make_fixtures.py        # renders test packaging images (also done automatically)
python -m pytest -q tests            # 35 tests
```
* `test_dates.py`: label/date logic (MFG vs EXP, month precision, invalid dates, unlabelled dates, shelf life, OCR confusions).
* `test_vision.py`: real zxing-cpp decoding of all 7 formats, and real Tesseract OCR on rendered packs (including rotated and blank images).
* `test_api.py`: end-to-end API tests against `tests/esp32_emulator.py`, a **test-only** stand-in that speaks the CameraWebServer protocol (`/capture` on one port, MJPEG `/stream` on another, `/status` → 404). It covers health, a dead-camera case, the stream relay, confirmation → auto-save → duplicate, two-sided merge, CRUD, notifications without duplicates, diagnostics, and token auth with CSRF protection.

UI smoke test (needs Chrome): `python -m playwright install chromium`, then run `python tests/ui_smoke.py http://localhost:8000 screenshots` with the backend running.

### With your real ESP32-CAM: checklist
| # | Check | How |
|---|---|---|
| 1 | Frontend loads | Open `http://localhost:8000` |
| 2 | Backend starts | Console shows `Fresh Vibe ready. Camera: http://192.168.1.65/capture` |
| 3 | Database initialises | Diagnostics → Database: Working |
| 4 | IP configurable | Connect Camera → change IP → Save & connect |
| 5 | Capture returns a JPEG | Connect Camera → Test connection → "Received a W×H JPEG" |
| 6 | Live stream works independently | Connect Camera → Live stream (port 81) while Capture still works |
| 7 | Secure frontend ↔ backend | Diagnostics → Frontend: secure context; Security: HTTPS (modes B/C) |
| 8 | CORS | Same-origin: nothing needed. Mode D: Diagnostics lists your origin |
| 9 | Real barcodes decode | Barcode Scanner on any packaged product |
| 10 | OCR reads packaging | Scan Product → Evidence → OCR text |
| 11 | MFG vs EXP distinguished | Evidence table → Type column |
| 12 | Saved correctly | Product Inventory |
| 13 | Duplicates handled | Scan the same item twice → quantity 2 + Undo |
| 14 | Notifications | Add an item expiring tomorrow → bell + optional browser alert |
| 15 | Network failures | Unplug the camera → Test connection shows a specific error and hint; status turns red |

---

## 9. API

All errors are JSON: `{"error": {"code", "message", "hint"}}` with a matching HTTP status. Interactive docs are at **/docs**.

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET | `/api/diagnostics` | Real checks: DB, camera capture, barcode and OCR self-tests, lookup, AI, security |
| GET | `/api/camera/health` | Real `/capture`; `ok` only with a valid JPEG |
| GET | `/api/camera/state` | Last known state (no camera request) |
| POST | `/api/camera/connect` | `{camera_ip, camera_capture_port, camera_stream_port}` → save, reset backoff, health check |
| GET | `/api/camera/capture` | JPEG from port 80 |
| GET | `/api/camera/stream` | MJPEG relayed from port 81 (one upstream connection, many viewers) |
| GET | `/api/camera/stream/status`, `/api/camera/logs`, `/api/camera/last` | Stream info, error log, last image |
| POST | `/api/camera/control` | `{var, val}`: framesize, quality, led_intensity, vflip… |
| POST | `/api/scan/image` | Capture (or upload `image`) and store |
| POST | `/api/scan/barcode` | Decode + lookup (`image` upload, `scan_id`, or `source=camera`) |
| POST | `/api/scan/ocr` | OCR + date extraction |
| POST | `/api/scan/process` | Full workflow; `merge_with`, `use_ai`, `auto_save` |
| GET/POST | `/api/products` | List (`q, category, status, verification, sort`) / create (`scan_id` to confirm a scan) |
| GET/PUT/DELETE | `/api/products/{id}` | Read / edit / delete |
| GET | `/api/expiry/summary` | Dashboard counts, categories, months |
| GET | `/api/notifications` | Expiry alerts (30/7 days, tomorrow, today, expired); `POST …/{id}/read`, `…/read-all` |
| GET/PUT | `/api/settings` | Camera IP/ports, thresholds, confidence, date order, AI toggle |

---

## 10. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `No answer from 192.168.1.65 within 8s` | Camera off, wrong IP, or the bridge PC is on a different network (guest Wi-Fi, mobile hotspot, VPN). Ping the IP from the bridge PC. |
| `refused the connection` | Wrong port: capture is **80**, stream is **81**. |
| `Response is not a JPEG` | The IP belongs to another device, such as your router. |
| Live stream fails but capture works | Another browser tab or app is viewing `:81/stream` directly. The firmware allows only one stream client, so close it; the bridge shares one stream with all app viewers. |
| Dates not found | Increase the frame size, focus the lens, turn on the flash LED, tilt the pack to avoid glare, fill the frame with the date line, or try `OCR_ENGINE=easyocr`. |
| Product name unknown | The barcode isn't in the open databases. Enter it once; future scans of that barcode are recognised from your inventory automatically. |
| `Tesseract is not installed` | Install it (see section 1) or set `TESSERACT_CMD`. |

## Project layout
```
backend/app/       main.py (app, errors, static), camera.py (bridge + MJPEG relay + auto-reconnect),
                   barcode.py, ocr.py, dates.py, lookup.py, ai_vision.py, pipeline.py, products.py,
                   expiry.py (status + notifications), security.py, settings_store.py, models.py, routes/
frontend/          index.html, config.js, css/app.css, js/ (app, api, ui, productForm, pages/*)
tests/             pytest suites, fixture generator, ESP32 emulator (tests only), UI smoke test
scripts/           run.sh, run.bat, make_cert.sh
firmware/          ESP32-CAM notes
```
