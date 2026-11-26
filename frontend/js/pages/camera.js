import { api, url } from "../api.js";
import { refreshCameraBadge } from "../app.js";
import { $, busy, errorBox, esc, icon, imgUrl, timeAgo, toast } from "../ui.js";

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Connect camera</h1>
    <p>The bridge fetches stills from port 80 (<code>/capture</code>) and video from port 81 (<code>/stream</code>). Your browser only talks to the bridge.</p></div>
    <div class="pill" id="status-pill"><span class="dot"></span><span>Not tested</span></div></div>
    <div class="grid split">
      <div class="stack">
        <div class="card"><div class="card-head"><h2>ESP32-CAM address</h2></div>
          <form class="card-body stack" id="conn">
            <div class="form-grid">
              <label class="field full"><span>Camera IP or hostname</span><input name="camera_ip" required placeholder="192.168.1.65" autocomplete="off" inputmode="decimal">
                <span class="hint">Shown in the Arduino Serial Monitor after “Camera Ready! Use 'http://…' to connect”.</span></label>
              <label class="field"><span>Capture port</span><input name="camera_capture_port" type="number" min="1" max="65535"><span class="hint">/capture — default 80</span></label>
              <label class="field"><span>Stream port</span><input name="camera_stream_port" type="number" min="1" max="65535"><span class="hint">/stream — default 81</span></label>
            </div>
            <div class="row">
              <button class="btn btn-primary" id="connect">${icon("wifi")}Save &amp; connect</button>
              <button type="button" class="btn" id="test">${icon("activity")}Test connection</button>
              <button type="button" class="btn" id="capture">${icon("camera")}Capture image</button>
              <button type="button" class="btn" id="live">${icon("play")}Live stream</button>
            </div>
            <div id="conn-msg"></div>
          </form></div>
        <div class="card"><div class="card-head"><h2>Connection status</h2><span class="tiny muted" id="next"></span></div>
          <div class="card-body"><dl class="kv" id="kv"></dl></div></div>
        <div class="card"><div class="card-head"><h2>Image settings</h2><span class="tiny muted">sent to the camera's /control</span></div>
          <div class="card-body stack">
            <label class="field"><span>Frame size</span><select id="framesize"></select><span class="hint">SVGA (800×600) or larger is recommended for reading printed dates.</span></label>
            <label class="field"><span>Flash LED <span class="muted" id="led-val">off</span></span><input type="range" id="led" min="0" max="255" value="0" step="5">
              <span class="hint">Helps with dark packs; tilt the pack if it causes glare.</span></label>
            <div class="row"><label class="check small"><input type="checkbox" id="vflip">Flip vertically</label><label class="check small"><input type="checkbox" id="hmirror">Mirror</label></div>
          </div></div>
      </div>
      <div class="stack">
        <div class="card"><div class="card-head"><h2>Preview</h2><span class="tiny muted" id="pv-meta"></span></div>
          <div class="card-body"><div class="viewer" id="viewer"><div class="overlay" id="overlay">${icon("camera")}<div>No image yet. Use <b>Test connection</b> or <b>Capture image</b>.</div></div></div></div></div>
        <div class="card"><div class="card-head"><h2>Last captured image</h2><a class="btn btn-ghost btn-sm" id="last-open" target="_blank" rel="noopener" hidden>Open</a></div>
          <div class="card-body" id="last"><div class="muted small">Nothing captured in this session.</div></div></div>
        <div class="card"><div class="card-head"><h2>Camera log</h2><div class="row"><button class="btn btn-ghost btn-sm" id="log-refresh">${icon("refresh")}</button><button class="btn btn-ghost btn-sm" id="log-clear">Clear</button></div></div>
          <div class="card-body"><div class="log" id="log"></div></div></div>
      </div>
    </div>`;

  const f = $("#conn", el), viewer = $("#viewer", el), overlay = $("#overlay", el);
  let streaming = false;

  try {
    const s = (await api.get("/api/settings")).settings;
    f.camera_ip.value = s.camera_ip; f.camera_capture_port.value = s.camera_capture_port; f.camera_stream_port.value = s.camera_stream_port;
  } catch (err) { $("#conn-msg", el).innerHTML = errorBox(err, "Could not load settings"); }

  try {
    const c = await api.get("/api/camera/controls");
    $("#framesize", el).innerHTML = '<option value="">— unchanged —</option>' + Object.entries(c.framesizes).map(([k, v]) => `<option value="${v}">${esc(k)}</option>`).join("");
  } catch { /* ignore */ }

  function paintState(s, health) {
    const pill = $("#status-pill", el);
    const map = { connected: ["ok", "Connected — valid JPEG received"], connecting: ["busy", "Connecting…"],
      disconnected: ["err", "Not connected"], unknown: ["", "Not tested yet"] };
    const [cls, label] = map[s.status] || map.unknown;
    pill.innerHTML = `<span class="dot ${cls}"></span><span>${label}</span>`;
    const err = s.last_error;
    $("#kv", el).innerHTML = `
      <dt>Capture URL</dt><dd class="mono">${esc(s.capture_url)}</dd>
      <dt>Stream URL</dt><dd class="mono">${esc(s.stream_url)}</dd>
      <dt>Last valid image</dt><dd>${esc(timeAgo(s.last_success_at))}${s.resolution ? ` · ${s.resolution[0]}×${s.resolution[1]}` : ""}${s.latency_ms ? ` · ${s.latency_ms} ms` : ""}</dd>
      <dt>Live stream</dt><dd>${s.stream.connected ? `streaming · ${s.stream.fps} fps · ${s.stream.viewers} viewer(s)` : s.stream.error ? esc(s.stream.error.message) : "idle"}</dd>
      <dt>Auto-reconnect</dt><dd>${s.auto_reconnect_paused ? "paused — press Save & connect" : s.status === "disconnected" ? `attempt ${s.reconnect_attempt}/6, next ${esc(timeAgo(s.next_check_at).replace(" ago", "") )}` : "on (real capture every check)"}</dd>
      ${err ? `<dt>Last error</dt><dd style="color:var(--red-600)">${esc(err.message)}${err.hint ? `<div class="small muted" style="margin-top:4px">${esc(err.hint)}</div>` : ""}</dd>` : ""}`;
    if (health && !health.ok && health.error) {
      $("#conn-msg", el).innerHTML = errorBox(health.error, "Camera test failed");
    } else if (health && health.ok) {
      $("#conn-msg", el).innerHTML = `<div class="callout ok">${icon("checkCircle")}<div><b>Camera connected.</b> Received a ${health.check.width}×${health.check.height} JPEG (${Math.round(health.check.bytes / 1024)} KB) in ${health.check.latency_ms} ms.</div></div>`;
    }
  }

  function showLast() {
    const src = imgUrl("/api/camera/last", true);
    $("#last", el).innerHTML = `<img src="${esc(src)}" alt="Last captured image" style="border-radius:10px">`;
    const a = $("#last-open", el); a.hidden = false; a.href = src;
  }

  async function poll() {
    try { paintState(await api.get("/api/camera/state", { retryAuth: false })); } catch { /* backend down: badge shows it */ }
  }
  async function loadLogs() {
    try {
      const { logs } = await api.get("/api/camera/logs?limit=80");
      $("#log", el).innerHTML = logs.length ? logs.map((l) => `<div class="${esc(l.level)}"><span>${esc(new Date(l.at).toLocaleTimeString())}</span><span>${esc(l.level.toUpperCase())}</span><span>${esc(l.message)}</span></div>`).join("")
        : '<div class="muted">No log entries.</div>';
    } catch (err) { $("#log", el).innerHTML = `<div class="error">${esc(err.message)}</div>`; }
  }

  async function health(btn, connect) {
    $("#conn-msg", el).innerHTML = "";
    try {
      const payload = connect ? { camera_ip: f.camera_ip.value.trim(), camera_capture_port: +f.camera_capture_port.value, camera_stream_port: +f.camera_stream_port.value } : null;
      const h = await busy(btn, () => connect ? api.post("/api/camera/connect", payload, { timeout: 90000 }) : api.get("/api/camera/health", { timeout: 90000 }), connect ? "Connecting…" : "Testing…");
      paintState(h, h);
      if (h.ok) showLast();
    } catch (err) { $("#conn-msg", el).innerHTML = errorBox(err, "Request failed"); }
    refreshCameraBadge(); loadLogs();
  }

  f.onsubmit = (e) => { e.preventDefault(); health($("#connect", el), true); };
  $("#test", el).onclick = (e) => health(e.currentTarget, false);
  $("#capture", el).onclick = async (e) => {
    try {
      const res = await busy(e.currentTarget, () => api.get("/api/camera/capture", { raw: true, timeout: 90000 }), "Capturing…");
      const blob = await res.blob();
      stopLive();
      viewer.querySelector("img")?.remove(); overlay.style.display = "none";
      viewer.insertAdjacentHTML("afterbegin", `<img src="${URL.createObjectURL(blob)}" alt="Captured image">`);
      $("#pv-meta", el).textContent = `${res.headers.get("X-Image-Width")}×${res.headers.get("X-Image-Height")} · ${res.headers.get("X-Capture-Ms")} ms${res.headers.get("X-Capture-Source") === "stream_frame" ? " · frame from live stream" : ""}`;
      showLast();
    } catch (err) { $("#conn-msg", el).innerHTML = errorBox(err, "Capture failed"); }
    poll(); refreshCameraBadge(); loadLogs();
  };

  function stopLive() {
    streaming = false;
    viewer.querySelector("img.live")?.remove();
    viewer.querySelector(".tag")?.remove();
    $("#live", el).innerHTML = `${icon("play")}Live stream`;
  }
  $("#live", el).onclick = () => {
    if (streaming) { stopLive(); return; }
    streaming = true;
    viewer.querySelector("img")?.remove();
    overlay.style.display = "grid";
    overlay.innerHTML = '<div class="spinner"></div><div>Opening port 81 stream through the bridge…</div>';
    const img = new Image();
    img.className = "live"; img.alt = "Live stream";
    img.onload = () => { overlay.style.display = "none"; if (!viewer.querySelector(".tag")) viewer.insertAdjacentHTML("beforeend", '<span class="tag live">LIVE · port 81</span>'); $("#pv-meta", el).textContent = "live"; };
    img.onerror = async () => {
      stopLive();
      overlay.style.display = "grid";
      let m = "Live stream unavailable.";
      try { const st = await api.get("/api/camera/stream/status"); if (st.error) m = `${st.error.message} ${st.error.hint || ""}`; } catch { /* ignore */ }
      overlay.innerHTML = `${icon("wifiOff")}<div>${esc(m)}</div>`;
      loadLogs();
    };
    img.src = url(`/api/camera/stream?t=${Date.now()}`);
    viewer.insertAdjacentElement("afterbegin", img);
    $("#live", el).innerHTML = `${icon("stop")}Stop stream`;
  };

  async function control(v, val) {
    try { await api.post("/api/camera/control", { var: v, val: Number(val) }); toast("Camera updated", { text: `${v} = ${val}` }); }
    catch (err) { toast("Camera setting failed", { type: "err", text: `${err.message} ${err.hint || ""}`, timeout: 8000 }); }
    loadLogs();
  }
  $("#framesize", el).onchange = (e) => e.target.value !== "" && control("framesize", e.target.value);
  $("#led", el).oninput = (e) => ($("#led-val", el).textContent = e.target.value === "0" ? "off" : e.target.value);
  $("#led", el).onchange = (e) => control("led_intensity", e.target.value);
  $("#vflip", el).onchange = (e) => control("vflip", e.target.checked ? 1 : 0);
  $("#hmirror", el).onchange = (e) => control("hmirror", e.target.checked ? 1 : 0);
  $("#log-refresh", el).onclick = loadLogs;
  $("#log-clear", el).onclick = async () => { await api.del("/api/camera/logs").catch(() => {}); loadLogs(); };

  await poll();
  try { if ((await api.get("/api/camera/state")).last_image_at) showLast(); } catch { /* ignore */ }
  loadLogs();
  const timer = setInterval(() => { poll(); }, 5000);
  return () => { clearInterval(timer); stopLive(); };
}
