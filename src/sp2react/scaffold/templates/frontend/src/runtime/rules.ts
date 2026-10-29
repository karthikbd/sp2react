// Spec rule engine (browser side). Mirrors backend/app/rules.py; both run the same test vectors.
import type { Condition, Field, Mode, Rule, User, Values } from "./spec";

export const REQUIRED_MESSAGE = "You can't leave this blank.";

export interface Ctx {
  mode: Mode;
  values: Values;
  original?: Values;
  user?: User | null;
}

export interface FieldState {
  visible: boolean;
  readonly: boolean;
  required: boolean;
  requiredRule?: Rule;
}

export interface RuleError {
  field?: string | null;
  message: string;
  presentation: string;
  rule: string;
}

export function isEmpty(v: unknown): boolean {
  if (v === null || v === undefined || v === "") return true;
  if (Array.isArray(v)) return v.length === 0;
  if (typeof v === "object") {
    const id = (v as { id?: unknown }).id;
    return id === null || id === undefined || id === 0 || id === "";
  }
  return false;
}

function scalar(v: unknown, against?: unknown): unknown {
  if (v !== null && typeof v === "object" && !Array.isArray(v)) {
    const o = v as { id?: unknown; title?: unknown };
    if (typeof against === "number") return o.id;
    return "title" in o ? o.title : o.id;
  }
  return v;
}

function numOrDate(v: unknown): unknown {
  if (typeof v === "string" && /^\s*\$?-?[\d,]+(\.\d+)?\s*$/.test(v)) return parseFloat(v.replace(/[$,]/g, ""));
  return v;
}

function cmp(a0: unknown, op: string, b0: unknown): boolean {
  const a = numOrDate(scalar(a0, b0)) as number | string | boolean | null | undefined;
  const b = numOrDate(b0) as number | string | boolean | null | undefined;
  if (op === "eq") return a === b;
  if (op === "ne") return a !== b;
  if (a === null || a === undefined || b === null || b === undefined || a === "") return false;
  if (typeof a !== typeof b) return false;
  if (op === "gt") return a > b;
  if (op === "gte") return a >= b;
  if (op === "lt") return a < b;
  if (op === "lte") return a <= b;
  throw new Error(`unknown operator ${op}`);
}

export function getValue(values: Values, path: string): unknown {
  const [head, rest] = path.includes(".") ? [path.slice(0, path.indexOf(".")), path.slice(path.indexOf(".") + 1)] : [path, ""];
  const v = values[head];
  if (rest && v && typeof v === "object") {
    const o = v as Record<string, unknown>;
    return rest in o ? o[rest] : o[rest.toLowerCase()];
  }
  return v;
}

export function evaluate(cond: Condition | null | undefined, ctx: Ctx): boolean {
  if (!cond) return true;
  const c = cond as Record<string, any>;
  if ("all" in c) return (c.all as Condition[]).every((x) => evaluate(x, ctx));
  if ("any" in c) return (c.any as Condition[]).some((x) => evaluate(x, ctx));
  if ("not" in c) return !evaluate(c.not as Condition, ctx);
  if ("role" in c) return (ctx.user?.groups ?? []).includes(c.role);
  if ("mode" in c) return (Array.isArray(c.mode) ? c.mode : [c.mode]).includes(ctx.mode);
  if ("field" in c) {
    const v = getValue(ctx.values ?? {}, c.field);
    let result = true;
    for (const [op, arg] of Object.entries(c)) {
      if (op === "field") continue;
      let ok: boolean;
      if (op === "empty") ok = isEmpty(v) === Boolean(arg);
      else if (op === "notEmpty") ok = !isEmpty(v) === Boolean(arg);
      else if (op === "changed") ok = (scalar(v) !== scalar(getValue(ctx.original ?? {}, c.field))) === Boolean(arg);
      else if (op === "in") ok = (arg as unknown[]).includes(scalar(v, (arg as unknown[])[0]));
      else if (op === "nin") ok = !(arg as unknown[]).includes(scalar(v, (arg as unknown[])[0]));
      else ok = cmp(v, op, arg);
      result = result && ok;
    }
    return result;
  }
  throw new Error(`unknown condition ${JSON.stringify(cond)}`);
}

export const applies = (r: Rule, mode: Mode) => !r.modes || r.modes.length === 0 || r.modes.includes(mode);

export function rulesFor(rules: Rule[], kind: string, field: string | null, mode: Mode): Rule[] {
  return rules.filter((r) => r.kind === kind && (field === null || r.field === field) && applies(r, mode));
}

export function fieldState(field: Field, rules: Rule[], ctx: Ctx): FieldState {
  const name = field.name;
  const mode = ctx.mode;
  // visible rules: those for this mode must all hold; a field whose visible rules are all scoped to
  // other modes is hidden in this one (e.g. Status shown only on edit/display)
  const allVis = rules.filter((r) => r.kind === "visible" && r.field === name);
  const visRules = allVis.filter((r) => applies(r, mode));
  let visible = visRules.length ? visRules.every((r) => evaluate(r.when, ctx)) : !allVis.length || !allVis.every((r) => r.modes && r.modes.length);
  if (field.type === "calculated" && mode !== "display") visible = false;
  const readonly = mode === "display" || Boolean(field.read_only) || rulesFor(rules, "readonly", name, mode).some((r) => evaluate(r.when, ctx));
  const required = Boolean(field.required) && mode !== "display" && !readonly;
  const requiredRule = rulesFor(rules, "required", name, mode).find((r) => evaluate(r.when, ctx));
  return { visible, readonly, required: required || (requiredRule !== undefined && visible), requiredRule };
}

export function resolveToken(token: unknown, user: User | null | undefined, today?: string): unknown {
  if (token === "@me") return user ? { id: user.id, login: user.login, title: user.title } : null;
  if (token === "@today") return today ?? new Date().toLocaleDateString("en-CA");
  return token;
}

export function defaults(fields: Field[], rules: Rule[], user: User | null | undefined, today?: string): Values {
  const out: Values = {};
  for (const f of fields) if (f.default !== undefined) out[f.name] = resolveToken(f.default, user, today);
  for (const r of rulesFor(rules, "default", null, "new")) out[r.field as string] = resolveToken(r.params?.value, user, today);
  return out;
}

export function fillTemplate(text: string, values: Values): string {
  return (text ?? "").replace(/\{([\w.]+)(?:\|(lower|upper))?\}/g, (_m: string, path: string, filter?: string) => {
    const v = scalar(getValue(values, path));
    if (v === null || v === undefined) return "";
    const out = String(v);
    return filter === "lower" ? out.toLowerCase() : filter === "upper" ? out.toUpperCase() : out;
  });
}

export function validate(fields: Field[], rules: Rule[], ctx: Ctx): RuleError[] {
  const errors: RuleError[] = [];
  const values = ctx.values ?? {};
  const mode = ctx.mode;
  const states: Record<string, FieldState> = {};
  for (const f of fields) states[f.name] = fieldState(f, rules, ctx);

  for (const f of fields) {
    const st = states[f.name];
    const v = values[f.name];
    if (!st.visible || st.readonly) continue;
    if (f.required && isEmpty(v)) {
      errors.push({ field: f.name, message: REQUIRED_MESSAGE, presentation: "inline", rule: "schema" });
      continue;
    }
    if (isEmpty(v)) continue;
    if (f.max_length && typeof v === "string" && v.length > f.max_length)
      errors.push({ field: f.name, message: `The value of this field may not contain more than ${f.max_length} characters.`, presentation: "inline", rule: "schema" });
    if (f.type === "number" || f.type === "currency") {
      const n = numOrDate(v);
      if (typeof n !== "number" || Number.isNaN(n)) errors.push({ field: f.name, message: "The value of this field must be a number.", presentation: "inline", rule: "schema" });
      else {
        if (f.min !== undefined && n < f.min) errors.push({ field: f.name, message: `The value of this field must be greater than or equal to ${f.min}.`, presentation: "inline", rule: "schema" });
        if (f.max !== undefined && n > f.max) errors.push({ field: f.name, message: `The value of this field must be less than or equal to ${f.max}.`, presentation: "inline", rule: "schema" });
      }
    }
    if (f.type === "choice" && f.choices && f.choices.length && !f.fill_in && !f.choices.includes(v as string))
      errors.push({ field: f.name, message: "Select a valid value.", presentation: "inline", rule: "schema" });
  }

  for (const r of rules) {
    if (!applies(r, mode) || mode === "display") continue;
    const fname = r.field ?? null;
    const st = fname ? states[fname] : undefined;
    if (st && (!st.visible || st.readonly) && r.kind !== "lock_item") continue;
    if (r.when && !evaluate(r.when, ctx)) continue;
    const v = fname ? values[fname] : undefined;
    const p = (r.params ?? {}) as Record<string, any>;
    let failed = false;
    if (r.kind === "required") failed = isEmpty(v);
    else if (r.kind === "compare") {
      const other = values[p.other];
      failed = isEmpty(v) || isEmpty(other) ? false : !cmp(v, p.op, scalar(other));
    } else if (r.kind === "length") failed = !(p.allow_empty && isEmpty(v)) && !cmp(String(v ?? "").length, p.op, p.value);
    else if (r.kind === "range") failed = !isEmpty(v) && !cmp(v, p.op, p.value);
    else if (r.kind === "pattern") failed = !isEmpty(v) && !new RegExp(`^(?:${p.regex})$`).test(String(v));
    if (failed) errors.push({ field: fname, message: fillTemplate(r.message ?? REQUIRED_MESSAGE, values), presentation: r.presentation ?? "inline", rule: r.id });
  }
  const seen = new Set<string>();
  return errors.filter((e) => {
    const key = e.field ? `${e.field}|${e.presentation}` : e.rule;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

export function lock(rules: Rule[], ctx: Ctx): Rule | undefined {
  return rulesFor(rules, "lock_item", null, ctx.mode).find((r) => evaluate(r.when, ctx));
}

export function setOnSave(rules: Rule[], ctx: Ctx): Values {
  const out: Values = {};
  for (const r of rulesFor(rules, "set_on_save", null, ctx.mode)) if (evaluate(r.when, ctx)) out[r.field as string] = resolveToken(r.params?.value, ctx.user);
  return out;
}

export function banners(rules: Rule[], ctx: Ctx): Rule[] {
  return rulesFor(rules, "banner", null, ctx.mode).filter((r) => evaluate(r.when, ctx));
}

// Fields hidden by a visible rule with params.clear lose their value (legacy: hide row + .val("")).
export function clearHidden(fields: Field[], rules: Rule[], ctx: Ctx): Values {
  const out: Values = {};
  if (ctx.mode === "display") return out;
  for (const f of fields) {
    const clears = rules.some((r) => r.kind === "visible" && r.field === f.name && r.params?.clear);
    if (clears && !fieldState(f, rules, ctx).visible && !isEmpty(ctx.values?.[f.name])) out[f.name] = null;
  }
  return out;
}
