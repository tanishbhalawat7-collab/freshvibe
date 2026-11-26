// All network access goes to the Fresh Vibe backend (same origin by default).
// The browser NEVER contacts the ESP32-CAM directly (no mixed content, no CORS).

const BASE = ((window.FRESHVIBE_CONFIG || {}).API_BASE || "").replace(/\/+$/, "");
const TOKEN_KEY = "fv_token";

export class ApiError extends Error {
  constructor(status, body) {
    const e = (body && body.error) || {};
    super(e.message || `Request failed (${status})`);
    this.status = status;
    this.code = e.code || (status === 0 ? "network" : "error");
    this.hint = e.hint || "";
    this.details = e.details || null;
  }
}

let authHandler = null;
export function onAuthRequired(fn) { authHandler = fn; }

export function url(path) { return BASE + path; }

export function setToken(t) {
  try { t ? sessionStorage.setItem(TOKEN_KEY, t) : sessionStorage.removeItem(TOKEN_KEY); } catch { /* private mode */ }
}
function token() { try { return sessionStorage.getItem(TOKEN_KEY); } catch { return null; } }

export async function request(path, { method = "GET", json, form, timeout = 60000, raw = false, retryAuth = true } = {}) {
  const headers = { "X-Requested-With": "FreshVibe" };
  const t = token();
  if (t) headers.Authorization = `Bearer ${t}`;
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  let res;
  try {
    res = await fetch(url(path), { method, headers, body, credentials: BASE ? "include" : "same-origin", signal: ctrl.signal });
  } catch (err) {
    clearTimeout(timer);
    const msg = err.name === "AbortError"
      ? `The backend did not answer within ${Math.round(timeout / 1000)} s.`
      : "Cannot reach the Fresh Vibe backend.";
    throw new ApiError(0, { error: { code: err.name === "AbortError" ? "timeout" : "network", message: msg,
      hint: BASE ? `Check that ${BASE} is running and that this site is listed in CORS_ORIGINS.` : "Is the backend (python -m app) still running?" } });
  }
  clearTimeout(timer);
  if (res.status === 401 && retryAuth && authHandler) {
    const ok = await authHandler();
    if (ok) return request(path, { method, json, form, timeout, raw, retryAuth: false });
  }
  if (raw) {
    if (!res.ok) throw new ApiError(res.status, await res.json().catch(() => null));
    return res;
  }
  const data = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}

export const api = {
  get: (p, o) => request(p, o),
  post: (p, json, o) => request(p, { ...o, method: "POST", json }),
  put: (p, json, o) => request(p, { ...o, method: "PUT", json }),
  del: (p, o) => request(p, { ...o, method: "DELETE" }),
  postForm: (p, form, o) => request(p, { ...o, method: "POST", form }),
};
