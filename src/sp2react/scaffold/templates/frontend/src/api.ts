// Client for the generated FastAPI backend. The OData-style query options are the same ones the
// legacy jQuery sent to /_api, so legacy queries carry over almost verbatim.
import type { User, Values } from "./runtime/spec";

export class ApiError extends Error {
  constructor(public status: number, public body: any) {
    super(body?.message ?? body?.detail ?? `HTTP ${status}`);
  }
}

export interface QueryOptions {
  filter?: string;
  orderby?: string;
  top?: number;
  skip?: number;
  select?: string;
}

const DEV_USER_KEY = "sp2react.devUser";

export function devUser(): string | null {
  try {
    return localStorage.getItem(DEV_USER_KEY);
  } catch {
    return null;
  }
}

export function setDevUser(login: string | null) {
  try {
    if (login) localStorage.setItem(DEV_USER_KEY, login);
    else localStorage.removeItem(DEV_USER_KEY);
  } catch {
    /* storage unavailable */
  }
}

async function request<T>(method: string, url: string, body?: unknown, headers: Record<string, string> = {}): Promise<T> {
  const h: Record<string, string> = { Accept: "application/json", ...headers };
  if (body !== undefined) h["Content-Type"] = "application/json";
  const du = devUser();
  if (du) h["X-User"] = du;
  const r = await fetch(url, { method, headers: h, body: body === undefined ? undefined : JSON.stringify(body), credentials: "include" });
  const text = await r.text();
  const data = text ? JSON.parse(text) : null;
  if (!r.ok) throw new ApiError(r.status, data);
  return data as T;
}

const enc = encodeURIComponent;

export const api = {
  me: () => request<User>("GET", "/api/me"),
  users: (search: string) => request<{ id: number; login: string; title: string; email?: string }[]>("GET", `/api/users?search=${enc(search)}`),
  spec: (screenId: string) => request<any>("GET", `/api/specs/${enc(screenId)}`),

  query: (list: string, o: QueryOptions = {}) => {
    const qs = Object.entries(o)
      .filter(([, v]) => v !== undefined && v !== null && v !== "")
      .map(([k, v]) => `$${k}=${enc(String(v))}`)
      .join("&");
    return request<{ value: Values[]; count: number }>("GET", `/api/lists/${list}/items${qs ? "?" + qs : ""}`);
  },
  get: (list: string, id: number | string) => request<Values>("GET", `/api/lists/${list}/items/${id}`),
  state: (list: string, id: number | string, mode = "edit") =>
    request<{ locked: boolean; message: string | null; redirect: string | null; banners: string[] }>("GET", `/api/lists/${list}/items/${id}/state?mode=${mode}`),
  create: (list: string, values: Values) => request<Values>("POST", `/api/lists/${list}/items`, { values }),
  update: (list: string, id: number | string, values: Values, etag?: string) =>
    request<Values>("PATCH", `/api/lists/${list}/items/${id}`, { values }, etag ? { "If-Match": etag } : {}),
  remove: (list: string, id: number | string) => request<null>("DELETE", `/api/lists/${list}/items/${id}`),
  lookup: (list: string, field: string, parent?: number | null, q = "") =>
    request<{ id: number; title: string; [k: string]: any }[]>(
      "GET",
      `/api/lists/${list}/lookup/${field}?q=${enc(q)}${parent !== undefined && parent !== null ? `&parent=${parent}` : ""}`
    ),
  unique: (list: string, field: string, value: string, exclude = 0) =>
    request<{ duplicate_id: number | null }>("GET", `/api/lists/${list}/unique/${field}?value=${enc(value)}&exclude=${exclude}`),
  attachmentUrl: (list: string, id: number | string, name: string) => `/api/lists/${list}/items/${id}/attachments/${enc(name)}`,
  uploadAttachment: async (list: string, id: number | string, file: File) => {
    const buf = new Uint8Array(await file.arrayBuffer());
    let bin = "";
    for (let i = 0; i < buf.length; i += 0x8000) bin += String.fromCharCode(...buf.subarray(i, i + 0x8000));
    return request("POST", `/api/lists/${list}/items/${id}/attachments`, { name: file.name, content_base64: btoa(bin) });
  },
  deleteAttachment: (list: string, id: number | string, name: string) => request("DELETE", `/api/lists/${list}/items/${id}/attachments/${enc(name)}`),
};

export type Api = typeof api;
