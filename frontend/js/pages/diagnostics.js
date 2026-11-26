import { api, url } from "../api.js";
import { refreshCameraBadge } from "../app.js";
import { $, busy, esc, icon } from "../ui.js";

function row(ic, title, state, detail, extra = "") {
  const label = { ok: "Working", err: "Failed", warn: "Warning", off: "Not configured" }[state];
  const cls = { ok: "ok", err: "err", warn: "warn", off: "" }[state];
  return `<div class="card diag"><div class="ic">${icon(ic)}</div><div><h3>${esc(title)}</h3><div class="small muted" style="margin-top:3px">${detail}</div>${extra}</div>
    <span class="pill"><span class="dot ${cls}"></span>${label}</span></div>`;
}

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Diagnostics</h1><p>Every check below runs for real right now — nothing is cached or assumed.</p></div>
    <button class="btn btn-primary" id="run">${icon("refresh")}Run all checks</button></div><div class="stack" id="out"></div>`;

  async function run(btn) {
    const fe = {
      secure: window.isSecureContext, origin: location.origin, api: url("") || "(same origin)",
      mixed: location.protocol === "https:" && url("").startsWith("http:"),
    };
    const feRow = row("monitor", "Frontend", fe.mixed ? "err" : fe.secure ? "ok" : "warn",
      `Loaded from <code>${esc(fe.origin)}</code> · API: <code>${esc(fe.api)}</code> · ${fe.secure ? "secure context (HTTPS/localhost)" : "NOT a secure context — use HTTPS or localhost for notifications and phone camera upload"}${fe.mixed ? "<br><b>Mixed content: HTTPS page with an HTTP API_BASE will be blocked.</b>" : ""}`);
    $("#out", el).innerHTML = feRow + '<div class="card card-pad row"><div class="spinner"></div>Running backend, database, camera, barcode and OCR checks…</div>';
    let d;
    try {
      d = await busy(btn, () => api.get("/api/diagnostics", { timeout: 120000 }), "Running…");
    } catch (err) {
      $("#out", el).innerHTML = feRow + row("server", "Backend / camera bridge", "err", `${esc(err.message)}<br>${esc(err.hint || "")}`)
        + row("db", "Database", "err", "Unknown — backend unreachable") + row("camera", "Camera", "err", "Unknown — backend unreachable");
      return;
    }
    const cam = d.camera;
    const camDetail = cam.ok
      ? `Real capture from <code>${esc(cam.capture_url)}</code>: ${cam.check.width}×${cam.check.height} JPEG, ${Math.round(cam.check.bytes / 1024)} KB, ${cam.check.latency_ms} ms`
      : `<code>${esc(cam.capture_url)}</code> — ${esc(cam.error?.message || "failed")}<br>${esc(cam.error?.hint || "")}`;
    const ocrD = d.ocr.ok ? `${esc(d.ocr.version)} read the test label correctly (EXP ${esc(d.ocr.got.expiry)}, MFG ${esc(d.ocr.got.mfg)}) in ${d.ocr.elapsed_ms} ms`
      : esc(d.ocr.error || `Read “${d.ocr.read_text || ""}” — expected EXP ${d.ocr.expected?.expiry}`);
    const bcD = d.barcode.ok ? `${esc(d.barcode.library)} encoded and decoded EAN-13 and QR test codes` : esc(JSON.stringify(d.barcode.checks || d.barcode.error));
    const sec = d.security;
    $("#out", el).innerHTML = [
      feRow,
      row("server", "Backend / camera bridge", "ok", `Fresh Vibe ${esc(d.backend.version)} · Python ${esc(d.backend.python)} · up ${Math.round(d.backend.uptime_s / 60)} min`),
      row("db", "Database", d.database.ok ? "ok" : "err", d.database.ok ? `${esc(d.database.engine)} · ${d.database.products} products` : esc(d.database.error)),
      row("camera", "Camera connection (ESP32-CAM)", cam.ok ? "ok" : "err", camDetail, cam.ok ? "" : '<a class="btn btn-sm" style="margin-top:8px" href="#/camera">Fix connection</a>'),
      row("barcode", "Barcode scanner", d.barcode.ok ? "ok" : "err", bcD),
      row("text", "OCR service", d.ocr.ok ? "ok" : "err", ocrD),
      row("globe", "Product database lookup", d.product_lookup.ok ? "ok" : "warn", esc(d.product_lookup.detail || d.product_lookup.error)),
      row("sparkles", "AI recognition (optional)", d.ai.configured ? "ok" : "off", d.ai.configured ? `${esc(d.ai.provider)} · ${esc(d.ai.model)} (key present; called during scans)` : esc(d.ai.reason)),
      row("shield", "Security", sec.warnings.length ? "warn" : "ok",
        `${sec.https ? "HTTPS" : "HTTP"} · token ${sec.auth_required ? "required" : "not required"} · CORS ${sec.cors_origins.length ? esc(sec.cors_origins.join(", ")) : "same-origin only"}${sec.warnings.map((w) => `<br>⚠ ${esc(w)}`).join("")}`),
    ].join("");
    refreshCameraBadge();
  }
  $("#run", el).onclick = (e) => run(e.currentTarget);
  run($("#run", el));
}
