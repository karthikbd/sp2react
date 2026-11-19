// Field values as forms edit them and the API stores them.

export interface Ref { id: number; title?: string | null }

/** The value of a lookup control from the selected option ids: one {id,title}, or a list for multi-value lookups. */
export function lookupValue(options: Ref[], selectedIds: (string | number)[], multi: boolean): Ref | Ref[] | null {
  const picked = selectedIds
    .map((s) => options.find((o) => String(o.id) === String(s)))
    .filter((o): o is Ref => !!o)
    .map((o) => ({ id: o.id, title: o.title ?? null }));
  if (multi) return picked;
  return picked[0] ?? null;
}

/** Ids currently selected in a lookup control (value can be one ref, a list of refs, or raw ids). */
export function selectedIds(value: unknown): string[] {
  const one = (v: any) => (v && typeof v === "object" ? v.id : v);
  if (Array.isArray(value)) return value.map(one).filter((x) => x !== null && x !== undefined).map(String);
  const v = one(value);
  return v === null || v === undefined || v === "" ? [] : [String(v)];
}

const pad = (n: number) => String(n).padStart(2, "0");

/** A stored date-time (UTC, "...Z" or with an offset) as the value of <input type="datetime-local"> in the browser's zone. */
export function toLocalInput(v: unknown): string {
  if (!v) return "";
  const s = String(v);
  if (!/[zZ]$|[+-]\d{2}:?\d{2}$/.test(s)) return s.slice(0, 16);      // no zone stored: show as written
  const d = new Date(s);
  if (Number.isNaN(d.getTime())) return "";
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/** The browser-local value of a datetime-local input as UTC ("YYYY-MM-DDTHH:MM:SSZ"), as SharePoint returns it. */
export function fromLocalInput(local: string): string | null {
  if (!local) return null;
  const d = new Date(local);           // no zone in the string: the browser's local time
  return Number.isNaN(d.getTime()) ? null : d.toISOString().replace(/\.\d{3}Z$/, "Z");
}

export interface UrlValue { url: string; description?: string | null }

/** Hyperlink values: {url, description}; older data may hold the URL alone. */
export function urlValue(v: unknown): UrlValue | null {
  if (!v) return null;
  if (typeof v === "string") return { url: v, description: null };
  const o = v as any;
  const url = o.url ?? o.Url;
  return url ? { url, description: o.description ?? o.Description ?? null } : null;
}

/** Managed metadata: {label, term_id}; the label is what SharePoint showed. */
export function termLabel(v: unknown): string {
  if (!v || typeof v !== "object") return v ? String(v) : "";
  const o = v as any;
  if (Array.isArray(o)) return o.map(termLabel).filter(Boolean).join("; ");
  return o.label ?? o.Label ?? o.term_id ?? o.TermGuid ?? "";
}
