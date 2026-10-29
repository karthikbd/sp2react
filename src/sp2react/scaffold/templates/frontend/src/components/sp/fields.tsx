// Field controls that render like SharePoint 2013/2016 list form controls.
// `title` attributes match SharePoint's ("<Label>" / "<Label> Required Field") so parity tests can
// use the same selectors the legacy jQuery used.
import { useEffect, useRef, useState } from "react";
import { api } from "../../api";
import { formatValue } from "../../runtime/format";
import type { Field } from "../../runtime/spec";

export interface Option {
  id: number;
  title: string;
  [k: string]: any;
}

interface Props {
  field: Field;
  value: any;
  onChange: (v: any) => void;
  onBlur?: () => void;
  options?: Option[];
  disabled?: boolean;
  required?: boolean;
}

function PeoplePicker({ field, value, onChange, onBlur, disabled, required }: Props) {
  const multi = !!field.multi;
  const selected: any[] = multi ? (value ?? []) : value ? [value] : [];
  const [text, setText] = useState("");
  const [hits, setHits] = useState<any[]>([]);
  const timer = useRef<number | undefined>(undefined);
  useEffect(() => {
    window.clearTimeout(timer.current);
    if (text.trim().length < 2) { setHits([]); return; }
    timer.current = window.setTimeout(() => { api.users(text.trim()).then(setHits).catch(() => setHits([])); }, 250);
  }, [text]);
  const pick = (u: any) => {
    const v = { id: u.id, login: u.login, title: u.title };
    onChange(multi ? [...selected.filter((s) => s.id !== u.id), v] : v);
    setText("");
    setHits([]);
  };
  return (
    <div className={`sp-peoplepicker${disabled ? " is-disabled" : ""}`} title={`${field.label}${required ? " Required Field" : ""}`}>
      {selected.map((s) => (
        <span key={s.id} className="ms-entity-resolved">
          {s.title}
          {!disabled && <button type="button" aria-label={`Remove ${s.title}`} onClick={() => onChange(multi ? selected.filter((x) => x.id !== s.id) : null)}>×</button>}
        </span>
      ))}
      {!disabled && (multi || selected.length === 0) && (
        <input className="ms-inputuserfield" value={text} onChange={(e) => setText(e.target.value)} onBlur={onBlur}
               placeholder="Enter a name or email address..." aria-label={field.label} />
      )}
      {hits.length > 0 && (
        <ul className="sp-picker-hits" role="listbox">
          {hits.map((h) => <li key={h.id} role="option" aria-selected={false} onMouseDown={() => pick(h)}>{h.title} <span className="sp-muted">{h.email}</span></li>)}
        </ul>
      )}
    </div>
  );
}

export function FieldControl(props: Props) {
  const { field, value, onChange, onBlur, options, disabled, required } = props;
  const title = `${field.label}${required ? " Required Field" : ""}`;
  const common = { title, disabled, onBlur, id: `fld-${field.name}`, name: field.name };
  switch (field.type) {
    case "note":
      return <textarea {...common} className="ms-long" rows={field.lines ?? 6} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
    case "choice":
      if (field.format === "radio")
        return (
          <span className="sp-radios" title={title}>
            {(field.choices ?? []).map((c) => (
              <label key={c}><input type="radio" name={field.name} disabled={disabled} checked={value === c} onChange={() => onChange(c)} /> {c}</label>
            ))}
          </span>
        );
      return (
        <select {...common} value={value ?? ""} onChange={(e) => onChange(e.target.value || null)}>
          {(!required || field.default === undefined) && <option value=""></option>}
          {(field.choices ?? []).map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      );
    case "multichoice": {
      const vals: string[] = value ?? [];
      return (
        <span className="sp-checks" title={title}>
          {(field.choices ?? []).map((c) => (
            <label key={c}>
              <input type="checkbox" disabled={disabled} checked={vals.includes(c)}
                     onChange={(e) => onChange(e.target.checked ? [...vals, c] : vals.filter((x) => x !== c))} /> {c}
            </label>
          ))}
        </span>
      );
    }
    case "lookup": {
      const id = value && typeof value === "object" ? value.id : value ?? "";
      return (
        <select {...common} value={id ?? ""} onChange={(e) => {
          const o = (options ?? []).find((x) => String(x.id) === e.target.value);
          onChange(o ? { id: o.id, title: o.title } : null);
        }}>
          {!required && <option value="">(None)</option>}
          {required && !id && <option value=""></option>}
          {(options ?? []).map((o) => <option key={o.id} value={o.id}>{o.title}</option>)}
        </select>
      );
    }
    case "user":
      return <PeoplePicker {...props} />;
    case "date":
      return <input {...common} type="date" className="ms-input" value={value ?? ""} onChange={(e) => onChange(e.target.value || null)} />;
    case "datetime":
      return <input {...common} type="datetime-local" className="ms-input" value={value ? String(value).slice(0, 16) : ""} onChange={(e) => onChange(e.target.value || null)} />;
    case "number":
    case "currency":
      return (
        <span className="sp-number">
          {field.type === "currency" && <span className="sp-currency">$</span>}
          <input {...common} type="text" inputMode="decimal" className="ms-input" size={11} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />
        </span>
      );
    case "boolean":
      return <input {...common} type="checkbox" checked={!!value} onChange={(e) => onChange(e.target.checked)} />;
    case "calculated":
      return <span>{formatValue(field, value)}</span>;
    default:
      return <input {...common} type="text" className="ms-long" maxLength={field.max_length} value={value ?? ""} onChange={(e) => onChange(e.target.value)} />;
  }
}
