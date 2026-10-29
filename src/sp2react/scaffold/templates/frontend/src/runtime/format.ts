// SharePoint (en-US) display formats, so read-only values look the same as before.
import type { Field } from "./spec";

export function formatDate(v: unknown, withTime = false): string {
  if (!v) return "";
  const s = String(v);
  const d = /^\d{4}-\d{2}-\d{2}$/.test(s) ? new Date(`${s}T00:00:00`) : new Date(s);
  if (Number.isNaN(d.getTime())) return s;
  const date = `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`;
  if (!withTime) return date;
  let h = d.getHours();
  const ap = h >= 12 ? "PM" : "AM";
  h = h % 12 || 12;
  return `${date} ${h}:${String(d.getMinutes()).padStart(2, "0")} ${ap}`;
}

export function formatCurrency(v: unknown): string {
  if (v === null || v === undefined || v === "") return "";
  const n = typeof v === "number" ? v : parseFloat(String(v).replace(/[$,]/g, ""));
  return Number.isNaN(n) ? String(v) : n.toLocaleString("en-US", { style: "currency", currency: "USD" });
}

export function formatValue(f: Field | undefined, v: any): string {
  if (v === null || v === undefined || v === "") return "";
  if (Array.isArray(v)) return v.map((x) => formatValue(f, x)).join("; ");
  if (typeof v === "object") return v.title ?? String(v.id ?? "");
  if (!f) return String(v);
  switch (f.type) {
    case "boolean": return v ? "Yes" : "No";
    case "currency": return formatCurrency(v);
    case "number": return typeof v === "number" ? v.toLocaleString("en-US") : String(v);
    case "date": return formatDate(v);
    case "datetime": return formatDate(v, true);
    default: return String(v);
  }
}
