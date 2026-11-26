import { api } from "../api.js";
import { refreshNotifications } from "../app.js";
import { categories, productFormHtml, readProductForm, wireProductForm } from "../productForm.js";
import { $, $$, busy, confirmDialog, conf, daysText, emptyState, errorBox, esc, fmtDate, icon, imgUrl, modal, productName, statusBadge, thumb, toast } from "../ui.js";

const VERIF = { user_verified: "Verified by you", auto_verified: "Auto-verified", unverified: "Unverified" };

function editModal(p, onDone) {
  modal(`<form id="edit"><div class="card-head"><h2>Edit product</h2><button type="button" class="btn btn-ghost btn-icon" data-close aria-label="Close">${icon("x")}</button></div>
    <div class="card-body">
      ${p.image_url ? `<div class="row" style="margin-bottom:14px;align-items:flex-start"><img src="${esc(imgUrl(p.image_url))}" alt="" style="width:160px;border-radius:10px;border:1px solid var(--border)">
        <div class="small stack" style="flex:1;min-width:200px"><div>${statusBadge(p.status)} <span class="badge b-info plain">${esc(VERIF[p.verification_status] || p.verification_status)}</span></div>
        <div class="muted">Identity from: ${esc(p.identity_source || "—")} · Expiry from: ${esc(p.expiry_source || "—")}</div>
        ${p.confidence != null ? `<div>Recognition confidence ${conf(p.confidence)}</div>` : ""}</div></div>` : ""}
      ${productFormHtml(p, { confidence: p.field_confidence || {} })}
      ${p.ocr_text ? `<details style="margin-top:12px"><summary>Original OCR text</summary><pre class="ocr">${esc(p.ocr_text)}</pre></details>` : ""}
      <div id="err" style="margin-top:10px"></div></div>
    <div class="card-foot"><button type="button" class="btn btn-danger" id="del" style="margin-right:auto">${icon("trash")}Delete</button>
      <button type="button" class="btn" data-close>Cancel</button><button class="btn btn-primary">${icon("check")}Save changes</button></div></form>`,
  { wide: true, onMount: (m, close) => {
    const f = m.querySelector("#edit");
    wireProductForm(f);
    f.onsubmit = async (e) => {
      e.preventDefault();
      let data;
      try { data = readProductForm(f); } catch (err) { $("#err", m).innerHTML = errorBox(err, "Check the form"); return; }
      try {
        await busy(f.querySelector(".btn-primary"), () => api.put(`/api/products/${p.id}`, data), "Saving…");
        toast("Product updated"); close(); onDone(); refreshNotifications();
      } catch (err) { $("#err", m).innerHTML = errorBox(err, "Could not save"); }
    };
    m.querySelector("#del").onclick = async () => {
      if (!(await confirmDialog("Delete product?", `“${p.name || p.barcode}” and its alerts will be removed permanently.`, { okLabel: "Delete", danger: true }))) return;
      try { await api.del(`/api/products/${p.id}`); toast("Product deleted"); close(); onDone(); refreshNotifications(); }
      catch (err) { $("#err", m).innerHTML = errorBox(err, "Could not delete"); }
    };
  } });
}

export async function render(el, params) {
  el.innerHTML = `<div class="page-head"><div><h1>Product inventory</h1><p id="count" class="muted">&nbsp;</p></div>
    <a class="btn btn-primary" href="#/add">${icon("plus")}Add product</a></div>
    <div class="card"><div class="card-head" style="flex-wrap:wrap"><div class="toolbar">
      <input type="search" id="q" placeholder="Search name, brand, barcode, batch…" aria-label="Search">
      <select id="cat" aria-label="Category"><option value="">All categories</option>${categories().map((c) => `<option>${esc(c)}</option>`).join("")}</select>
      <select id="status" aria-label="Status"><option value="">All statuses</option><option value="fresh">Fresh</option><option value="expiring_soon">Expiring soon</option><option value="expired">Expired</option><option value="unknown">Unknown</option></select>
      <select id="sort" aria-label="Sort"><option value="expiry_asc">Expiry: soonest first</option><option value="expiry_desc">Expiry: latest first</option><option value="name">Name A–Z</option><option value="scanned_desc">Recently scanned</option></select>
    </div></div><div class="table-wrap" id="table"><div class="card-body"><div class="skeleton" style="height:120px"></div></div></div></div>`;

  let items = [];
  async function load() {
    const qs = new URLSearchParams();
    for (const [id, key] of [["q", "q"], ["cat", "category"], ["status", "status"], ["sort", "sort"]]) {
      const v = $(`#${id}`, el).value; if (v) qs.set(key, v);
    }
    let data;
    try { data = await api.get(`/api/products?${qs}`); } catch (err) { $("#table", el).innerHTML = `<div class="card-body">${errorBox(err)}</div>`; return; }
    items = data.items;
    $("#count", el).textContent = `${data.total} product${data.total === 1 ? "" : "s"}`;
    if (!items.length) {
      $("#table", el).innerHTML = emptyState("box", "No products match", "Scan a product or adjust the filters.", '<a class="btn btn-primary" href="#/scan">Scan product</a>');
      return;
    }
    $("#table", el).innerHTML = `<table><thead><tr><th></th><th>Product</th><th>Category</th><th>Barcode</th><th>Batch</th><th>Mfg</th><th>Expiry</th><th>Status</th><th>Qty</th><th></th></tr></thead><tbody>
      ${items.map((p) => { const d = daysText(p); return `<tr data-id="${p.id}">
        <td>${thumb(p)}</td>
        <td><div style="font-weight:600">${productName(p)}</div><div class="tiny muted">${esc(p.brand || "")}${p.verification_status === "unverified" ? ' · <span style="color:var(--amber-600)">unverified</span>' : ""}</div></td>
        <td>${esc(p.category || "—")}</td><td class="mono small">${esc(p.barcode || "—")}</td><td class="mono small">${esc(p.batch_no || "—")}</td>
        <td class="small">${esc(fmtDate(p.mfg_date, p.mfg_precision))}</td>
        <td class="small"><b>${esc(fmtDate(p.expiry_date, p.expiry_precision))}</b><div class="tiny muted">${esc(d.big)} ${esc(d.small)}</div></td>
        <td>${statusBadge(p.status)}</td><td>${esc(p.quantity)}</td>
        <td><div class="row" style="flex-wrap:nowrap;gap:4px"><button class="btn btn-ghost btn-icon" data-edit="${p.id}" aria-label="Edit">${icon("edit")}</button>
          <button class="btn btn-ghost btn-icon btn-danger" data-del="${p.id}" aria-label="Delete">${icon("trash")}</button></div></td></tr>`; }).join("")}
      </tbody></table>`;
    $$("[data-edit]", el).forEach((b) => (b.onclick = () => editModal(items.find((x) => x.id == b.dataset.edit), load)));
    $$("[data-del]", el).forEach((b) => (b.onclick = async () => {
      const p = items.find((x) => x.id == b.dataset.del);
      if (!(await confirmDialog("Delete product?", `“${p.name || p.barcode}” will be removed permanently.`, { okLabel: "Delete", danger: true }))) return;
      try { await api.del(`/api/products/${p.id}`); toast("Product deleted"); load(); refreshNotifications(); } catch (err) { toast("Delete failed", { type: "err", text: err.message }); }
    }));
  }
  let t;
  $("#q", el).oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  ["cat", "status", "sort"].forEach((id) => ($(`#${id}`, el).onchange = load));
  await load();
  const id = params.get("id");
  if (id) {
    try { editModal(await api.get(`/api/products/${id}`), load); } catch (err) { toast("Product not found", { type: "err", text: err.message }); }
  }
}
