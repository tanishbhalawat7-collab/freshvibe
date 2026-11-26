import { api } from "../api.js";
import { refreshCameraBadge } from "../app.js";
import { $, busy, errorBox, esc, icon, imgUrl } from "../ui.js";

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Barcode scanner</h1>
    <p>Decodes EAN-13, EAN-8, UPC-A, UPC-E, Code 128, Code 39 and QR codes (plus Data Matrix) with zxing-cpp, then looks the product up.</p></div></div>
    <div class="grid split">
      <div class="card"><div class="card-body stack">
        <div class="viewer" id="viewer"><div class="frame"></div><div class="overlay" id="overlay">${icon("barcode")}<div>Point the barcode at the ESP32-CAM, about 10–15 cm away, and capture.</div></div></div>
        <div class="row"><button class="btn btn-primary btn-lg" id="cap">${icon("barcode")}Capture &amp; decode</button>
          <label class="btn" for="file">${icon("upload")}Upload photo</label><input type="file" id="file" accept="image/*" capture="environment" class="sr-only"></div>
        <p class="tiny muted">Barcodes identify the product only. They do not contain expiry dates — those are read from the printed text with OCR on the Scan page.</p>
      </div></div>
      <div class="card"><div class="card-head"><h2>Decoded</h2></div><div class="card-body" id="out">
        <div class="empty">${icon("barcode")}<div>No barcode decoded yet.</div></div></div></div>
    </div>`;

  const out = $("#out", el);

  async function run(form, btn) {
    out.innerHTML = '<div class="row"><div class="spinner"></div><b>Decoding…</b></div>';
    try {
      const r = await busy(btn, () => api.postForm("/api/scan/barcode", form, { timeout: 60000 }), "Decoding…");
      $("#overlay", el).style.display = "none";
      $("#viewer", el).querySelector("img")?.remove();
      $("#viewer", el).insertAdjacentHTML("afterbegin", `<img src="${esc(imgUrl(r.image_url))}" alt="Captured image">`);
      refreshCameraBadge();
      if (!r.found) {
        out.innerHTML = `<div class="callout warn">${icon("alert")}<div><b>No barcode found.</b>
          <ul><li>Fill most of the frame with the barcode and keep it flat.</li><li>Avoid glare; add light or turn on the flash LED (Camera page).</li>
          <li>Use at least SVGA (800×600) frame size.</li></ul><div class="tiny">Tried: ${esc(r.variants_tried.join(", "))} · ${esc(r.library)}</div></div></div>`;
        return;
      }
      const lk = r.lookup;
      out.innerHTML = `<div class="stack">${r.codes.map((c) => `<div class="card card-pad"><div class="row between"><div>
          <div class="tiny muted">${esc(c.format)}</div><div style="font-size:22px;font-weight:700" class="mono">${esc(c.text)}</div></div>
          <span class="badge b-fresh">checksum OK</span></div></div>`).join("")}
        ${lk ? (lk.found ? `<div class="callout ok">${icon("checkCircle")}<div><b>${esc(lk.product.name || "Unnamed")}</b>
            <div>${esc([lk.product.brand, lk.product.category].filter(Boolean).join(" · "))}</div><div class="tiny">Source: ${esc(lk.source)}${lk.cached ? " (cached)" : ""}</div></div></div>`
          : `<div class="callout warn">${icon("alert")}<div><b>${lk.errors?.length ? "Product databases could not be reached." : "Not found in product databases."}</b>
            <div class="small">${esc(lk.errors?.join("; ") || "You can enter the name once; future scans of this barcode will recognise it.")}</div></div></div>`) : ""}
        <div class="row"><a class="btn btn-primary" href="#/scan?merge=${r.scan_id}">${icon("layers")}Now scan the expiry date</a>
          <a class="btn" href="#/add?barcode=${encodeURIComponent(r.codes[0].text)}${lk?.found ? `&name=${encodeURIComponent(lk.product.name || "")}&brand=${encodeURIComponent(lk.product.brand || "")}&category=${encodeURIComponent(lk.product.category || "")}` : ""}">${icon("plus")}Add manually</a></div>
      </div>`;
    } catch (err) {
      out.innerHTML = errorBox(err, "Could not decode");
      refreshCameraBadge();
    }
  }
  $("#cap", el).onclick = (e) => { const f = new FormData(); f.append("source", "camera"); run(f, e.currentTarget); };
  $("#file", el).onchange = (e) => { const file = e.target.files[0]; if (!file) return; const f = new FormData(); f.append("image", file); run(f, $("#cap", el)); e.target.value = ""; };
}
