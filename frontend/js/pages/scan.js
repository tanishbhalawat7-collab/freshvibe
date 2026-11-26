import { api, url } from "../api.js";
import { refreshCameraBadge, refreshNotifications } from "../app.js";
import { focusFirstUncertain, productFormHtml, readProductForm, wireProductForm } from "../productForm.js";
import { $, busy, conf, errorBox, esc, fmtDate, icon, imgUrl, productCard, toast } from "../ui.js";

const MERGE_KEY = "fv_merge_scan";
const FIELD_LABEL = { name: "Product name", brand: "Brand", category: "Category", barcode: "Barcode",
  expiry_date: "Expiry date", mfg_date: "Manufacturing date", batch_no: "Batch no." };

function step(state, title, detail) {
  const ic = { ok: "check", warn: "alert", err: "x", skip: "x" }[state];
  return `<div class="step ${state}"><span class="ic">${icon(ic)}</span><div><div class="t">${esc(title)}</div><div class="d">${detail}</div></div></div>`;
}

function stepsFor(r) {
  const out = [];
  const q = r.quality || {};
  out.push(step(q.issues?.length ? "warn" : "ok", "Image captured",
    `${esc(q.width)}×${esc(q.height)} px · sharpness ${esc(q.sharpness)}${q.issues?.length ? `<br>${q.issues.map(esc).join("<br>")}` : ""}`));
  const codes = r.barcode?.codes || [];
  out.push(step(codes.length ? "ok" : "warn", "Barcode",
    codes.length ? codes.map((c) => `<b>${esc(c.text)}</b> (${esc(c.format)})`).join(", ") : "No barcode visible in this image."));
  if (r.lookup) {
    out.push(step(r.lookup.found ? "ok" : (r.lookup.errors?.length ? "err" : "warn"), "Product database",
      r.lookup.found ? `Found in <b>${esc(r.lookup.source)}</b>${r.lookup.cached ? " (cached)" : ""}`
        : r.lookup.errors?.length ? `Lookup failed: ${esc(r.lookup.errors.slice(0, 2).join("; "))}` : "Barcode not listed in any product database."));
  } else out.push(step("skip", "Product database", "Skipped — no retail barcode."));
  const o = r.ocr || {};
  out.push(step(o.error ? "err" : (o.text ? "ok" : "warn"), "OCR text recognition",
    o.error ? esc(o.error) : `${esc(o.engine)} read ${(o.text || "").length} characters · mean confidence ${Math.round((o.mean_confidence || 0) * 100)}% · ${esc(o.elapsed_ms)} ms`));
  const d = r.dates || {};
  const dd = [];
  if (d.expiry) dd.push(`Expiry <b>${esc(d.expiry.value)}</b> from “${esc(d.expiry.raw)}”${d.expiry.label ? ` (label ${esc(d.expiry.label)})` : ""}`);
  if (d.mfg) dd.push(`Mfg <b>${esc(d.mfg.value)}</b> (label ${esc(d.mfg.label)})`);
  if (d.packed) dd.push(`Packed <b>${esc(d.packed.value)}</b>`);
  const unl = (d.all_dates || []).filter((x) => x.kind === "unlabeled");
  if (unl.length) dd.push(`${unl.length} unlabelled date(s): ${unl.map((x) => esc(x.value)).join(", ")}`);
  out.push(step(d.expiry ? "ok" : "warn", "Date extraction", dd.join("<br>") || "No dates found in the text."));
  const ai = r.ai || {};
  out.push(step(ai.used ? "ok" : ai.error ? "err" : "skip", "AI product recognition",
    ai.used ? `${esc(ai.provider)}: ${esc(ai.product_name || "no name")}${ai.image_problems ? ` · ${esc(ai.image_problems)}` : ""}` : esc(ai.error || ai.reason || "not used")));
  const st = r.decision.status;
  out.push(step(st === "saved" ? "ok" : st === "retake" ? "err" : "warn", "Validation",
    st === "saved" ? "All key fields above the confidence threshold — saved automatically."
      : st === "retake" ? "Not enough readable information." : `Needs your confirmation (threshold ${Math.round(r.threshold * 100)}%).`));
  return out.join("");
}

function evidence(r) {
  const dates = r.dates?.all_dates || [];
  return `<details style="margin-top:14px"><summary>Evidence (raw OCR text, all dates, AI output)</summary>
    <div class="stack">
      <div><div class="small muted" style="margin-bottom:6px">OCR text (original, unmodified)</div><pre class="ocr">${esc(r.ocr?.text || "(no text)")}</pre></div>
      ${dates.length ? `<div class="table-wrap"><table><thead><tr><th>As read</th><th>Normalised</th><th>Label</th><th>Type</th><th>Confidence</th></tr></thead><tbody>
        ${dates.map((x) => `<tr><td class="mono">${esc(x.raw)}</td><td>${esc(x.value)}${x.precision === "month" ? ' <span class="tiny muted">(month)</span>' : ""}</td>
          <td>${esc(x.label || "—")}</td><td>${esc(x.kind)}${x.derived ? " (derived)" : ""}${x.ambiguous ? ' <span class="badge b-expiring_soon plain">ambiguous</span>' : ""}</td><td>${conf(x.confidence, r.threshold)}</td></tr>`).join("")}
      </tbody></table></div>` : ""}
      ${r.ai?.used ? `<div><div class="small muted" style="margin-bottom:6px">AI response (unverified)</div><pre class="ocr">${esc(JSON.stringify(r.ai, null, 2))}</pre></div>` : ""}
    </div></details>`;
}

export async function render(el, params) {
  let settings = {};
  try { settings = await api.get("/api/settings"); } catch { /* shown below on action */ }
  const aiOk = settings.ai?.configured;
  let streaming = false;
  let lastResult = null;

  el.innerHTML = `<div class="page-head"><div><h1>Scan product</h1><p>Hold the product 10–20 cm in front of the ESP32-CAM with the barcode or the EXP/MFG print facing the lens.</p></div></div>
  <div id="merge-banner"></div>
  <div class="grid split">
    <div class="card"><div class="card-head"><h2>Camera</h2><span class="tiny muted" id="cam-hint"></span></div>
      <div class="card-body stack">
        <div class="viewer" id="viewer"><div class="frame"></div><div class="overlay" id="overlay">${icon("camera")}<div>Press <b>Scan with ESP32-CAM</b> to capture,<br>or start the live view to aim.</div></div></div>
        <div class="row">
          <button class="btn btn-primary btn-lg" id="scan-cam">${icon("scan")}Scan with ESP32-CAM</button>
          <button class="btn" id="live">${icon("play")}Live view</button>
          <label class="btn" for="file">${icon("upload")}Upload photo</label>
          <input type="file" id="file" accept="image/*" capture="environment" class="sr-only">
        </div>
        <label class="check small"><input type="checkbox" id="use-ai" ${aiOk ? "checked" : "disabled"}> Use AI recognition
          <span class="muted">${aiOk ? `(${esc(settings.ai.provider)})` : "— not configured (set AI_PROVIDER + API key in .env)"}</span></label>
      </div></div>
    <div class="card"><div class="card-head"><h2>Result</h2><span id="res-meta" class="tiny muted"></span></div>
      <div class="card-body" id="result"><div class="empty">${icon("scan")}<div>Scan results appear here: barcode, product, dates and confidence for each field.</div></div></div></div>
  </div>`;

  const viewer = $("#viewer", el), overlay = $("#overlay", el), result = $("#result", el);

  function mergeId() { return sessionStorage.getItem(MERGE_KEY); }
  function renderMerge() {
    const id = mergeId();
    $("#merge-banner", el).innerHTML = id ? `<div class="callout info" style="margin-bottom:18px">${icon("layers")}<div class="row between"><div>
      <b>Combining with scan #${esc(id)}.</b> Capture the other side (e.g. the EXP print) — the best reading of each field will be kept.</div>
      <button class="btn btn-sm" id="merge-cancel">Cancel combining</button></div></div>` : "";
    $("#merge-cancel", el)?.addEventListener("click", () => { sessionStorage.removeItem(MERGE_KEY); renderMerge(); });
  }
  renderMerge();

  function showImage(src) {
    viewer.querySelector("img")?.remove();
    overlay.style.display = "none";
    viewer.insertAdjacentHTML("afterbegin", `<img src="${esc(src)}" alt="Captured product image">`);
  }

  function stopLive() {
    streaming = false;
    viewer.querySelector("img.live")?.remove();
    viewer.querySelector(".tag")?.remove();
    $("#live", el).innerHTML = `${icon("play")}Live view`;
  }
  $("#live", el).onclick = () => {
    if (streaming) { stopLive(); return; }
    streaming = true;
    viewer.querySelector("img")?.remove();
    overlay.style.display = "grid";
    overlay.innerHTML = '<div class="spinner"></div><div>Connecting to live stream (port 81) via the bridge…</div>';
    const img = new Image();
    img.className = "live";
    img.alt = "Live camera stream";
    img.onload = () => { overlay.style.display = "none"; if (!viewer.querySelector(".tag")) viewer.insertAdjacentHTML("beforeend", '<span class="tag live">LIVE</span>'); };
    img.onerror = async () => {
      stopLive();
      let msg = "The live stream is not available.";
      try { const st = await api.get("/api/camera/stream/status"); if (st.error) msg = `${st.error.message} ${st.error.hint || ""}`; } catch { /* ignore */ }
      overlay.style.display = "grid";
      overlay.innerHTML = `${icon("wifiOff")}<div>${esc(msg)}</div><a class="btn btn-sm" href="#/camera">Camera settings</a>`;
    };
    img.src = url(`/api/camera/stream?t=${Date.now()}`);
    viewer.insertAdjacentElement("afterbegin", img);
    $("#live", el).innerHTML = `${icon("stop")}Stop live`;
  };

  async function process(form, btn) {
    const merge = mergeId();
    if (merge) form.append("merge_with", merge);
    form.append("use_ai", $("#use-ai", el).checked ? "true" : "false");
    result.innerHTML = `<div class="stack"><div class="row"><div class="spinner"></div><b>Analysing image…</b></div>
      <div class="muted small">Decoding barcode, looking up the product, reading packaging text${$("#use-ai", el).checked ? " and asking the AI model" : ""}. This usually takes 2–10 seconds.</div></div>`;
    $("#res-meta", el).textContent = "";
    try {
      const r = await busy(btn, () => api.postForm("/api/scan/process", form, { timeout: 120000 }), "Scanning…");
      lastResult = r;
      if (merge) sessionStorage.removeItem(MERGE_KEY);
      renderMerge();
      if (!viewer.querySelector("img.live")) showImage(imgUrl(r.image_url));
      showResult(r);
      refreshCameraBadge();
    } catch (err) {
      result.innerHTML = errorBox(err, err.code?.startsWith("camera_") ? "Camera capture failed" : "Scan failed")
        + (err.code?.startsWith("camera_") ? '<div class="row" style="margin-top:12px"><a class="btn" href="#/camera">Open camera connection</a><label class="btn" for="file">Upload a photo instead</label></div>' : "");
      refreshCameraBadge();
    }
  }

  $("#scan-cam", el).onclick = (e) => { const f = new FormData(); f.append("source", "camera"); process(f, e.currentTarget); };
  $("#file", el).onchange = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const f = new FormData(); f.append("image", file);
    showImage(URL.createObjectURL(file));
    process(f, $("#scan-cam", el));
    e.target.value = "";
  };

  function showResult(r) {
    const st = r.decision.status;
    $("#res-meta", el).textContent = `scan #${r.scan_id} · ${r.elapsed_ms} ms`;
    let head = "";
    if (st === "saved") {
      const p = r.saved.product;
      head = `<div class="callout ok">${icon("checkCircle")}<div><b>${r.saved.duplicate ? `Already in inventory — quantity is now ${p.quantity}.` : "Product saved automatically."}</b>
        <div class="small">Identity: ${esc(r.fields.name.source)} · Expiry: ${esc(r.fields.expiry_date.source)} (${Math.round(r.fields.expiry_date.confidence * 100)}%)</div></div></div>
        <div class="card" style="margin-top:12px">${productCard(p)}</div>
        <div class="row" style="margin-top:12px"><button class="btn btn-primary" id="next">${icon("scan")}Scan next</button>
        <button class="btn" id="undo">${r.saved.duplicate ? "Undo quantity +1" : "Undo save"}</button><a class="btn btn-ghost" href="#/inventory?id=${p.id}">${icon("edit")}Edit</a></div>`;
      toast(r.saved.duplicate ? "Duplicate detected" : "Product saved", { text: `${p.name || p.barcode} · expires ${p.expiry_label}` });
      refreshNotifications();
    } else if (st === "retake") {
      head = `<div class="callout err">${icon("camera")}<div><b>Please capture another image.</b><ul>${[...r.decision.reasons, ...r.decision.tips].map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div>
        <div class="row" style="margin-top:12px"><button class="btn btn-primary" id="again">${icon("refresh")}Capture again</button></div>`;
    } else {
      const f = r.fields;
      const values = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.value]));
      values.mfg_precision = f.mfg_date.precision; values.expiry_precision = f.expiry_date.precision;
      const confidence = Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.confidence]));
      head = `<div class="callout warn">${icon("alert")}<div><b>Please confirm ${r.decision.uncertain_fields.length ? r.decision.uncertain_fields.map((k) => FIELD_LABEL[k] || k).join(", ") : "the details"}.</b>
        <ul>${r.decision.reasons.map((x) => `<li>${esc(x)}</li>`).join("")}${r.decision.tips.map((x) => `<li>${esc(x)}</li>`).join("")}</ul></div></div>
        <form id="confirm" style="margin-top:14px">${productFormHtml(values, { uncertain: r.decision.uncertain_fields, confidence, threshold: r.threshold })}
          ${f.expiry_date.value ? `<p class="tiny muted" style="margin-top:8px">Expiry read as “${esc(f.expiry_date.raw)}” → ${esc(fmtDate(f.expiry_date.value, f.expiry_date.precision))} (${esc(f.expiry_date.source)})</p>` : ""}
          <div id="form-err" style="margin-top:10px"></div>
          <div class="row" style="margin-top:14px"><button class="btn btn-primary">${icon("check")}Save confirmed product</button>
          <button type="button" class="btn" id="other-side">${icon("layers")}Capture another side</button>
          <button type="button" class="btn btn-ghost" id="discard">Discard</button></div></form>`;
    }
    result.innerHTML = head + `<div class="steps" style="margin-top:16px">${stepsFor(r)}</div>` + evidence(r);

    $("#next", result)?.addEventListener("click", () => $("#scan-cam", el).click());
    $("#again", result)?.addEventListener("click", () => $("#scan-cam", el).click());
    $("#undo", result)?.addEventListener("click", async () => {
      const p = r.saved.product;
      try {
        if (r.saved.duplicate) await api.put(`/api/products/${p.id}`, { quantity: Math.max(1, p.quantity - 1) });
        else await api.del(`/api/products/${p.id}`);
        toast("Undone"); result.innerHTML = '<div class="empty">Ready for the next scan.</div>';
      } catch (err) { toast("Undo failed", { type: "err", text: err.message }); }
    });
    const form = $("#confirm", result);
    if (form) {
      wireProductForm(form);
      focusFirstUncertain(form);
      form.onsubmit = async (e) => {
        e.preventDefault();
        let data;
        try { data = readProductForm(form); } catch (err) { $("#form-err", form).innerHTML = errorBox(err, "Check the form"); return; }
        try {
          const res = await busy(form.querySelector("button.btn-primary"), () => api.post("/api/products", { ...data, scan_id: r.scan_id }), "Saving…");
          toast(res.duplicate ? "Duplicate — quantity increased" : "Product saved", { text: `${res.product.name || res.product.barcode} · expires ${res.product.expiry_label}` });
          result.innerHTML = `<div class="callout ok">${icon("checkCircle")}<div><b>Saved as verified.</b></div></div><div class="card" style="margin-top:12px">${productCard(res.product)}</div>
            <div class="row" style="margin-top:12px"><button class="btn btn-primary" id="next2">${icon("scan")}Scan next</button></div>`;
          $("#next2", result).onclick = () => $("#scan-cam", el).click();
          refreshNotifications();
        } catch (err) { $("#form-err", form).innerHTML = errorBox(err, "Could not save"); }
      };
      $("#other-side", form).onclick = () => {
        sessionStorage.setItem(MERGE_KEY, String(r.scan_id));
        renderMerge();
        toast("Turn the product", { type: "warn", text: "Now capture the side with the barcode or the EXP/MFG print." });
        $("#scan-cam", el).focus();
      };
      $("#discard", form).onclick = () => { result.innerHTML = '<div class="empty">Scan discarded. Nothing was saved.</div>'; };
    }
  }

  if (params.get("merge")) { sessionStorage.setItem(MERGE_KEY, params.get("merge")); renderMerge(); }
  return () => stopLive();
}
