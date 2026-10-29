// Generic SharePoint list form (NewForm / EditForm / DispForm) driven by the screen spec.
// All behaviour that used to live in jQuery comes from spec rules evaluated by runtime/rules.ts;
// the API enforces the same rules again on save.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { api, ApiError } from "../../api";
import { HANDLERS } from "../../custom";
import { formatValue } from "../../runtime/format";
import * as R from "../../runtime/rules";
import { rulesForList, type Field, type Mode, type Spec, type Values } from "../../runtime/spec";
import { useUser } from "../../runtime/user";
import { Banner } from "./Banner";
import { FieldControl, type Option } from "./fields";
import { LegacyHtml } from "./LegacyHtml";

interface Props {
  spec: Spec;
  mode: Mode;
  id?: string;
}

export function ListForm({ spec, mode, id }: Props) {
  const list = spec.screen.list as string;
  const lst = spec.lists[list];
  const fields: Field[] = lst.fields;
  const rules = useMemo(() => rulesForList(spec, list), [spec, list]);
  const { user } = useUser();
  const nav = useNavigate();
  const [params] = useSearchParams();
  const source = params.get("Source");
  const [values, setValues] = useState<Values>({});
  const [original, setOriginal] = useState<Values>({});
  const [options, setOptions] = useState<Record<string, Option[]>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loaded, setLoaded] = useState(false);
  const [files, setFiles] = useState<File[]>([]);
  const etag = useRef<string | undefined>(undefined);
  const route = spec.screen.route;

  const ctx: R.Ctx = { mode, values, original, user };
  const states = useMemo(() => Object.fromEntries(fields.map((f) => [f.name, R.fieldState(f, rules, ctx)])), [fields, rules, values, original, user, mode]);
  const banners = useMemo(() => R.banners(rules, ctx), [rules, values, original, user, mode]);

  const goBack = useCallback(() => {
    if (source && source.startsWith("/")) nav(source);
    else nav(route);
  }, [nav, source, route]);

  const loadOptions = useCallback(async (field: Field, current: Values) => {
    const cascade = rules.find((r) => r.kind === "cascade" && r.field === field.name);
    const parentVal = cascade ? current[cascade.params!.parent] : undefined;
    const parentId = parentVal && typeof parentVal === "object" ? parentVal.id : parentVal;
    if (cascade && !parentId) return [];
    return api.lookup(list, field.name, cascade ? parentId : undefined);
  }, [rules, list]);

  // ------------------------------------------------------------------ load
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    (async () => {
      let v: Values;
      if (mode === "new") {
        v = R.defaults(fields, rules, user);
      } else {
        const item = await api.get(list, id as string);
        etag.current = item._etag;
        setOriginal(item);
        v = item;
        if (mode === "edit") {
          const locked = R.lock(rules, { mode, values: item, original: item, user });
          if (locked) {
            window.alert(R.fillTemplate(locked.message ?? "", item));
            const to = (locked.params?.redirect ?? "display") === "display" ? `${route}/display/${id}` : route;
            nav(`${to}${source ? `?Source=${encodeURIComponent(source)}` : ""}`, { replace: true });
            return;
          }
        }
      }
      for (const h of Object.values(HANDLERS)) h.onLoad?.({ mode, values: v, original: mode === "new" ? {} : v, user }, api);
      if (cancelled) return;
      setValues(v);
      if (mode !== "display") {
        const opts: Record<string, Option[]> = {};
        for (const f of fields.filter((x) => x.type === "lookup")) opts[f.name] = await loadOptions(f, v);
        if (!cancelled) setOptions(opts);
      }
      setLoaded(true);
    })().catch((e) => window.alert(e.message));
    return () => { cancelled = true; };
  }, [user, mode, id]);

  // --------------------------------------------------------------- change
  const change = async (field: Field, v: any) => {
    let next = { ...values, [field.name]: v };
    setErrors((e) => ({ ...e, [field.name]: "" }));
    // cascades: children of this field get new options and lose a value that no longer fits
    for (const r of rules.filter((x) => x.kind === "cascade" && x.params?.parent === field.name)) {
      const child = fields.find((f) => f.name === r.field)!;
      const opts = await loadOptions(child, next);
      setOptions((o) => ({ ...o, [child.name]: opts }));
      const cur = next[child.name];
      if (cur && !opts.some((o) => o.id === (typeof cur === "object" ? cur.id : cur))) next = { ...next, [child.name]: null };
    }
    // derived values: copy a column from the selected lookup item
    for (const r of R.rulesFor(rules, "derive", null, mode).filter((x) => x.params?.from_field === field.name)) {
      const opt = (options[field.name] ?? []).find((o) => o.id === (v && typeof v === "object" ? v.id : v));
      next = { ...next, [r.field as string]: opt ? opt[r.params!.column] ?? null : null };
    }
    next = { ...next, ...R.clearHidden(fields, rules, { mode, values: next, original, user }) };
    for (const h of Object.values(HANDLERS)) {
      const patch = h.onChange?.(field.name, { mode, values: next, original, user });
      if (patch) next = { ...next, ...patch };
    }
    setValues(next);
  };

  const blur = async (field: Field) => {
    const r = R.rulesFor(rules, "unique", field.name, mode)[0];
    const v = values[field.name];
    if (!r || R.isEmpty(v)) return;
    const res = await api.unique(list, field.name, String(v), mode === "edit" ? Number(id) : 0);
    setErrors((e) => ({ ...e, [field.name]: res.duplicate_id ? R.fillTemplate(r.message ?? "", { ...values, duplicate_id: res.duplicate_id, id: res.duplicate_id }) : "" }));
  };

  // ----------------------------------------------------------------- save
  const showErrors = (list_: R.RuleError[]) => {
    const alertErr = list_.find((e) => e.presentation === "alert");
    if (alertErr) { window.alert(alertErr.message); return; }
    const inline: Record<string, string> = {};
    for (const e of list_) if (e.field) inline[e.field] = inline[e.field] || e.message;
    setErrors(inline);
    const firstMsg = list_.find((e) => !e.field);
    if (firstMsg) window.alert(firstMsg.message);
  };

  const save = async () => {
    const pending = Object.entries(errors).find(([, m]) => m);
    const errs = R.validate(fields, rules, ctx);
    for (const h of Object.values(HANDLERS)) errs.push(...(h.validate?.(ctx) ?? []));
    if (pending) {
      const r = R.rulesFor(rules, "unique", pending[0], mode)[0];
      if (r) errs.unshift({ field: pending[0], message: pending[1], presentation: r.presentation ?? "inline", rule: r.id });
    }
    if (errs.length) return showErrors(errs);
    for (const c of R.rulesFor(rules, "confirm", null, mode).filter((x) => (x.params?.action ?? "save") === "save" && R.evaluate(x.when, ctx)))
      if (!window.confirm(R.fillTemplate(c.message ?? "", values))) return;
    const payload: Values = { ...values, ...R.setOnSave(rules, ctx) };
    for (const k of ["ID", "Created", "Modified", "Author", "Editor", "_etag", "_version", "Attachments"]) delete payload[k];
    setBusy(true);
    try {
      const saved = mode === "new" ? await api.create(list, payload) : await api.update(list, id as string, payload, etag.current);
      for (const f of files) await api.uploadAttachment(list, saved.ID, f);
      goBack();
    } catch (e) {
      if (e instanceof ApiError && e.status === 422) showErrors(e.body.errors);
      else if (e instanceof ApiError && e.status === 423) { window.alert(e.body.message); nav(`${route}/display/${id}`); }
      else window.alert((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  // --------------------------------------------------------------- render
  const around = (where: "before" | "after") =>
    spec.screen.components
      .filter((c) => c.kind !== "form" && (c.region ?? "before") === where && (!c.props?.modes || c.props.modes.includes(mode)))
      .filter((c) => !c.roles?.length || c.roles.some((g) => user?.groups.includes(g)))
      .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
      .map((c) => c.kind === "banner"
        ? <Banner key={c.id} text={c.props?.text ?? ""} tone={c.props?.tone ?? "info"} />
        : c.kind === "html" ? <LegacyHtml key={c.id} html={c.props?.legacy_html ?? ""} /> : null);

  const toolbar = mode === "display" ? (
    <div className="sp-toolbar">
      <button type="button" className="ms-ButtonHeightWidth" onClick={() => nav(`${route}/edit/${id}${source ? `?Source=${encodeURIComponent(source)}` : ""}`)}>Edit Item</button>
      <button type="button" className="ms-ButtonHeightWidth" onClick={goBack}>Close</button>
    </div>
  ) : (
    <div className="sp-toolbar">
      <button type="button" className="ms-ButtonHeightWidth" disabled={busy || !loaded} onClick={save}>Save</button>
      <button type="button" className="ms-ButtonHeightWidth" disabled={busy} onClick={goBack}>Cancel</button>
    </div>
  );

  if (!loaded) return <div className="sp-loading">Loading...</div>;
  return (
    <div className="sp-listform">
      {around("before")}
      {banners.map((b) => <Banner key={b.id} text={R.fillTemplate(b.message ?? "", values)} />)}
      <table className="ms-formtable" role="presentation">
        <tbody>
          {fields.map((f) => {
            const st = states[f.name];
            if (!st.visible) return null;
            return (
              <tr key={f.name} id={`row-${f.name}`}>
                <td className="ms-formlabel">
                  <h3 className="ms-standardheader">
                    <span className="nobr">{f.label}{st.required && mode !== "display" && <span className="ms-accentText" title="This is a required field."> *</span>}</span>
                  </h3>
                </td>
                <td className="ms-formbody">
                  {mode === "display" ? (
                    <span className="sp-value">{formatValue(f, values[f.name])}</span>
                  ) : (
                    <FieldControl field={f} value={values[f.name]} options={options[f.name]} disabled={st.readonly} required={st.required}
                                  onChange={(v) => change(f, v)} onBlur={() => blur(f)} />
                  )}
                  {f.description && mode !== "display" && <div className="ms-metadata">{f.description}</div>}
                  {errors[f.name] && <span className="ms-formvalidation" role="alert"><br />{errors[f.name]}</span>}
                </td>
              </tr>
            );
          })}
          {lst.attachments && (
            <tr id="row-Attachments">
              <td className="ms-formlabel"><h3 className="ms-standardheader"><span className="nobr">Attachments</span></h3></td>
              <td className="ms-formbody">
                {(original.Attachments ?? []).map((n: string) => (
                  <div key={n}>
                    <a href={api.attachmentUrl(list, id as string, n)}>{n}</a>
                    {mode === "edit" && <button type="button" className="sp-link" onClick={async () => {
                      await api.deleteAttachment(list, id as string, n);
                      setOriginal((o) => ({ ...o, Attachments: (o.Attachments ?? []).filter((x: string) => x !== n) }));
                    }}>Delete</button>}
                  </div>
                ))}
                {mode !== "display" && (
                  <>
                    {files.map((f) => <div key={f.name}>{f.name}</div>)}
                    <input type="file" aria-label="Attach file" onChange={(e) => e.target.files && setFiles((x) => [...x, ...Array.from(e.target.files!)])} />
                  </>
                )}
              </td>
            </tr>
          )}
        </tbody>
      </table>
      {mode !== "new" && original.ID && (
        <div className="sp-itemmeta">
          Created at {formatValue({ name: "Created", label: "Created", type: "datetime" }, original.Created)} by {original.Author?.title ?? ""}
          <br />
          Last modified at {formatValue({ name: "Modified", label: "Modified", type: "datetime" }, original.Modified)} by {original.Editor?.title ?? ""}
        </div>
      )}
      {toolbar}
      {around("after")}
    </div>
  );
}
