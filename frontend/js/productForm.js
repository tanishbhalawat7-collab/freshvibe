import { $, $$, conf, esc } from "./ui.js";

let CATEGORIES = ["Dairy", "Bakery", "Beverages", "Snacks", "Grocery", "Frozen", "Fruits & Vegetables", "Meat & Seafood",
  "Condiments & Sauces", "Medicine", "Personal Care", "Household", "Baby Care", "Pet Care", "Other"];
export function setCategories(c) { if (Array.isArray(c) && c.length) CATEGORIES = c; }
export function categories() { return CATEGORIES; }

function dateField(key, label, value, precision, cls, extra) {
  const prec = precision || (value && value.length === 7 ? "month" : "day");
  return `<label class="field ${cls}"><span>${label} ${extra}</span>
    <div class="input-group">
      <input name="${key}" type="${prec === "month" ? "month" : "date"}" value="${esc(value || "")}" placeholder="${prec === "month" ? "YYYY-MM" : "YYYY-MM-DD"}">
      <select name="${key}_precision" aria-label="${label} precision" style="width:auto">
        <option value="day" ${prec === "day" ? "selected" : ""}>Exact day</option>
        <option value="month" ${prec === "month" ? "selected" : ""}>Month only</option>
      </select>
    </div></label>`;
}

/** values: product-like object; meta: {uncertain:[], confidence:{field:0..1}, threshold} */
export function productFormHtml(values = {}, meta = {}) {
  const u = new Set(meta.uncertain || []);
  const c = meta.confidence || {};
  const thr = meta.threshold || 0.75;
  const cls = (k) => (u.has(k) ? "uncertain" : "");
  const cf = (k) => (c[k] != null && values[k] ? conf(c[k], thr) : "");
  const input = (k, label, attrs = "") => `<label class="field ${cls(k)}"><span>${label} ${cf(k)}</span><input name="${k}" value="${esc(values[k] ?? "")}" ${attrs}></label>`;
  return `<div class="form-grid">
    ${input("name", "Product name", 'required maxlength="255" autocomplete="off"')}
    ${input("brand", "Brand", 'maxlength="255" autocomplete="off"')}
    <label class="field ${cls("category")}"><span>Category ${cf("category")}</span>
      <select name="category"><option value="">— Select —</option>${CATEGORIES.map((x) => `<option ${x === values.category ? "selected" : ""}>${esc(x)}</option>`).join("")}</select></label>
    ${input("barcode", "Barcode", 'maxlength="64" inputmode="numeric" autocomplete="off"')}
    ${dateField("mfg_date", "Manufacturing date", values.mfg_date, values.mfg_precision, cls("mfg_date"), cf("mfg_date"))}
    ${dateField("expiry_date", "Expiry date", values.expiry_date, values.expiry_precision, cls("expiry_date"), cf("expiry_date"))}
    ${input("batch_no", "Batch / lot no.", 'maxlength="64" autocomplete="off"')}
    <label class="field"><span>Quantity</span><input name="quantity" type="number" min="1" max="9999" value="${esc(values.quantity || 1)}"></label>
    <label class="field full"><span>Notes</span><textarea name="notes" maxlength="2000">${esc(values.notes || "")}</textarea></label>
  </div>`;
}

export function wireProductForm(root) {
  $$("select[name$=_precision]", root).forEach((sel) => {
    sel.onchange = () => {
      const input = root.querySelector(`input[name=${sel.name.replace("_precision", "")}]`);
      const v = input.value;
      if (sel.value === "month") { input.type = "month"; input.value = v ? v.slice(0, 7) : ""; input.placeholder = "YYYY-MM"; }
      else { input.type = "date"; input.value = v && v.length === 7 ? `${v}-01` : v; input.placeholder = "YYYY-MM-DD"; }
    };
  });
}

export function readProductForm(root) {
  const v = (n) => { const el = root.querySelector(`[name=${n}]`); return el ? el.value.trim() : ""; };
  const data = {
    name: v("name") || null, brand: v("brand") || null, category: v("category") || null,
    barcode: v("barcode") || null, batch_no: v("batch_no") || null, notes: v("notes") || null,
    quantity: parseInt(v("quantity") || "1", 10) || 1,
  };
  for (const k of ["mfg_date", "expiry_date"]) {
    const prec = v(`${k}_precision`) || "day";
    let val = v(k);
    if (val && prec === "month") val = val.slice(0, 7);
    if (val && !/^\d{4}-\d{2}(-\d{2})?$/.test(val)) throw new Error(`${k === "mfg_date" ? "Manufacturing" : "Expiry"} date must be YYYY-MM-DD or YYYY-MM.`);
    data[k] = val || null;
    data[k.replace("_date", "_precision")] = val ? prec : null;
  }
  if (!data.name && !data.barcode) throw new Error("Enter at least a product name or a barcode.");
  return data;
}

export function focusFirstUncertain(root) {
  const el = $(".field.uncertain input, .field.uncertain select", root);
  if (el) el.focus();
}
