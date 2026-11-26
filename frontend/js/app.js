import { api, onAuthRequired, setToken } from "./api.js";
import { setCategories } from "./productForm.js";
import { $, esc, icon, modal, timeAgo, toast } from "./ui.js";

const ROUTES = [
  { path: "dashboard", label: "Dashboard", icon: "dashboard", mod: () => import("./pages/dashboard.js") },
  { path: "scan", label: "Scan Product", icon: "scan", mod: () => import("./pages/scan.js") },
  { path: "tracker", label: "Expiry Tracker", icon: "clock", mod: () => import("./pages/tracker.js") },
  { path: "barcode", label: "Barcode Scanner", icon: "barcode", mod: () => import("./pages/barcode.js") },
  { path: "inventory", label: "Product Inventory", icon: "box", mod: () => import("./pages/inventory.js") },
  { path: "add", label: "Add Product", icon: "plus", mod: () => import("./pages/add.js") },
  { path: "camera", label: "Connect Camera", icon: "camera", mod: () => import("./pages/camera.js") },
  { path: "settings", label: "Settings", icon: "settings", mod: () => import("./pages/settings.js") },
  { sep: true },
  { path: "diagnostics", label: "Diagnostics", icon: "activity", mod: () => import("./pages/diagnostics.js") },
];

let cleanup = null;
let navToken = 0;

function renderNav() {
  $("#nav").innerHTML = ROUTES.map((r) => r.sep ? '<div class="nav-sep"></div>'
    : `<a href="#/${r.path}" data-path="${r.path}">${icon(r.icon)}<span>${esc(r.label)}</span></a>`).join("");
  $("#brand-mark").innerHTML = icon("leaf");
  $("#menu-btn").innerHTML = icon("menu");
  $("#bell").innerHTML = icon("bell");
  $("#quick-scan").innerHTML = `${icon("scan")}<span>Scan</span>`;
  $("#menu-btn").onclick = () => $("#sidebar").classList.toggle("open");
}

export function parseHash() {
  const h = location.hash.replace(/^#\/?/, "") || "dashboard";
  const [path, qs] = h.split("?");
  return { path, params: new URLSearchParams(qs || "") };
}

async function route() {
  const { path, params } = parseHash();
  const r = ROUTES.find((x) => x.path === path) || ROUTES[0];
  const my = ++navToken;
  document.querySelectorAll("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.path === r.path));
  $("#page-title").textContent = r.label;
  document.title = `${r.label} · Fresh Vibe`;
  $("#sidebar").classList.remove("open");
  if (cleanup) { try { cleanup(); } catch { /* ignore */ } cleanup = null; }
  const view = $("#view");
  view.innerHTML = '<div class="skeleton" style="height:28px;width:220px"></div>';
  try {
    const mod = await r.mod();
    if (my !== navToken) return;
    view.innerHTML = "";
    const page = document.createElement("div");
    page.className = "page";
    view.appendChild(page);
    cleanup = (await mod.render(page, params)) || null;
  } catch (err) {
    console.error(err);
    view.innerHTML = `<div class="callout err">${icon("xCircle")}<div><b>Could not load this page</b><div>${esc(err.message)}</div></div></div>`;
  }
  view.focus({ preventScroll: true });
  window.scrollTo(0, 0);
}

// ---------------------------------------------------- camera mini status
export async function refreshCameraBadge() {
  const dot = $("#cam-dot"), text = $("#cam-text");
  try {
    const s = await api.get("/api/camera/state", { timeout: 8000, retryAuth: false });
    const map = { connected: ["ok", "Camera connected"], connecting: ["busy", "Camera: connecting…"],
      disconnected: ["err", "Camera offline"], unknown: ["", "Camera: not tested"] };
    const [cls, label] = map[s.status] || map.unknown;
    dot.className = `dot ${cls}`;
    text.textContent = label;
    text.title = s.status === "connected" ? `Last real capture ${timeAgo(s.last_success_at)}` : (s.last_error?.message || "");
  } catch (err) {
    dot.className = "dot err";
    text.textContent = err.code === "auth_required" ? "Sign in required" : "Backend unreachable";
  }
}

// ---------------------------------------------------------- notifications
const SHOWN_KEY = "fv_shown_notifications";
function shownSet() { try { return new Set(JSON.parse(localStorage.getItem(SHOWN_KEY) || "[]")); } catch { return new Set(); } }
function saveShown(s) { try { localStorage.setItem(SHOWN_KEY, JSON.stringify([...s].slice(-500))); } catch { /* ignore */ } }

async function refreshNotifications() {
  let data;
  try { data = await api.get("/api/notifications", { retryAuth: false }); } catch { return; }
  const bell = $("#bell");
  bell.querySelector(".count")?.remove();
  if (data.unread) bell.insertAdjacentHTML("beforeend", `<span class="count">${data.unread > 99 ? "99+" : data.unread}</span>`);
  bell.setAttribute("aria-label", `Notifications (${data.unread} unread)`);
  bell._items = data.items;
  // Browser notifications: once per notification id, only if the user enabled them.
  if ("Notification" in window && Notification.permission === "granted" && localStorage.getItem("fv_browser_notify") === "1") {
    const shown = shownSet();
    for (const n of data.items.filter((x) => !x.read && !shown.has(x.id)).slice(0, 5)) {
      try { new Notification("Fresh Vibe", { body: n.message, tag: `fv-${n.id}` }); } catch { /* ignore */ }
      shown.add(n.id);
    }
    saveShown(shown);
  }
}

function toggleBell() {
  const wrap = $("#bell-wrap");
  const open = wrap.querySelector(".dropdown");
  if (open) { open.remove(); return; }
  const items = $("#bell")._items || [];
  const dd = document.createElement("div");
  dd.className = "dropdown";
  dd.innerHTML = `<div class="card-head"><h3>Notifications</h3>${items.some((i) => !i.read) ? '<button class="btn btn-ghost btn-sm" id="read-all">Mark all read</button>' : ""}</div>
    <div class="items">${items.length ? items.map((n) => `<div class="notif ${n.read ? "read" : ""}" data-id="${n.id}" data-product="${n.product_id}" tabindex="0">
      <span class="sev sev-${n.severity}"></span><div><div style="font-weight:550">${esc(n.message)}</div><div class="tiny muted">${esc(timeAgo(n.created_at))}</div></div></div>`).join("")
      : '<div class="empty small">No expiry alerts. Nice and fresh.</div>'}</div>`;
  wrap.appendChild(dd);
  dd.querySelector("#read-all")?.addEventListener("click", async () => { await api.post("/api/notifications/read-all"); dd.remove(); refreshNotifications(); });
  dd.querySelectorAll(".notif").forEach((el) => el.addEventListener("click", async () => {
    await api.post(`/api/notifications/${el.dataset.id}/read`).catch(() => {});
    dd.remove(); refreshNotifications();
    location.hash = `#/inventory?id=${el.dataset.product}`;
  }));
  setTimeout(() => document.addEventListener("click", function close(e) {
    if (!wrap.contains(e.target)) { dd.remove(); document.removeEventListener("click", close); }
  }), 0);
}

// ------------------------------------------------------------------ auth
let loginPromise = null;
function askLogin() {
  if (loginPromise) return loginPromise;
  loginPromise = new Promise((resolve) => {
    modal(`<form id="login"><div class="card-head"><h2>Sign in to your camera bridge</h2></div>
      <div class="card-body stack"><p class="muted">This Fresh Vibe bridge is protected with an access token (API_TOKEN in its .env file).</p>
      <label class="field"><span>Access token</span><input name="token" type="password" autocomplete="current-password" required></label>
      <div id="login-err"></div></div>
      <div class="card-foot"><button type="button" class="btn" data-close>Cancel</button><button class="btn btn-primary">Sign in</button></div></form>`,
    { onMount: (m, close) => {
      m.querySelector("[data-close]").onclick = () => { close(); loginPromise = null; resolve(false); };
      m.querySelector("#login").onsubmit = async (e) => {
        e.preventDefault();
        const token = e.target.token.value.trim();
        try {
          await api.post("/api/auth/login", { token }, { retryAuth: false });
          setToken(token);
          close(); loginPromise = null; resolve(true);
          refreshCameraBadge(); refreshNotifications();
        } catch (err) {
          m.querySelector("#login-err").innerHTML = `<div class="callout err">${icon("xCircle")}<div>${esc(err.message)}</div></div>`;
        }
      };
    } });
  });
  return loginPromise;
}

// ------------------------------------------------------------------ boot
async function boot() {
  renderNav();
  onAuthRequired(askLogin);
  $("#bell").addEventListener("click", toggleBell);
  window.addEventListener("hashchange", route);
  try {
    const s = await api.get("/api/settings");
    setCategories(s.categories);
  } catch (err) {
    if (err.code !== "auth_required") toast("Backend not reachable", { type: "err", text: err.hint || err.message, timeout: 9000 });
  }
  route();
  refreshCameraBadge();
  refreshNotifications();
  setInterval(refreshCameraBadge, 10000);
  setInterval(refreshNotifications, 60000);
}
export { refreshNotifications };
boot();
