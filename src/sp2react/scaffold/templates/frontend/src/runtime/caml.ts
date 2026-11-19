// A list view's CAML <Where> as a filter in the API's OData subset (the same one the legacy REST calls used).
// Anything this does not understand is reported, so the page can say the filter is not applied rather than
// silently showing other rows.

export interface CamlContext {
  userId?: number | null;      // <UserID /> = the signed-in user
  today?: string;              // <Today /> as YYYY-MM-DD (defaults to the browser's local date)
}

export interface CamlFilter {
  filter?: string;
  unsupported: string[];
}

interface Node { name: string; attrs: Record<string, string>; children: Node[]; text: string }

function parseXml(xml: string): Node {
  const root: Node = { name: "#root", attrs: {}, children: [], text: "" };
  const stack: Node[] = [root];
  const re = /<!\[CDATA\[([\s\S]*?)\]\]>|<(\/?)([A-Za-z_][\w:.-]*)((?:\s+[\w:.-]+\s*=\s*(?:"[^"]*"|'[^']*'))*)\s*(\/?)>|([^<]+)/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(xml))) {
    const top = stack[stack.length - 1];
    if (m[1] !== undefined) { top.text += m[1]; continue; }
    if (m[6] !== undefined) { top.text += decode(m[6]); continue; }
    if (m[2] === "/") {
      if (stack.length > 1 && stack[stack.length - 1].name.toLowerCase() === m[3].toLowerCase()) stack.pop();
      continue;
    }
    const attrs: Record<string, string> = {};
    for (const a of m[4].matchAll(/([\w:.-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')/g)) attrs[a[1].toLowerCase()] = decode(a[2] ?? a[3] ?? "");
    const node: Node = { name: m[3], attrs, children: [], text: "" };
    top.children.push(node);
    if (m[5] !== "/") stack.push(node);
  }
  return root;
}

function decode(s: string): string {
  return s.replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&apos;/g, "'").replace(/&amp;/g, "&");
}

function find(n: Node, name: string): Node | undefined {
  for (const c of n.children) {
    if (c.name.toLowerCase() === name.toLowerCase()) return c;
    const deep = find(c, name);
    if (deep) return deep;
  }
  return undefined;
}

const quote = (s: string) => `'${s.replace(/'/g, "''")}'`;
const field = (name: string) => (/^LinkTitle(NoMenu|2)?$/.test(name) ? "Title" : name);
const OPS: Record<string, string> = { eq: "eq", neq: "ne", gt: "gt", geq: "ge", lt: "lt", leq: "le" };

function localToday(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export function camlWhereToOData(xml: string | null | undefined, ctx: CamlContext = {}): CamlFilter {
  const unsupported: string[] = [];
  if (!xml) return { unsupported };
  const where = find(parseXml(xml), "Where");
  if (!where) return { unsupported };

  function value(v: Node | undefined, ref: Node): string | null {
    if (!v) { unsupported.push("missing <Value>"); return null; }
    const type = (v.attrs.type || "Text").toLowerCase();
    const special = v.children[0]?.name.toLowerCase();
    if (special === "userid") {
      if (ctx.userId === undefined || ctx.userId === null) { unsupported.push("<UserID /> before the user is known"); return null; }
      return String(ctx.userId);
    }
    if (special === "today") {
      const offset = Number(v.children[0].attrs.offsetdays ?? v.children[0].attrs.offset ?? 0) || 0;
      const base = new Date(`${ctx.today ?? localToday()}T00:00:00Z`);
      base.setUTCDate(base.getUTCDate() + offset);
      return `datetime'${base.toISOString().slice(0, 10)}'`;
    }
    if (special) { unsupported.push(`<${v.children[0].name}>`); return null; }
    const text = v.text.trim();
    switch (type) {
      case "integer": case "number": case "counter": case "currency": case "lookup":
        if (type === "lookup" && (ref.attrs.lookupid || "").toUpperCase() !== "TRUE") return quote(text);
        return /^-?\d+(\.\d+)?$/.test(text) ? text : (unsupported.push(`${type} value '${text}'`), null);
      case "boolean":
        return text === "1" || text.toLowerCase() === "true" ? "true" : "false";
      case "datetime":
        return `datetime'${text.replace(/Z$/, "")}'`;
      default:
        return quote(text);
    }
  }

  function path(ref: Node, v: Node | undefined): string {
    const name = field(ref.attrs.name ?? "");
    const type = (v?.attrs.type || "").toLowerCase();
    const isId = (ref.attrs.lookupid || "").toUpperCase() === "TRUE" || v?.children[0]?.name.toLowerCase() === "userid";
    if (isId) return `${name}/Id`;
    if (type === "user" || type === "lookup") return `${name}/Title`;
    return name;
  }

  function cond(n: Node): string | null {
    const op = n.name.toLowerCase();
    const parts = n.children.filter((c) => !/^(fieldref|value|values)$/i.test(c.name));
    if (op === "and" || op === "or") {
      const subs = parts.map(cond);
      if (subs.some((s) => s === null) || subs.length < 2) return null;
      return `(${subs.join(` ${op} `)})`;
    }
    const ref = n.children.find((c) => c.name.toLowerCase() === "fieldref");
    if (!ref?.attrs.name) { unsupported.push(`<${n.name}> without a FieldRef`); return null; }
    const v = n.children.find((c) => c.name.toLowerCase() === "value");
    if (op === "isnull") return `${path(ref, v)} eq null`;
    if (op === "isnotnull") return `${path(ref, v)} ne null`;
    if (op in OPS || op === "contains" || op === "beginswith") {
      const val = value(v, ref);
      if (val === null) return null;
      const p = path(ref, v);
      if (op === "contains") return `substringof(${val}, ${p})`;
      if (op === "beginswith") return `startswith(${p}, ${val})`;
      return `${p} ${OPS[op]} ${val}`;
    }
    if (op === "in") {
      const vals = (n.children.find((c) => c.name.toLowerCase() === "values")?.children ?? []).map((x) => value(x, ref));
      if (!vals.length || vals.some((x) => x === null)) return null;
      const p = path(ref, n.children.find((c) => c.name.toLowerCase() === "values")?.children[0]);
      return `(${vals.map((x) => `${p} eq ${x}`).join(" or ")})`;
    }
    unsupported.push(`<${n.name}>`);
    return null;
  }

  const top = where.children[0];
  if (!top) return { unsupported };
  const f = cond(top);
  if (f === null) return { unsupported: unsupported.length ? unsupported : [`<${top.name}>`] };
  return { filter: f.startsWith("(") && f.endsWith(")") && top.name.toLowerCase() !== "in" ? f.slice(1, -1) : f, unsupported };
}
