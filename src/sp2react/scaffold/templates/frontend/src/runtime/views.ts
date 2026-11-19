// Legacy list views as the new list page shows them: same columns, order and row limit.

export interface ViewDef {
  fields: string[];
  orderby?: string;
  top?: number;
}

// SharePoint's "Title (linked to item)" columns are the Title field; the list page links it to the item
const TITLE_ALIASES = /^(LinkTitle|LinkTitleNoMenu|LinkTitle2)$/;

export function columnName(name: string): string {
  return TITLE_ALIASES.test(name) ? "Title" : name;
}

/** <OrderBy> of a view's CAML (ViewQuery or a whole view XML) as an OData $orderby, or undefined. */
export function orderbyFromCaml(xml?: string | null): string | undefined {
  if (!xml) return undefined;
  const ob = xml.match(/<OrderBy[^>]*>([\s\S]*?)<\/OrderBy>/i);
  if (!ob) return undefined;
  const parts = Array.from(ob[1].matchAll(/<FieldRef\b([^>]*)\/?>/gi)).map((m) => {
    const name = m[1].match(/\bName\s*=\s*"([^"]+)"/i)?.[1];
    const asc = m[1].match(/\bAscending\s*=\s*"(\w+)"/i)?.[1];
    return name ? `${columnName(name)}${asc && asc.toUpperCase() === "FALSE" ? " desc" : ""}` : "";
  }).filter(Boolean);
  return parts.length ? parts.join(",") : undefined;
}

export interface SpecView { fields?: string[]; query?: string | null; rowLimit?: number | null; default?: boolean }

/** The view the list page opens with: the legacy default view, else AllItems, else the first view. */
export function listPageView(views: Record<string, SpecView> | undefined, fieldNames: string[]): ViewDef {
  const all = views ?? {};
  const v = Object.values(all).find((x) => x?.default) ?? all.AllItems ?? Object.values(all)[0];
  const fields = (v?.fields?.length ? v.fields : fieldNames.slice(0, 6)).map(columnName);
  return {
    fields: fields.filter((f, i) => fields.indexOf(f) === i),
    orderby: orderbyFromCaml(v?.query) ?? "ID",   // a view without <OrderBy> lists items by ID, oldest first
    top: v?.rowLimit ?? 30,
  };
}
