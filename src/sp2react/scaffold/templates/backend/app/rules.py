"""Spec rule engine (server side). Mirrors frontend/src/runtime/rules.ts; both are tested
against the same vectors so the browser and the API always agree.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Optional

REQUIRED_MESSAGE = "You can't leave this blank."


def is_empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or (isinstance(v, dict) and v.get("id") in (None, 0, ""))


def _scalar(v: Any, against: Any = None) -> Any:
    """Lookup/user objects compare by title when the other side is text, by id when it is a number."""
    if isinstance(v, dict):
        if isinstance(against, (int, float)) and not isinstance(against, bool):
            return v.get("id")
        return v.get("title") if "title" in v else v.get("id")
    return v


def _num_or_date(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        try:
            return float(v.replace(",", "").replace("$", "")) if re.fullmatch(r"\s*[$]?-?[\d,]+(\.\d+)?\s*", v) else v
        except ValueError:
            return v
    return v


def _cmp(a: Any, op: str, b: Any) -> bool:
    a, b = _num_or_date(_scalar(a, b)), _num_or_date(b)
    if op == "eq":
        return a == b
    if op == "ne":
        return a != b
    if a is None or b is None or a == "":
        return False
    try:
        if op == "gt":
            return a > b
        if op == "gte":
            return a >= b
        if op == "lt":
            return a < b
        if op == "lte":
            return a <= b
    except TypeError:
        return False
    raise ValueError(f"unknown operator {op}")


def get_value(values: dict, path: str) -> Any:
    head, _, rest = path.partition(".")
    v = values.get(head)
    if rest and isinstance(v, dict):
        return v.get(rest) if rest in v else v.get(rest.lower())
    return v


def evaluate(cond: Optional[dict], ctx: dict) -> bool:
    """ctx: {mode, values, original, user: {groups: [...]}}"""
    if not cond:
        return True
    if "all" in cond:
        return all(evaluate(c, ctx) for c in cond["all"])
    if "any" in cond:
        return any(evaluate(c, ctx) for c in cond["any"])
    if "not" in cond:
        return not evaluate(cond["not"], ctx)
    if "role" in cond:
        return cond["role"] in (ctx.get("user") or {}).get("groups", [])
    if "mode" in cond:
        modes = cond["mode"] if isinstance(cond["mode"], list) else [cond["mode"]]
        return ctx.get("mode") in modes
    if "field" in cond:
        v = get_value(ctx.get("values") or {}, cond["field"])
        result = True
        for op, arg in cond.items():
            if op == "field":
                continue
            if op == "empty":
                ok = is_empty(v) == bool(arg)
            elif op == "notEmpty":
                ok = (not is_empty(v)) == bool(arg)
            elif op == "changed":
                before = get_value(ctx.get("original") or {}, cond["field"])
                ok = (_scalar(v) != _scalar(before)) == bool(arg)
            elif op == "in":
                ok = _scalar(v, (arg or [None])[0]) in arg
            elif op == "nin":
                ok = _scalar(v, (arg or [None])[0]) not in arg
            else:
                ok = _cmp(v, op, arg)
            result = result and ok
        return result
    raise ValueError(f"unknown condition {cond}")


def applies(rule: dict, mode: str) -> bool:
    return not rule.get("modes") or mode in rule["modes"]


def rules_for(rules: list[dict], kind: str, field: Optional[str], mode: str) -> list[dict]:
    return [r for r in rules if r["kind"] == kind and (field is None or r.get("field") == field) and applies(r, mode)]


def field_state(field: dict, rules: list[dict], ctx: dict) -> dict:
    name, mode = field["name"], ctx["mode"]
    # visible rules: those for this mode must all hold; a field whose visible rules are all scoped to
    # other modes is hidden in this one (e.g. Status shown only on edit/display)
    all_vis = [r for r in rules if r["kind"] == "visible" and r.get("field") == name]
    vis_rules = [r for r in all_vis if applies(r, mode)]
    visible = all(evaluate(r.get("when"), ctx) for r in vis_rules) if vis_rules else not all_vis or not all(r.get("modes") for r in all_vis)
    if field.get("type") == "calculated" and mode != "display":
        visible = False
    readonly = mode == "display" or bool(field.get("read_only")) or any(evaluate(r.get("when"), ctx) for r in rules_for(rules, "readonly", name, mode))
    required = bool(field.get("required")) and mode != "display" and not readonly
    req_rule = next((r for r in rules_for(rules, "required", name, mode) if evaluate(r.get("when"), ctx)), None)
    return {"visible": visible, "readonly": readonly, "required": required or (req_rule is not None and visible),
            "required_rule": req_rule}


def resolve_token(token: Any, user: dict, today: Optional[date] = None) -> Any:
    if token == "@me":
        return {"id": user.get("id"), "login": user.get("login"), "title": user.get("title")}
    if token == "@today":
        return (today or date.today()).isoformat()
    return token


def defaults(fields: list[dict], rules: list[dict], user: dict, today: Optional[date] = None) -> dict:
    out = {}
    for f in fields:
        if "default" in f:
            out[f["name"]] = resolve_token(f["default"], user, today)
    for r in rules_for(rules, "default", None, "new"):
        out[r["field"]] = resolve_token(r["params"]["value"], user, today)
    return out


def fill_template(text: str, values: dict) -> str:
    """'{Field}', '{Lookup.title}', '{Field|lower}', '{Field|upper}' -> values."""
    def rep(m):
        v = _scalar(get_value(values, m.group(1)))
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        out = str(v).lower() if isinstance(v, bool) else str(v)
        return out.lower() if m.group(2) == "lower" else out.upper() if m.group(2) == "upper" else out
    return re.sub(r"\{([\w.]+)(?:\|(lower|upper))?\}", rep, text or "")


def validate(fields: list[dict], rules: list[dict], ctx: dict) -> list[dict]:
    """-> [{field, message, presentation, rule}] in display order, schema checks first per field."""
    errors: list[dict] = []
    values, mode = ctx.get("values") or {}, ctx["mode"]
    by_name = {f["name"]: f for f in fields}
    states = {f["name"]: field_state(f, rules, ctx) for f in fields}

    for f in fields:
        st, v = states[f["name"]], values.get(f["name"])
        if not st["visible"] or st["readonly"]:
            continue
        if f.get("required") and is_empty(v):
            errors.append({"field": f["name"], "message": REQUIRED_MESSAGE, "presentation": "inline", "rule": "schema"})
            continue
        if is_empty(v):
            continue
        if f.get("max_length") and isinstance(v, str) and len(v) > f["max_length"]:
            errors.append({"field": f["name"], "message": f"The value of this field may not contain more than {f['max_length']} characters.",
                           "presentation": "inline", "rule": "schema"})
        if f.get("type") in ("number", "currency"):
            n = _num_or_date(v)
            if not isinstance(n, (int, float)):
                errors.append({"field": f["name"], "message": "The value of this field must be a number.", "presentation": "inline", "rule": "schema"})
            else:
                if "min" in f and n < f["min"]:
                    errors.append({"field": f["name"], "message": f"The value of this field must be greater than or equal to {f['min']:g}.", "presentation": "inline", "rule": "schema"})
                if "max" in f and n > f["max"]:
                    errors.append({"field": f["name"], "message": f"The value of this field must be less than or equal to {f['max']:g}.", "presentation": "inline", "rule": "schema"})
        if f.get("type") == "choice" and f.get("choices") and not f.get("fill_in") and v not in f["choices"]:
            errors.append({"field": f["name"], "message": "Select a valid value.", "presentation": "inline", "rule": "schema"})

    for r in rules:
        if not applies(r, mode) or mode == "display":
            continue
        fname = r.get("field")
        st = states.get(fname) if fname else None
        if st and (not st["visible"] or st["readonly"]) and r["kind"] not in ("lock_item",):
            continue
        if r.get("when") and not evaluate(r["when"], ctx):
            continue
        k, v, p = r["kind"], values.get(fname) if fname else None, r.get("params") or {}
        failed = False
        if k == "required":
            failed = is_empty(v)
        elif k == "compare":
            other = values.get(p["other"])
            if is_empty(v) or is_empty(other):
                failed = False
            else:
                failed = not _cmp(v, p["op"], _scalar(other))
        elif k == "length":
            failed = not (p.get("allow_empty") and is_empty(v)) and not _cmp(len(str(v or "")), p["op"], p["value"])
        elif k == "range":
            failed = not is_empty(v) and not _cmp(v, p["op"], p["value"])
        elif k == "pattern":
            failed = not is_empty(v) and not re.fullmatch(p["regex"], str(v))
        if failed:
            errors.append({"field": fname, "message": fill_template(r.get("message") or REQUIRED_MESSAGE, values),
                           "presentation": r.get("presentation", "inline"), "rule": r["id"]})
    # one error per field (the first), like SharePoint shows one message under a control
    seen, out = set(), []
    for e in errors:
        key = (e["field"], e["presentation"]) if e["field"] else (e["rule"],)
        if key in seen:
            continue
        seen.add(key)
        out.append(e)
    return out


def lock(rules: list[dict], ctx: dict) -> Optional[dict]:
    for r in rules_for(rules, "lock_item", None, ctx["mode"]):
        if evaluate(r.get("when"), ctx):
            return r
    return None


def set_on_save(rules: list[dict], ctx: dict) -> dict:
    return {r["field"]: resolve_token(r["params"]["value"], ctx.get("user") or {}) for r in rules_for(rules, "set_on_save", None, ctx["mode"])
            if evaluate(r.get("when"), ctx)}


def banners(rules: list[dict], ctx: dict) -> list[dict]:
    return [r for r in rules_for(rules, "banner", None, ctx["mode"]) if evaluate(r.get("when"), ctx)]


def clear_hidden(fields: list[dict], rules: list[dict], ctx: dict) -> dict:
    """Fields hidden by a visible rule with params.clear lose their value (legacy: hide row + .val(""))."""
    out = {}
    for f in fields:
        clears = [r for r in rules if r["kind"] == "visible" and r.get("field") == f["name"] and (r.get("params") or {}).get("clear")]
        if clears and ctx["mode"] != "display" and not field_state(f, rules, ctx)["visible"] and not is_empty((ctx.get("values") or {}).get(f["name"])):
            out[f["name"]] = None
    return out
