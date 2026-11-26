import { api } from "../api.js";
import { emptyState, errorBox, esc, icon, productCard } from "../ui.js";

function donut(s) {
  const parts = [["fresh", "#10b981"], ["expiring_soon", "#f59e0b"], ["expired", "#ef4444"], ["unknown", "#d1d5db"]];
  const total = parts.reduce((a, [k]) => a + (s[k] || 0), 0);
  if (!total) return '<svg viewBox="0 0 42 42" width="150" height="150"><circle cx="21" cy="21" r="15.9" fill="none" stroke="#eef2f0" stroke-width="5"/></svg>';
  let off = 25;
  const segs = parts.map(([k, c]) => {
    const pct = ((s[k] || 0) / total) * 100;
    const seg = pct ? `<circle cx="21" cy="21" r="15.9" fill="none" stroke="${c}" stroke-width="5" stroke-dasharray="${pct} ${100 - pct}" stroke-dashoffset="${off}"/>` : "";
    off -= pct;
    return seg;
  }).join("");
  return `<svg viewBox="0 0 42 42" width="150" height="150" role="img" aria-label="Expiry status breakdown">
    <circle cx="21" cy="21" r="15.9" fill="none" stroke="#eef2f0" stroke-width="5"/>${segs}
    <text x="21" y="21" text-anchor="middle" font-size="8" font-weight="700" fill="#111827">${total}</text>
    <text x="21" y="27" text-anchor="middle" font-size="3.2" fill="#6b7280">products</text></svg>`;
}

export async function render(el) {
  el.innerHTML = `<div class="page-head"><div><h1>Good to see you</h1><p>What's in your kitchen and medicine cabinet, and what needs attention.</p></div>
    <div class="row"><a class="btn" href="#/add">${icon("plus")}Add manually</a><a class="btn btn-primary" href="#/scan">${icon("scan")}Scan a product</a></div></div>
    <div id="dash"><div class="grid cols-4">${'<div class="card stat"><div class="skeleton" style="height:60px"></div></div>'.repeat(4)}</div></div>`;
  let s;
  try { s = await api.get("/api/expiry/summary"); } catch (err) { el.querySelector("#dash").innerHTML = errorBox(err, "Could not load the dashboard"); return; }
  const fd = s.thresholds.fresh_days;
  const stat = (tone, ic, label, value, sub, href) => `<a class="card stat tone-${tone}" href="${href}" style="color:inherit;text-decoration:none">
    <div class="icon">${icon(ic)}</div><div class="label">${label}</div><div class="value">${value}</div><div class="tiny muted">${sub}</div></a>`;
  const maxMonth = Math.max(1, ...s.upcoming_by_month.map((m) => m.count));
  const catRows = s.categories.slice(0, 8).map((c) => {
    const w = (k) => `${((c[k] || 0) / c.total) * 100}%`;
    return `<div class="bar-row"><span>${esc(c.category)}</span><div class="bar-track">
      <i class="seg-fresh" style="width:${w("fresh")}"></i><i class="seg-soon" style="width:${w("expiring_soon")}"></i>
      <i class="seg-expired" style="width:${w("expired")}"></i><i class="seg-unknown" style="width:${w("unknown")}"></i></div><b>${c.total}</b></div>`;
  }).join("");

  el.querySelector("#dash").innerHTML = `
    ${s.expired || s.expiring_soon ? `<div class="alert-strip">
      ${s.expired ? `<div class="callout err">${icon("alert")}<div><b>${s.expired} product${s.expired > 1 ? "s have" : " has"} expired.</b> Check and discard safely. <a href="#/tracker">Review</a></div></div>` : ""}
      ${s.expiring_soon ? `<div class="callout warn">${icon("clock")}<div><b>${s.expiring_soon} product${s.expiring_soon > 1 ? "s" : ""} expiring within ${fd} days.</b> <a href="#/tracker">Plan to use them</a></div></div>` : ""}
    </div>` : ""}
    <div class="grid cols-4">
      ${stat("forest", "box", "Total products", s.total, `${s.total_units} units tracked`, "#/inventory")}
      ${stat("green", "leaf", "Fresh", s.fresh, `more than ${fd} days left`, "#/tracker")}
      ${stat("amber", "clock", "Expiring soon", s.expiring_soon, `within ${fd} days`, "#/tracker")}
      ${stat("red", "alert", "Expired", s.expired, `${s.unknown} with unknown expiry`, "#/tracker")}
    </div>
    <div class="grid split" style="margin-top:18px">
      <div class="card"><div class="card-head"><h2>Needs attention</h2><a class="btn btn-ghost btn-sm" href="#/tracker">Open tracker</a></div>
        <div class="list" style="padding:8px">${s.attention.length ? s.attention.map((p) => productCard(p)).join("")
          : emptyState("checkCircle", "Nothing is expiring soon", `Items appear here ${fd} days before they expire.`)}</div></div>
      <div class="grid">
        <div class="card"><div class="card-head"><h2>Expiry statistics</h2></div><div class="card-body donut-wrap">${donut(s)}
          <div class="stack small">
            <div class="row between"><span class="legend"><span><i class="seg-fresh"></i>Fresh</span></span><b>${s.fresh}</b></div>
            <div class="row between"><span class="legend"><span><i class="seg-soon"></i>Expiring soon</span></span><b>${s.expiring_soon}</b></div>
            <div class="row between"><span class="legend"><span><i class="seg-expired"></i>Expired</span></span><b>${s.expired}</b></div>
            <div class="row between"><span class="legend"><span><i class="seg-unknown"></i>Unknown / unverified</span></span><b>${s.unknown}</b></div>
          </div></div></div>
        <div class="card"><div class="card-head"><h2>Expiring by month</h2><span class="tiny muted">next 6 months</span></div>
          <div class="card-body"><div class="columns">${s.upcoming_by_month.map((m) => {
            const [y, mo] = m.month.split("-").map(Number);
            return `<div class="col"><b>${m.count}</b><i style="height:${Math.round((m.count / maxMonth) * 100)}px"></i><span>${new Date(y, mo - 1, 1).toLocaleDateString(undefined, { month: "short" })}</span></div>`;
          }).join("")}</div></div></div>
      </div>
    </div>
    <div class="grid cols-2" style="margin-top:18px">
      <div class="card"><div class="card-head"><h2>Recently scanned</h2><a class="btn btn-ghost btn-sm" href="#/inventory">All products</a></div>
        <div class="list" style="padding:8px">${s.recent.length ? s.recent.map((p) => productCard(p)).join("")
          : emptyState("scan", "No products yet", "Scan your first product with the ESP32-CAM.", '<a class="btn btn-primary" href="#/scan">Start scanning</a>')}</div></div>
      <div class="card"><div class="card-head"><h2>Product categories</h2><div class="legend"><span><i class="seg-fresh"></i>Fresh</span><span><i class="seg-soon"></i>Soon</span><span><i class="seg-expired"></i>Expired</span><span><i class="seg-unknown"></i>Unknown</span></div></div>
        <div class="card-body bars">${catRows || emptyState("layers", "No categories yet")}</div></div>
    </div>`;
}
