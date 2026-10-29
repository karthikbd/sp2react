"""Map SharePoint lists onto an existing database (the data your team already migrated).

  reflect   read the database SCHEMA only (tables, columns, types, keys); no rows are read
  draft     deterministic first pass: names, types and foreign keys
  agent     the dbmap agent resolves what the draft could not (renamed or split columns, odd names)
  validate  every mapped table/column exists, types are compatible, required fields are mapped
The result is db-mapping.json plus db-mapping.md for you to review before code generation uses it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

TYPE_FAMILIES = {
    "text": ("char", "text", "string", "clob", "varchar", "nvarchar", "uniqueidentifier"),
    "number": ("int", "dec", "num", "float", "double", "real", "money"),
    "date": ("date", "time"),
    "boolean": ("bool", "bit", "tinyint"),
    "binary": ("blob", "binary", "image", "bytea"),
}
FIELD_FAMILY = {"text": "text", "note": "text", "choice": "text", "multichoice": "text", "url": "text", "calculated": "text",
                "taxonomy": "text", "number": "number", "currency": "number", "date": "date", "datetime": "date",
                "boolean": "boolean", "lookup": "number", "user": "any"}
SYSTEM_PATTERNS = {
    "Created": r"^(created|created_?(at|on|date|dt|time)|create_?date|date_?created)$",
    "Modified": r"^(modified|modified_?(at|on|date|dt|time)|updated_?(at|on)|last_?modified|date_?modified)$",
    "Author": r"^(author|created_?by|creator)(_?id|_?login)?$",
    "Editor": r"^(editor|modified_?by|updated_?by|last_?modified_?by)(_?id|_?login)?$",
    "version": r"^(version|row_?version|ui_?version|rowversion|etag)$",
}


def tokens(name: str) -> set[str]:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", name)
    s = re.sub(r"_x0020_", " ", s)
    parts = [p for p in re.split(r"[^A-Za-z0-9]+", s.lower()) if p]
    out = set()
    for p in parts:
        if p in ("tbl", "t", "sp", "list", "lst", "dbo"):
            continue
        out.add(p[:-1] if p.endswith("s") and len(p) > 3 else p)
    return out


def similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def family(sql_type: str) -> str:
    t = sql_type.lower()
    for fam, keys in TYPE_FAMILIES.items():
        if any(k in t for k in keys):
            return "boolean" if fam == "number" and "tinyint(1)" in t else fam
    return "text"


def compatible(field_type: str, sql_type: str) -> bool:
    want = FIELD_FAMILY.get(field_type, "text")
    have = family(sql_type)
    if want == "any":
        return have in ("number", "text")
    if want == "boolean":
        return have in ("boolean", "number")
    if want == "date":
        return have in ("date", "text")
    return have == want or (want == "text" and have in ("text",)) or (want == "number" and have == "number")


# ------------------------------------------------------------------ reflect
def reflect(url: str, schema: Optional[str] = None) -> dict:
    try:
        from sqlalchemy import create_engine, inspect
    except ImportError as e:  # pragma: no cover - optional extra
        raise RuntimeError("map-db needs SQLAlchemy and your driver: pip install 'sp2react[db]' (and pymysql or pyodbc)") from e
    eng = create_engine(url, future=True)
    ins = inspect(eng)
    out: dict = {"dialect": eng.dialect.name, "schema": schema, "tables": {}}
    for t in ins.get_table_names(schema=schema):
        pk = ins.get_pk_constraint(t, schema=schema).get("constrained_columns") or []
        fks = {}
        for fk in ins.get_foreign_keys(t, schema=schema):
            for c, rc in zip(fk.get("constrained_columns", []), fk.get("referred_columns", [])):
                fks[c] = {"table": fk.get("referred_table"), "column": rc}
        cols = [{"name": c["name"], "type": str(c["type"]), "nullable": bool(c.get("nullable", True)),
                 "pk": c["name"] in pk, **({"fk": fks[c["name"]]} if c["name"] in fks else {})}
                for c in ins.get_columns(t, schema=schema)]
        out["tables"][t] = {"columns": cols, "pk": pk}
    eng.dispose()
    return out


# -------------------------------------------------------------------- draft
def draft(lists: dict[str, dict], db: dict) -> tuple[dict, list[str]]:
    """lists: {ListKey: {"title", "fields": [...]}} -> (mapping, unresolved notes)."""
    mapping: dict = {"version": 1, "schema": db.get("schema"), "lists": {}}
    notes: list[str] = []
    tables = db["tables"]
    chosen_tables: dict[str, str] = {}
    for key, l in lists.items():
        scored = sorted(((max(similarity(key, t), similarity(l["title"], t)), t) for t in tables), reverse=True)
        if not scored or scored[0][0] < 0.5:
            notes.append(f"{key}: no table with a matching name (best: {scored[0][1] if scored else 'none'})")
            continue
        chosen_tables[key] = scored[0][1]
    for key, tname in chosen_tables.items():
        l, t = lists[key], tables[tname]
        cols = {c["name"]: c for c in t["columns"]}
        used: set[str] = set()
        m: dict = {"table": tname, "key": (t["pk"][0] if t["pk"] else next((c for c in cols if c.lower() in ("id", "item_id", f"{tname}_id")), None)), "fields": {}, "system": {}}
        if not m["key"]:
            notes.append(f"{key}: table {tname} has no primary key; set 'key' to the column holding the item id")
        used.add(m["key"])
        for f in l["fields"]:
            cands = []
            for cname, c in cols.items():
                if cname in used:
                    continue
                s = max(similarity(f["name"], cname), similarity(f["label"], cname))
                if f["type"] == "lookup":
                    target = chosen_tables.get(f["lookup"]["list"])
                    if c.get("fk", {}).get("table") == target and target:
                        s += 1.0
                    if cname.lower().endswith("_id") or cname.lower().endswith("id"):
                        s += 0.2
                if f["type"] == "user" and re.search(r"(login|user|email|_id)$", cname.lower()):
                    s += 0.1
                if s > 0 and compatible(f["type"], c["type"]):
                    cands.append((s, cname))
            cands.sort(reverse=True)
            if cands and cands[0][0] >= 0.5:
                cname = cands[0][1]
                used.add(cname)
                spec: Any = cname
                if f["type"] == "user" and family(cols[cname]["type"]) == "text":
                    spec = {"column": cname, "ref": "login"}
                if f.get("multi") or f["type"] == "multichoice":
                    spec = {"column": cname, "delimiter": ";", **({"ref": "login"} if isinstance(spec, dict) else {})}
                m["fields"][f["name"]] = spec
            else:
                notes.append(f"{key}.{f['name']} ({f['label']}, {f['type']}): no confident column match in {tname}")
        for sysname, pat in SYSTEM_PATTERNS.items():
            hit = next((c for c in cols if c not in used and re.match(pat, c.lower())), None)
            if hit:
                m["system"][sysname] = hit
                used.add(hit)
        mapping["lists"][key] = m
    users = next((t for t in tables if re.search(r"(^|_)(app_?)?users?$", t.lower())), None)
    if users:
        cols = [c["name"] for c in tables[users]["columns"]]
        pick = lambda pat: next((c for c in cols if re.search(pat, c.lower())), None)
        um = {"table": users, "id": tables[users]["pk"][0] if tables[users]["pk"] else pick(r"^(user_?)?id$"),
              "login": pick(r"(login|user_?name|account|upn|sam)"), "title": pick(r"(display|full_?name|^name$|title)"), "email": pick(r"mail")}
        if um["id"] and um["login"]:
            mapping["users"] = {k: v for k, v in um.items() if v}
    return mapping, notes


# ----------------------------------------------------------------- validate
def validate(mapping: dict, lists: dict[str, dict], db: dict) -> tuple[list[str], list[str]]:
    """-> (problems that block, warnings)."""
    problems, warnings = [], []
    tables = db["tables"]
    for key, l in lists.items():
        m = mapping.get("lists", {}).get(key)
        if not m:
            problems.append(f"List {key} ({l['title']}) is not mapped to a table")
            continue
        t = tables.get(m.get("table"))
        if not t:
            problems.append(f"{key}: table '{m.get('table')}' does not exist")
            continue
        cols = {c["name"]: c for c in t["columns"]}
        if m.get("key") not in cols:
            problems.append(f"{key}: key column '{m.get('key')}' does not exist in {m['table']}")
        for fname, spec in m.get("fields", {}).items():
            cname = spec if isinstance(spec, str) else spec.get("column")
            f = next((x for x in l["fields"] if x["name"] == fname), None)
            if not f:
                problems.append(f"{key}: '{fname}' is not a field of the list")
                continue
            if cname not in cols:
                problems.append(f"{key}.{fname}: column '{cname}' does not exist in {m['table']}")
                continue
            if not compatible(f["type"], cols[cname]["type"]):
                warnings.append(f"{key}.{fname}: {f['type']} field mapped to {cols[cname]['type']} column {cname}")
            if f.get("required") and cols[cname]["nullable"] is False:
                pass
            if f["type"] == "lookup" and f["lookup"]["list"] not in mapping.get("lists", {}):
                warnings.append(f"{key}.{fname}: looks up {f['lookup']['list']}, which is not mapped (titles will be empty)")
        for f in l["fields"]:
            if f["name"] not in m.get("fields", {}):
                (problems if f.get("required") else warnings).append(
                    f"{key}.{f['name']} ({f['label']}{', required' if f.get('required') else ''}) has no column")
        for sysname, cname in m.get("system", {}).items():
            if cname not in cols:
                problems.append(f"{key}: system column {sysname} -> '{cname}' does not exist")
        for cname, c in cols.items():
            mapped = {m.get("key")} | {(s if isinstance(s, str) else s.get("column")) for s in m.get("fields", {}).values()} | set(m.get("system", {}).values())
            if cname not in mapped and not c["nullable"] and not c["pk"]:
                warnings.append(f"{key}: NOT NULL column {m['table']}.{cname} is not mapped; inserts will fail unless it has a default")
    um = mapping.get("users")
    if um:
        t = tables.get(um.get("table"))
        if not t:
            problems.append(f"users: table '{um.get('table')}' does not exist")
        else:
            cols = {c["name"] for c in t["columns"]}
            for k in ("id", "login"):
                if um.get(k) not in cols:
                    problems.append(f"users: {k} column '{um.get(k)}' does not exist")
    return problems, warnings


def report(mapping: dict, lists: dict[str, dict], db: dict, problems: list[str], warnings: list[str]) -> str:
    lines = ["# Database mapping: SharePoint lists -> existing tables", "",
             f"Database: {db.get('dialect')} {('schema ' + db['schema']) if db.get('schema') else ''}. Only the schema was read; no rows.", "",
             f"**{'Ready' if not problems else 'Needs attention'}**: {len(problems)} problem(s), {len(warnings)} warning(s).", ""]
    for key, l in lists.items():
        m = mapping.get("lists", {}).get(key)
        lines += [f"## {l['title']} ({key}) -> `{m['table'] if m else 'not mapped'}`", ""]
        if not m:
            continue
        cols = {c["name"]: c for c in db["tables"].get(m["table"], {}).get("columns", [])}
        lines += [f"Key: `{m.get('key')}`", "", "| Field | Type | Column | Column type |", "|---|---|---|---|"]
        for f in l["fields"]:
            spec = m.get("fields", {}).get(f["name"])
            cname = spec if isinstance(spec, str) else (spec or {}).get("column")
            extra = f" ({', '.join(f'{k}={v}' for k, v in spec.items() if k != 'column')})" if isinstance(spec, dict) else ""
            lines.append(f"| {f['label']} (`{f['name']}`) | {f['type']} | {('`' + cname + '`' + extra) if cname else '**missing**'} | {cols.get(cname, {}).get('type', '')} |")
        if m.get("system"):
            lines += ["", "System columns: " + ", ".join(f"{k} -> `{v}`" for k, v in m["system"].items())]
        lines.append("")
    if mapping.get("users"):
        u = mapping["users"]
        lines += ["## People", "", f"Users table `{u['table']}` (id `{u['id']}`, login `{u['login']}`" + (f", name `{u['title']}`" if u.get("title") else "") + ")", ""]
    if problems:
        lines += ["## Problems (block code generation)", ""] + [f"- {p}" for p in problems] + [""]
    if warnings:
        lines += ["## Warnings", ""] + [f"- {w}" for w in warnings]
    return "\n".join(lines) + "\n"
