import { api, setToken } from "../api.js";
import { $, busy, errorBox, esc, icon, toast } from "../ui.js";

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Settings</h1><p>Camera, expiry thresholds, recognition and notifications.</p></div></div><div id="body"><div class="skeleton" style="height:200px"></div></div>`;
  let data;
  try { data = await api.get("/api/settings"); } catch (err) { $("#body", el).innerHTML = errorBox(err, "Could not load settings"); return; }
  const s = data.settings;
  const notifState = "Notification" in window ? Notification.permission : "unsupported";
  const notifOn = localStorage.getItem("fv_browser_notify") === "1" && notifState === "granted";

  $("#body", el).innerHTML = `<form id="f" class="grid cols-2">
    <div class="card"><div class="card-head"><h2>Camera (admin)</h2><a class="btn btn-ghost btn-sm" href="#/camera">Open camera page</a></div><div class="card-body form-grid">
      <label class="field full"><span>ESP32-CAM IP / hostname</span><input name="camera_ip" value="${esc(s.camera_ip)}" required></label>
      <label class="field"><span>Capture port (/capture)</span><input name="camera_capture_port" type="number" value="${esc(s.camera_capture_port)}"></label>
      <label class="field"><span>Stream port (/stream)</span><input name="camera_stream_port" type="number" value="${esc(s.camera_stream_port)}"></label>
      <label class="field"><span>Request timeout (s)</span><input name="camera_timeout_s" type="number" min="1" max="60" step="0.5" value="${esc(s.camera_timeout_s)}"></label>
      <label class="field"><span>Retries per capture</span><input name="camera_retries" type="number" min="1" max="10" value="${esc(s.camera_retries)}"></label>
      <label class="field full"><span>Background health check every (s)</span><input name="camera_monitor_interval_s" type="number" min="0" max="3600" value="${esc(s.camera_monitor_interval_s)}">
        <span class="hint">0 = off. Each check is a real /capture. When the camera drops, reconnects back off (5 s → 5 min) and pause after 6 failures.</span></label>
    </div></div>
    <div class="card"><div class="card-head"><h2>Expiry thresholds</h2></div><div class="card-body form-grid">
      <label class="field full"><span>“Fresh” means more than … days left</span><input name="fresh_days" type="number" min="1" max="3650" value="${esc(s.fresh_days)}">
        <span class="hint">Products with 0–N days left are “Expiring soon”.</span></label>
      <label class="field full"><span>Alert windows (days, comma-separated)</span><input name="notify_days" value="${esc(s.notify_days.join(", "))}">
        <span class="hint">Alerts are also created for “tomorrow”, “today” and “expired”. Each alert is created once per product.</span></label>
    </div></div>
    <div class="card"><div class="card-head"><h2>Recognition</h2><span class="tiny muted">OCR: ${esc(data.ocr_engine)}</span></div><div class="card-body form-grid">
      <label class="field full"><span>Auto-save only when confidence ≥ <b id="thr-v">${Math.round(s.auto_save_min_confidence * 100)}%</b></span>
        <input name="auto_save_min_confidence" type="range" min="0.5" max="0.99" step="0.01" value="${esc(s.auto_save_min_confidence)}">
        <span class="hint">Below this, you are asked to confirm the uncertain fields. Higher = safer, more confirmations.</span></label>
      <label class="field"><span>Ambiguous dates like 03/04/2027</span><select name="date_order">
        <option value="DMY" ${s.date_order === "DMY" ? "selected" : ""}>Day first (DD/MM) — India, UK, EU</option>
        <option value="MDY" ${s.date_order === "MDY" ? "selected" : ""}>Month first (MM/DD) — USA</option></select></label>
      <label class="field"><span>AI recognition</span><label class="check" style="min-height:40px"><input type="checkbox" name="ai_enabled" ${s.ai_enabled ? "checked" : ""} ${data.ai.configured ? "" : "disabled"}>
        ${data.ai.configured ? `Use ${esc(data.ai.provider)} (${esc(data.ai.model)})` : `Not configured — ${esc(data.ai.reason)}`}</label></label>
    </div></div>
    <div class="card"><div class="card-head"><h2>Notifications &amp; access</h2></div><div class="card-body stack">
      <div class="row between"><div><b>Browser notifications</b><div class="small muted">Permission: ${esc(notifState)}${window.isSecureContext ? "" : " · needs HTTPS or localhost"}</div></div>
        <button type="button" class="btn" id="notif">${notifOn ? "Turn off" : "Enable"}</button></div>
      ${data.auth_required ? `<div class="row between"><div><b>Access token</b><div class="small muted">This bridge is protected by API_TOKEN.</div></div>
        <button type="button" class="btn" id="logout">${icon("logout")}Sign out</button></div>` : `<div class="callout warn">${icon("shield")}<div class="small">No API_TOKEN is set. That is fine on localhost, but set one before exposing the bridge through a tunnel.</div></div>`}
    </div></div>
    <div style="grid-column:1/-1" class="row"><button class="btn btn-primary btn-lg">${icon("check")}Save settings</button><div id="msg" style="flex:1"></div></div>
  </form>`;

  const f = $("#f", el);
  f.auto_save_min_confidence.oninput = (e) => ($("#thr-v", el).textContent = `${Math.round(e.target.value * 100)}%`);
  f.onsubmit = async (e) => {
    e.preventDefault();
    const payload = {
      camera_ip: f.camera_ip.value.trim(), camera_capture_port: +f.camera_capture_port.value, camera_stream_port: +f.camera_stream_port.value,
      camera_timeout_s: +f.camera_timeout_s.value, camera_retries: +f.camera_retries.value, camera_monitor_interval_s: +f.camera_monitor_interval_s.value,
      fresh_days: +f.fresh_days.value, notify_days: f.notify_days.value.split(/[,\s]+/).filter(Boolean).map(Number),
      auto_save_min_confidence: +f.auto_save_min_confidence.value, date_order: f.date_order.value,
    };
    if (!f.ai_enabled.disabled) payload.ai_enabled = f.ai_enabled.checked;
    try {
      await busy(f.querySelector(".btn-primary"), () => api.put("/api/settings", payload), "Saving…");
      $("#msg", el).innerHTML = "";
      toast("Settings saved");
    } catch (err) { $("#msg", el).innerHTML = errorBox(err, "Not saved"); }
  };
  $("#notif", el).onclick = async () => {
    if (!("Notification" in window)) { toast("Not supported in this browser", { type: "err" }); return; }
    if (localStorage.getItem("fv_browser_notify") === "1") { localStorage.removeItem("fv_browser_notify"); toast("Browser notifications off"); render(el); return; }
    const p = await Notification.requestPermission();
    if (p === "granted") { localStorage.setItem("fv_browser_notify", "1"); new Notification("Fresh Vibe", { body: "Expiry alerts will appear here." }); toast("Browser notifications on"); }
    else toast("Permission not granted", { type: "warn", text: "Allow notifications for this site in the browser settings." });
    render(el);
  };
  $("#logout", el)?.addEventListener("click", async () => { await api.post("/api/auth/logout").catch(() => {}); setToken(null); location.reload(); });
}
