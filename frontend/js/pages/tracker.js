import { api } from "../api.js";
import { categories } from "../productForm.js";
import { $, daysText, emptyState, errorBox, esc, icon, thumb, productName } from "../ui.js";

const LANES = [
  ["expired", "Expired", "var(--red-600)"],
  ["expiring_soon", "Expiring soon", "var(--amber-600)"],
  ["fresh", "Fresh", "var(--emerald-600)"],
  ["unknown", "Unknown", "var(--slate-600)"],
];

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Expiry tracker</h1><p id="thr" class="muted">Products grouped by how much time is left.</p></div>
    <div class="toolbar"><input type="search" id="q" placeholder="Search name, brand, barcode…" aria-label="Search">
      <select id="cat" aria-label="Category"><option value="">All categories</option>${categories().map((c) => `<option>${esc(c)}</option>`).join("")}</select></div></div>
    <div id="lanes"><div class="skeleton" style="height:200px"></div></div>`;
  let fresh = 30;
  try { fresh = (await api.get("/api/settings")).settings.fresh_days; } catch { /* default */ }
  $("#thr", el).textContent = `Fresh: more than ${fresh} days left · Expiring soon: 0–${fresh} days · Expired: past the date · Unknown: no verified expiry. Month-only dates count until the end of that month.`;

  async function load() {
    const qs = new URLSearchParams({ sort: "expiry_asc" });
    if ($("#q", el).value) qs.set("q", $("#q", el).value);
    if ($("#cat", el).value) qs.set("category", $("#cat", el).value);
    let data;
    try { data = await api.get(`/api/products?${qs}`); } catch (err) { $("#lanes", el).innerHTML = errorBox(err); return; }
    $("#lanes", el).innerHTML = `<div class="lanes">${LANES.map(([key, label, color]) => {
      const items = data.items.filter((p) => p.status === key);
      if (key === "expired") items.reverse();
      return `<section class="card lane"><div class="lane-head"><div class="row"><span class="dot" style="background:${color}"></span><h3>${label}</h3></div><span class="badge plain b-${key}">${items.length}</span></div>
        <div class="list">${items.length ? items.map((p) => {
          const d = daysText(p);
          const pct = p.days_left == null ? 0 : Math.max(4, Math.min(100, 100 - (p.days_left / Math.max(fresh * 3, 1)) * 100));
          return `<a class="product-card" href="#/inventory?id=${p.id}" style="color:inherit;text-decoration:none">${thumb(p)}<div style="min-width:0">
            <div class="name" style="font-size:13.5px">${productName(p)}${p.quantity > 1 ? ` <span class="muted small">×${p.quantity}</span>` : ""}</div>
            <div class="meta">${esc(p.expiry_label)} · <b style="color:${color}">${esc(d.big)} ${esc(d.small)}</b></div>
            ${p.days_left != null ? `<div class="progress"><i style="width:${pct}%;background:${color}"></i></div>` : `<div class="tiny muted">${p.verification_status === "unverified" ? "awaiting confirmation" : "no expiry recorded"}</div>`}
          </div></a>`;
        }).join("") : emptyState("checkCircle", "Nothing here")}</div></section>`;
    }).join("")}</div>`;
  }
  let t;
  $("#q", el).oninput = () => { clearTimeout(t); t = setTimeout(load, 250); };
  $("#cat", el).onchange = load;
  await load();
  void icon;
}
