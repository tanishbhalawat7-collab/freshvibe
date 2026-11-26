import { api } from "../api.js";
import { refreshNotifications } from "../app.js";
import { productFormHtml, readProductForm, wireProductForm } from "../productForm.js";
import { $, busy, errorBox, esc, icon, productCard, toast } from "../ui.js";

export async function render(el, params) {
  const pre = Object.fromEntries([...params.entries()].filter(([k]) => ["name", "brand", "category", "barcode"].includes(k)));
  el.innerHTML = `<div class="page-head"><div><h1>Add product</h1><p>Enter details by hand, or let Fresh Vibe pre-fill them from a photo.</p></div></div>
    <div class="grid split">
      <div class="card"><form id="f"><div class="card-body">${productFormHtml(pre)}<div id="err" style="margin-top:12px"></div></div>
        <div class="card-foot"><button type="reset" class="btn">Clear</button><button class="btn btn-primary">${icon("check")}Save product</button></div></form></div>
      <div class="stack">
        <div class="card card-pad stack"><h2>Pre-fill from a photo</h2>
          <p class="muted small">Capture with the ESP32-CAM or upload a photo. Recognised values are placed in the form for you to check — nothing is saved until you press Save.</p>
          <div class="row"><button class="btn" id="cam">${icon("camera")}Capture</button><label class="btn" for="file">${icon("upload")}Upload</label>
          <input type="file" id="file" accept="image/*" capture="environment" class="sr-only"></div><div id="fill"></div></div>
        <div id="saved"></div>
      </div></div>`;
  const form = $("#f", el);
  wireProductForm(form);
  let scanId = null;

  form.onsubmit = async (e) => {
    e.preventDefault();
    let data;
    try { data = readProductForm(form); } catch (err) { $("#err", el).innerHTML = errorBox(err, "Check the form"); return; }
    $("#err", el).innerHTML = "";
    try {
      const r = await busy(form.querySelector(".btn-primary"), () => api.post("/api/products", { ...data, ...(scanId ? { scan_id: scanId } : {}) }), "Saving…");
      toast(r.duplicate ? "Already in inventory — quantity increased" : "Product added", { text: `${r.product.name || r.product.barcode} · expires ${r.product.expiry_label}` });
      $("#saved", el).innerHTML = `<div class="card"><div class="card-head"><h3>${r.duplicate ? "Merged with existing item" : "Saved"}</h3></div>${productCard(r.product)}</div>`;
      form.reset(); scanId = null; refreshNotifications();
    } catch (err) { $("#err", el).innerHTML = errorBox(err, "Could not save"); }
  };

  async function prefill(fd, btn) {
    fd.append("auto_save", "false");
    $("#fill", el).innerHTML = '<div class="row"><div class="spinner"></div>Reading the image…</div>';
    try {
      const r = await busy(btn, () => api.postForm("/api/scan/process", fd, { timeout: 120000 }), "Reading…");
      scanId = r.scan_id;
      const f = r.fields;
      const filled = [];
      for (const k of ["name", "brand", "category", "barcode", "batch_no", "mfg_date", "expiry_date"]) {
        if (!f[k]?.value) continue;
        const input = form.querySelector(`[name=${k}]`);
        if (k.endsWith("_date")) {
          const sel = form.querySelector(`[name=${k}_precision]`);
          sel.value = f[k].precision || "day"; sel.onchange();
        }
        input.value = f[k].value;
        input.closest(".field").classList.toggle("uncertain", f[k].confidence < r.threshold);
        filled.push(k.replace("_", " "));
      }
      $("#fill", el).innerHTML = filled.length
        ? `<div class="callout ok">${icon("checkCircle")}<div>Filled: ${esc(filled.join(", "))}. Fields marked in amber are uncertain — check them against the pack.</div></div>`
        : `<div class="callout warn">${icon("alert")}<div>Nothing could be read reliably. ${esc(r.decision.tips.join(" "))}</div></div>`;
    } catch (err) { $("#fill", el).innerHTML = errorBox(err, "Could not read the image"); }
  }
  $("#cam", el).onclick = (e) => { const fd = new FormData(); fd.append("source", "camera"); prefill(fd, e.currentTarget); };
  $("#file", el).onchange = (e) => { const file = e.target.files[0]; if (!file) return; const fd = new FormData(); fd.append("image", file); prefill(fd, $("#cam", el)); e.target.value = ""; };
}
