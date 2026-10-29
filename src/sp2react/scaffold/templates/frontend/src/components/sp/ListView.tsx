// A list view (AllItems.aspx / list view web part): same columns, order and row limit as the legacy view.
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { formatValue } from "../../runtime/format";
import type { Field } from "../../runtime/spec";

export interface ViewDef {
  fields: string[];
  orderby?: string;
  top?: number;
}

export function parseViewXml(xml?: string | null): Partial<ViewDef> {
  if (!xml) return {};
  const fields = Array.from(xml.matchAll(/<ViewFields>([\s\S]*?)<\/ViewFields>/g)).flatMap((m) =>
    Array.from(m[1].matchAll(/FieldRef\s+Name="([^"]+)"/g)).map((x) => x[1].replace(/^LinkTitle(NoMenu)?$/, "Title")));
  const ob = xml.match(/<OrderBy>([\s\S]*?)<\/OrderBy>/);
  const orderby = ob ? Array.from(ob[1].matchAll(/FieldRef\s+Name="([^"]+)"(?:\s+Ascending="(\w+)")?/g))
    .map((x) => `${x[1]}${x[2] && x[2].toUpperCase() === "FALSE" ? " desc" : ""}`).join(",") : undefined;
  const rl = xml.match(/<RowLimit[^>]*>(\d+)<\/RowLimit>/);
  return { fields: fields.length ? fields : undefined, orderby, top: rl ? Number(rl[1]) : undefined };
}

export function ListView({ list, fields, view, route, showNew = true, title }: {
  list: string; fields: Field[]; view: ViewDef; route?: string; showNew?: boolean; title?: string | null;
}) {
  const [rows, setRows] = useState<any[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => {
    api.query(list, { orderby: view.orderby, top: view.top ?? 30 }).then((r) => setRows(r.value)).catch((e) => setErr(e.message));
  }, [list, view.orderby, view.top]);
  const byName = Object.fromEntries(fields.map((f) => [f.name, f]));
  const sysLabel: Record<string, string> = { Created: "Created", Modified: "Modified", Author: "Created By", Editor: "Modified By", ID: "ID" };
  return (
    <div className="sp-listview">
      {title && <h2 className="ms-webpart-titleText">{title}</h2>}
      {showNew && route && <div className="sp-newitem"><Link to={`${route}/new`}>+ new item</Link></div>}
      {err && <div className="ms-formvalidation">{err}</div>}
      <table className="ms-listviewtable">
        <thead><tr>{view.fields.map((n) => <th key={n}>{byName[n]?.label ?? sysLabel[n] ?? n}</th>)}</tr></thead>
        <tbody>
          {rows === null ? <tr><td colSpan={view.fields.length}>Loading...</td></tr> :
            rows.length === 0 ? <tr><td colSpan={view.fields.length}>There are no items to show in this view.</td></tr> :
              rows.map((r) => (
                <tr key={r.ID}>
                  {view.fields.map((n) => (
                    <td key={n}>
                      {n === "Title" && route ? <Link to={`${route}/display/${r.ID}`}>{r.Title}</Link> :
                        formatValue(byName[n] ?? (n === "Created" || n === "Modified" ? { name: n, label: n, type: "datetime" } : undefined), r[n])}
                    </td>
                  ))}
                </tr>
              ))}
        </tbody>
      </table>
    </div>
  );
}
