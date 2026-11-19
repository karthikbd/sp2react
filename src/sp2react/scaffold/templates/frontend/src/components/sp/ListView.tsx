// A list view (AllItems.aspx / list view web part): same columns, filter, order and row limit as the legacy view,
// with SharePoint's page-by-page navigation.
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { camlWhereToOData } from "../../runtime/caml";
import { formatValue } from "../../runtime/format";
import type { Field } from "../../runtime/spec";
import { useUser } from "../../runtime/user";
import { urlValue } from "../../runtime/values";
import { columnName, orderbyFromCaml, type ViewDef } from "../../runtime/views";

export type { ViewDef };

export function parseViewXml(xml?: string | null): Partial<ViewDef> {
  if (!xml) return {};
  const fields = Array.from(xml.matchAll(/<ViewFields>([\s\S]*?)<\/ViewFields>/g)).flatMap((m) =>
    Array.from(m[1].matchAll(/FieldRef\s+Name="([^"]+)"/g)).map((x) => columnName(x[1])));
  const rl = xml.match(/<RowLimit[^>]*>(\d+)<\/RowLimit>/);
  return { fields: fields.length ? fields : undefined, orderby: orderbyFromCaml(xml), top: rl ? Number(rl[1]) : undefined, where: xml };
}

export function ListView({ list, fields, view, route, showNew = true, title }: {
  list: string; fields: Field[]; view: ViewDef; route?: string; showNew?: boolean; title?: string | null;
}) {
  const { user } = useUser();
  const [rows, setRows] = useState<any[] | null>(null);
  const [count, setCount] = useState(0);
  const [skip, setSkip] = useState(0);
  const [err, setErr] = useState<string | null>(null);
  const top = view.top ?? 30;
  const needsUser = !!view.where && /<UserID\b/i.test(view.where);
  const where = useMemo(() => camlWhereToOData(view.where, { userId: user?.id }), [view.where, user?.id]);
  useEffect(() => {
    if (needsUser && !user) return;               // <UserID /> filters wait for the signed-in user
    setRows(null);
    api.query(list, { filter: where.filter, orderby: view.orderby, top, skip })
      .then((r) => { setRows(r.value); setCount(r.count); })
      .catch((e) => setErr(e.message));
  }, [list, where.filter, view.orderby, top, skip, needsUser, user]);
  useEffect(() => setSkip(0), [list, where.filter, view.orderby]);
  const byName = Object.fromEntries(fields.map((f) => [f.name, f]));
  const sysLabel: Record<string, string> = { Created: "Created", Modified: "Modified", Author: "Created By", Editor: "Modified By", ID: "ID" };
  const cols = view.fields.map(columnName);
  const last = Math.min(skip + top, count);
  return (
    <div className="sp-listview">
      {title && <h2 className="ms-webpart-titleText">{title}</h2>}
      {showNew && route && <div className="sp-newitem"><Link to={`${route}/new`}>+ new item</Link></div>}
      {err && <div className="ms-formvalidation">{err}</div>}
      {where.unsupported.length > 0 && (
        <div className="ms-formvalidation">This view's filter could not be applied ({where.unsupported.join(", ")}): all items are shown.</div>
      )}
      <table className="ms-listviewtable">
        <thead><tr>{cols.map((n) => <th key={n}>{byName[n]?.label ?? sysLabel[n] ?? n}</th>)}</tr></thead>
        <tbody>
          {rows === null ? <tr><td colSpan={cols.length}>Loading...</td></tr> :
            rows.length === 0 ? <tr><td colSpan={cols.length}>There are no items to show in this view.</td></tr> :
              rows.map((r) => (
                <tr key={r.ID}>
                  {cols.map((n) => {
                    const f = byName[n];
                    const u = f?.type === "url" ? urlValue(r[n]) : null;
                    return (
                      <td key={n}>
                        {n === "Title" && route ? <Link to={`${route}/display/${r.ID}`}>{r.Title}</Link> :
                          u ? <a href={/^(https?:|mailto:|\/)/i.test(u.url) ? u.url : "#"}>{u.description || u.url}</a> :
                            formatValue(f ?? (n === "Created" || n === "Modified" ? { name: n, label: n, type: "datetime" } : undefined), r[n])}
                      </td>
                    );
                  })}
                </tr>
              ))}
        </tbody>
      </table>
      {count > top && (
        <div className="sp-paging">
          {skip > 0 && <button type="button" onClick={() => setSkip(Math.max(0, skip - top))} aria-label="Previous">&#9664;</button>}
          <span> {skip + 1} - {last} </span>
          {last < count && <button type="button" onClick={() => setSkip(skip + top)} aria-label="Next">&#9654;</button>}
        </div>
      )}
    </div>
  );
}
