import { url } from "./api.js";

// ---------------------------------------------------------------- icons
const P = {
  leaf: '<path d="M11 20A7 7 0 0 1 9.8 6.1C15.5 5 17 4.48 19 2c1 2 2 4.18 2 8 0 5.5-4.78 10-10 10Z"/><path d="M2 21c0-3 1.85-5.36 5.08-6C9.5 14.52 12 13 13 12"/>',
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  scan: '<path d="M3 7V5a2 2 0 0 1 2-2h2"/><path d="M17 3h2a2 2 0 0 1 2 2v2"/><path d="M21 17v2a2 2 0 0 1-2 2h-2"/><path d="M7 21H5a2 2 0 0 1-2-2v-2"/><path d="M7 12h10"/>',
  clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
  barcode: '<path d="M3 5v14"/><path d="M7 5v14"/><path d="M10 5v14"/><path d="M14 5v14"/><path d="M17 5v14"/><path d="M21 5v14"/>',
  box: '<path d="M21 8 12 3 3 8v8l9 5 9-5Z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/>',
  plus: '<path d="M12 5v14"/><path d="M5 12h14"/>',
  camera: '<path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3Z"/><circle cx="12" cy="13" r="3.5"/>',
  settings: '<path d="M12.22 2h-.44a2 2 0 0 0-2 2v.18a2 2 0 0 1-1 1.73l-.43.25a2 2 0 0 1-2 0l-.15-.08a2 2 0 0 0-2.73.73l-.22.38a2 2 0 0 0 .73 2.73l.15.1a2 2 0 0 1 1 1.72v.51a2 2 0 0 1-1 1.74l-.15.09a2 2 0 0 0-.73 2.73l.22.38a2 2 0 0 0 2.73.73l.15-.08a2 2 0 0 1 2 0l.43.25a2 2 0 0 1 1 1.73V20a2 2 0 0 0 2 2h.44a2 2 0 0 0 2-2v-.18a2 2 0 0 1 1-1.73l.43-.25a2 2 0 0 1 2 0l.15.08a2 2 0 0 0 2.73-.73l.22-.39a2 2 0 0 0-.73-2.73l-.15-.08a2 2 0 0 1-1-1.74v-.5a2 2 0 0 1 1-1.74l.15-.09a2 2 0 0 0 .73-2.73l-.22-.38a2 2 0 0 0-2.73-.73l-.15.08a2 2 0 0 1-2 0l-.43-.25a2 2 0 0 1-1-1.73V4a2 2 0 0 0-2-2z"/><circle cx="12" cy="12" r="3"/>',
  activity: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  bell: '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/><path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>',
  check: '<path d="M20 6 9 17l-5-5"/>',
  checkCircle: '<circle cx="12" cy="12" r="9"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
  alert: '<path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/>',
  x: '<path d="M18 6 6 18"/><path d="m6 6 12 12"/>',
  xCircle: '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.09-3.09a2 2 0 0 0-2.82 0L6 21"/>',
  search: '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/>',
  trash: '<path d="M3 6h18"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6"/><path d="M8 6V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>',
  upload: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
  wifi: '<path d="M12 20h.01"/><path d="M2 8.82a15 15 0 0 1 20 0"/><path d="M5 12.86a10 10 0 0 1 14 0"/><path d="M8.5 16.43a5 5 0 0 1 7 0"/>',
  wifiOff: '<path d="M12 20h.01"/><path d="M8.5 16.43a5 5 0 0 1 7 0"/><path d="M2 8.82a15 15 0 0 1 4.17-2.65"/><path d="M10.66 5c4.01-.36 8.14.9 11.34 3.76"/><path d="M16.85 11.25a10 10 0 0 1 2.22 1.68"/><path d="M5 13a10 10 0 0 1 5.24-2.76"/><path d="m2 2 20 20"/>',
  menu: '<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>',
  db: '<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3"/>',
  server: '<rect x="2" y="3" width="20" height="8" rx="2"/><rect x="2" y="13" width="20" height="8" rx="2"/><path d="M6 7h.01"/><path d="M6 17h.01"/>',
  text: '<path d="M4 7V4h16v3"/><path d="M9 20h6"/><path d="M12 4v16"/>',
  sparkles: '<path d="m12 3-1.9 5.8a2 2 0 0 1-1.3 1.3L3 12l5.8 1.9a2 2 0 0 1 1.3 1.3L12 21l1.9-5.8a2 2 0 0 1 1.3-1.3L21 12l-5.8-1.9a2 2 0 0 1-1.3-1.3Z"/>',
  monitor: '<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8"/><path d="M12 17v4"/>',
  shield: '<path d="M20 13c0 5-3.5 7.5-7.66 8.95a1 1 0 0 1-.67-.01C7.5 20.5 4 18 4 13V6a1 1 0 0 1 1-1c2 0 4.5-1.2 6.24-2.72a1.17 1.17 0 0 1 1.52 0C14.51 3.81 17 5 19 5a1 1 0 0 1 1 1z"/>',
  globe: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a14 14 0 0 1 0 18a14 14 0 0 1 0-18"/>',
  layers: '<path d="m12 2 10 5-10 5L2 7Z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/>',
  zap: '<path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/>',
  logout: '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="m16 17 5-5-5-5"/><path d="M21 12H9"/>',
};
export function icon(name, cls = "") {
  return `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${P[name] || ""}</svg>`;
}

// ------------------------------------------------------------- helpers
export function esc(v) {
  return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
export function imgUrl(path, bust = false) { return path ? url(path) + (bust ? `${path.includes("?") ? "&" : "?"}t=${Date.now()}` : "") : ""; }

export const STATUS_LABEL = { fresh: "Fresh", expiring_soon: "Expiring soon", expired: "Expired", unknown: "Unknown" };
export function statusBadge(s) { return `<span class="badge b-${esc(s)}">${STATUS_LABEL[s] || esc(s)}</span>`; }
export function daysText(p) {
  if (p.days_left == null) return { big: "—", small: "no expiry" };
  const d = p.days_left;
  if (d < 0) return { big: `${-d}d`, small: "ago" };
  if (d === 0) return { big: "Today", small: p.expiry_precision === "month" ? "end of month" : "last day" };
  if (d === 1) return { big: "1 day", small: "left" };
  if (d > 365) return { big: `${(d / 365).toFixed(1)} yr`, small: "left" };
  return { big: `${d} days`, small: "left" };
}
export function fmtDate(iso, precision) {
  if (!iso) return "—";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d || 1);
  return precision === "month" || !d
    ? dt.toLocaleDateString(undefined, { month: "short", year: "numeric" })
    : dt.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
export function timeAgo(iso) {
  if (!iso) return "never";
  const s = Math.round((Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 10) return "just now";
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString();
}
export function conf(v, thr = 0.75) {
  if (v == null) return "";
  const pct = Math.round(v * 100);
  return `<span class="conf ${v < thr ? "low" : ""}" title="Confidence ${pct}%"><span class="conf-bar"><i style="width:${pct}%"></i></span>${pct}%</span>`;
}
export function productName(p) {
  if (!p.name) return p.barcode ? `Barcode ${esc(p.barcode)}` : "Unnamed product";
  return esc(p.name);
}
export function thumb(p) {
  return p.image_url ? `<img class="thumb" loading="lazy" src="${esc(imgUrl(p.image_url))}" alt="">` : `<div class="thumb">${icon("box")}</div>`;
}
export function productCard(p, { href = true } = {}) {
  const d = daysText(p);
  const color = { fresh: "var(--emerald-600)", expiring_soon: "var(--amber-600)", expired: "var(--red-600)" }[p.status] || "var(--muted)";
  const tag = href ? "a" : "div";
  return `<${tag} class="product-card" ${href ? `href="#/inventory?id=${p.id}" style="color:inherit;text-decoration:none"` : ""}>
    ${thumb(p)}
    <div style="min-width:0">
      <div class="name">${productName(p)} ${p.quantity > 1 ? `<span class="muted small">×${p.quantity}</span>` : ""}</div>
      <div class="meta">${esc([p.brand, p.category].filter(Boolean).join(" · ") || "—")}</div>
      <div class="row" style="margin-top:6px;gap:8px">${statusBadge(p.status)}<span class="tiny muted">Exp ${esc(p.expiry_label)}</span></div>
    </div>
    <div class="days" style="color:${color}">${esc(d.big)}<small>${esc(d.small)}</small></div>
  </${tag}>`;
}
export function emptyState(iconName, title, text = "", action = "") {
  return `<div class="empty">${icon(iconName)}<div><b style="color:var(--text)">${esc(title)}</b><div class="small">${esc(text)}</div></div>${action}</div>`;
}
export function errorBox(err, title = "Something went wrong") {
  return `<div class="callout err">${icon("xCircle")}<div><b>${esc(title)}</b><div>${esc(err.message || err)}</div>${err.hint ? `<div class="small" style="margin-top:4px">${esc(err.hint)}</div>` : ""}</div></div>`;
}

// --------------------------------------------------------------- toast
export function toast(title, { text = "", type = "ok", action = null, timeout = 5000 } = {}) {
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `${icon(type === "err" ? "xCircle" : type === "warn" ? "alert" : "checkCircle")}<div><div class="t">${esc(title)}</div>${text ? `<div class="d">${esc(text)}</div>` : ""}</div>${action ? `<button type="button">${esc(action.label)}</button>` : ""}`;
  if (action) el.querySelector("button").onclick = () => { action.run(); el.remove(); };
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), timeout);
}

// --------------------------------------------------------------- modal
export function modal(html, { onMount, wide = false } = {}) {
  const root = $("#modal-root");
  const back = document.createElement("div");
  back.className = "modal-back";
  back.innerHTML = `<div class="modal" role="dialog" aria-modal="true" style="${wide ? "width:min(860px,100%)" : ""}">${html}</div>`;
  const close = () => { back.remove(); document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  back.addEventListener("mousedown", (e) => { if (e.target === back) close(); });
  document.addEventListener("keydown", onKey);
  root.appendChild(back);
  const m = back.querySelector(".modal");
  $$("[data-close]", m).forEach((b) => (b.onclick = close));
  onMount && onMount(m, close);
  const first = m.querySelector("input, select, textarea, button");
  first && first.focus();
  return close;
}

export function confirmDialog(title, text, { okLabel = "Confirm", danger = false } = {}) {
  return new Promise((resolve) => {
    modal(`<div class="card-head"><h2>${esc(title)}</h2></div><div class="card-body"><p>${esc(text)}</p></div>
      <div class="card-foot"><button class="btn" data-close>Cancel</button><button class="btn ${danger ? "btn-danger" : "btn-primary"}" id="ok">${esc(okLabel)}</button></div>`,
    { onMount: (m, close) => {
      m.querySelector("#ok").onclick = () => { close(); resolve(true); };
      $$("[data-close]", m).forEach((b) => (b.onclick = () => { close(); resolve(false); }));
    } });
  });
}

export async function busy(btn, fn, label) {
  const old = btn.innerHTML;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${esc(label || btn.textContent.trim())}`;
  try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = old; }
}
