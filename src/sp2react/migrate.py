"""Data migration and reconciliation: SharePoint list items -> the generated app's database, then proof
that what the app serves matches what SharePoint holds.

  export     every item of every list the converted screens use (paged, original IDs, attachments)
  transform  lookups/people -> ids, date-only values -> calendar dates, multi-values -> lists, system fields kept
  load       written as the app's seed + attachment files, then loaded through the app's own repository
  reconcile  read back THROUGH THE APP's repository and compare with the export: counts, ids, every field,
             orphaned lookups, attachments (sha256), and a per-list fingerprint
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

SYSTEM = ("Created", "Modified", "Author", "Editor")


# ------------------------------------------------------------------ export
def export_lists(sp, legacy_site: dict, lists: Iterable[str], out: Path, page_size: int = 1000,
                 progress: Callable[[str], None] = lambda s: None) -> dict:
    """Writes <out>/<List>.jsonl (raw SharePoint items) and <out>/attachments/<List>/<ID>/<file>."""
    out.mkdir(parents=True, exist_ok=True)
    by_key = {l["url"].rstrip("/").split("/")[-1]: l for l in legacy_site["lists"]}
    summary = {}
    for key in lists:
        l = by_key[key]
        n, files = 0, 0
        with (out / f"{key}.jsonl").open("w", encoding="utf-8") as fh:
            for it in sp.all_items(l["id"], page_size):
                fh.write(json.dumps(it, ensure_ascii=False) + "\n")
                n += 1
                for a in ((it.get("AttachmentFiles") or {}).get("results") or []):
                    data = sp.file_bytes(a["ServerRelativeUrl"])
                    p = out / "attachments" / key / str(it.get("ID") or it.get("Id")) / a["FileName"]
                    p.parent.mkdir(parents=True, exist_ok=True)
                    p.write_bytes(data)
                    files += 1
        summary[key] = {"items": n, "attachments": files}
        progress(f"[migrate] exported {key}: {n} items, {files} attachments")
    (out / "export.json").write_text(json.dumps({"at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), "lists": summary, "source": legacy_site.get("url")}, indent=2))
    return summary


def read_export(out: Path, key: str) -> list[dict]:
    f = out / f"{key}.jsonl"
    return [json.loads(line) for line in f.read_text(encoding="utf-8").splitlines() if line.strip()] if f.exists() else []


# --------------------------------------------------------------- transform
def date_only(v: Optional[str]) -> Optional[str]:
    """SharePoint stores date-only values as local midnight in UTC; +12h lands on the right calendar day either side of UTC."""
    if not v:
        return None
    try:
        return (datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(hours=12)).date().isoformat()
    except ValueError:
        return v[:10]


def _results(v):
    return v.get("results", []) if isinstance(v, dict) else (v or [])


def source_value(f: dict, it: dict, suffix: str = ""):
    """A field's value in a raw REST item. Items are keyed by the field's REST name (EntityPropertyName), which
    differs from the internal name for columns that start with '_' or a digit; older specs only have the name."""
    for key in dict.fromkeys((f.get("rest_name") or "", f["name"], ("OData_" + f["name"]) if re.match(r"[_0-9]", f["name"]) else "")):
        if key and key + suffix in it:
            return it[key + suffix]
    return None


def url_value(v):
    """SharePoint hyperlink {Url, Description} -> {url, description}."""
    if isinstance(v, dict):
        return {"url": v.get("Url"), "description": v.get("Description")} if v.get("Url") else None
    return {"url": v, "description": None} if v else None


def term_value(f: dict, it: dict):
    """Managed metadata -> {label, term_id} (a list for multi-value fields). REST's own Label is the WssId, so the
    label comes from the field's hidden note column ("Label|TermGuid;Label2|Guid2") when the schema names it."""
    raw = source_value(f, it)
    terms = raw.get("results", []) if isinstance(raw, dict) and "results" in raw else ([raw] if isinstance(raw, dict) else [])
    labels = {}
    note = it.get(f["label_field"]) if f.get("label_field") else None
    for part in (note or "").split(";"):
        if "|" in part:
            label, guid = part.rsplit("|", 1)
            labels[guid.strip().lower()] = label.strip()
    out = [{"label": labels.get(str(t.get("TermGuid", "")).lower()), "term_id": t.get("TermGuid")} for t in terms if t and t.get("TermGuid")]
    return out if f.get("multi") else (out[0] if out else None)


def has_source_key(f: dict, it: dict) -> bool:
    """REST returns every column of an item, null or not: a field that is in no exported item was read by the wrong name."""
    names = {f.get("rest_name") or "", f["name"], ("OData_" + f["name"]) if re.match(r"[_0-9]", f["name"]) else ""} - {""}
    return any(n in it or n + "Id" in it for n in names)


def transform(items: list[dict], fields: list[dict]) -> list[dict]:
    rows = []
    for it in items:
        row: dict = {"ID": it.get("ID") or it.get("Id")}
        for f in fields:
            n, t = f["name"], f["type"]
            if t in ("lookup", "user"):
                raw = source_value(f, it, "Id")
                raw = source_value(f, it) if raw is None else raw
                row[n] = sorted(_results(raw)) if f.get("multi") else (raw if isinstance(raw, int) else None)
            elif t == "multichoice":
                row[n] = list(_results(source_value(f, it)))
            elif t == "date":
                row[n] = date_only(source_value(f, it))
            elif t == "url":
                row[n] = url_value(source_value(f, it))
            elif t == "taxonomy":
                row[n] = term_value(f, it)
            elif t in ("number", "currency"):
                v = source_value(f, it)
                row[n] = float(v) if v not in (None, "") else None
            else:
                row[n] = source_value(f, it)
        ver = str(it.get("_UIVersionString") or it.get("OData__UIVersionString") or "1.0").split(".")[0]
        row["_meta"] = {"version": int(ver) if ver.isdigit() else 1, "created": it.get("Created"), "modified": it.get("Modified"),
                        "author": it.get("AuthorId"), "editor": it.get("EditorId")}
        rows.append(row)
    return rows


# -------------------------------------------------------------------- load
def write_seed(app: Path, key: str, rows: list[dict], attachments_dir: Optional[Path]) -> None:
    seed = app / "backend" / "data" / "seed"
    seed.mkdir(parents=True, exist_ok=True)
    (seed / f"{key}.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    if attachments_dir and (attachments_dir / key).exists():
        import shutil
        dst = app / "backend" / "data" / "attachments" / key
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(attachments_dir / key, dst)


LOADER = r"""
import json, os, sys, hashlib
from pathlib import Path
sys.path.insert(0, os.getcwd())
if sys.argv[2] == "load":
    db = Path(os.environ["DB_PATH"])
    if db.exists():
        db.unlink()
from app.main import create_app
repo = create_app().state.repo      # the same repository the API uses (sqlite seed, or your database via mapping.json)
out = {}
for name in repo.specs.lists:
    try:
        items = repo.all(name)
    except KeyError:                # list not mapped to a table
        continue
    for it in items:
        it["_attachment_sha256"] = {n: hashlib.sha256(repo.attachment(name, it["ID"], n) or b"").hexdigest() for n in it.get("Attachments", [])}
    out[name] = items
print(json.dumps(out, default=str))
"""


def read_through_app(app: Path, db_path: Path, load: bool, env: Optional[dict] = None) -> dict:
    """Run the generated backend's own repository (same code the API uses) and return every item it serves."""
    r = subprocess.run([sys.executable, "-c", LOADER, str(db_path), "load" if load else "read"], cwd=app / "backend",
                       capture_output=True, text=True, timeout=900,
                       env={**os.environ, "DB_PATH": str(db_path), "DATA_SOURCE": "sqlite", **(env or {})})
    if r.returncode != 0:
        raise RuntimeError(f"could not read the app database: {r.stderr[-2000:]}")
    return json.loads(r.stdout)


# --------------------------------------------------------------- reconcile
def _norm_source(f: dict, it: dict):
    t = f["type"]
    if t in ("lookup", "user"):
        raw = source_value(f, it, "Id")
        raw = source_value(f, it) if raw is None else raw
        return sorted(_results(raw)) if f.get("multi") else (raw if isinstance(raw, int) else None)
    v = source_value(f, it)
    if t == "multichoice":
        return sorted(_results(v))
    if t == "date":
        return date_only(v)
    if t == "url":
        return url_value(v)
    if t == "taxonomy":
        return term_value(f, it)
    if t in ("number", "currency"):
        return float(v) if v not in (None, "") else None
    if t == "boolean":
        return bool(v) if v is not None else None
    return None if v == "" else v


def _norm_app(f: dict, v):
    t = f["type"]
    if t == "url":
        if isinstance(v, dict) and "url" in v:
            return {"url": v["url"], "description": v.get("description")} if v["url"] else None
        return url_value(v)
    if t == "taxonomy":
        return v
    if t in ("lookup", "user"):
        if isinstance(v, list):
            return sorted(x.get("id") for x in v if x)
        return v.get("id") if isinstance(v, dict) else v
    if t == "multichoice":
        return sorted(v or [])
    if t in ("number", "currency"):
        return float(v) if v not in (None, "") else None
    if t == "boolean":
        return bool(v) if v is not None else None
    return None if v == "" else v


def _sec(v: Optional[str]) -> Optional[str]:
    return v[:19] if isinstance(v, str) else v


def reconcile(export_dir: Path, app_items: dict, specs_lists: dict, max_rows: int = 200) -> dict:
    report: dict = {"ok": True, "lists": {}}
    for key, l in specs_lists.items():
        fields = l["fields"]
        src = {int(it.get("ID") or it.get("Id") or 0): it for it in read_export(export_dir, key)}
        dst = {int(it["ID"]): it for it in app_items.get(key, [])}
        lr: dict[str, Any] = {"source_items": len(src), "app_items": len(dst), "missing_in_app": sorted(set(src) - set(dst)),
              "extra_in_app": sorted(set(dst) - set(src)), "field_mismatches": [], "orphan_lookups": [], "attachment_mismatches": [],
              "fields_checked": len(fields) + len(SYSTEM),
              "fields_not_in_export": [f["name"] for f in fields if src and not f.get("read_only") and f["type"] != "calculated"
                                       and not any(has_source_key(f, it) for it in src.values())]}
        canon_src, canon_dst = [], []
        for iid in sorted(set(src) & set(dst)):
            s, d = src[iid], dst[iid]
            rs: dict[str, Any] = {"ID": iid}
            rd: dict[str, Any] = {"ID": iid}
            for f in fields:
                a, b = _norm_source(f, s), _norm_app(f, d.get(f["name"]))
                rs[f["name"]], rd[f["name"]] = a, b
                if a != b and len(lr["field_mismatches"]) < max_rows:
                    lr["field_mismatches"].append({"id": iid, "field": f["name"], "sharepoint": a, "app": b})
                if f["type"] == "lookup" and isinstance(d.get(f["name"]), dict) and d[f["name"]].get("title") is None and b is not None:
                    lr["orphan_lookups"].append({"id": iid, "field": f["name"], "points_to": b, "list": f["lookup"]["list"]})
            for name, sk, dk in (("Created", "Created", "Created"), ("Modified", "Modified", "Modified")):
                a, b = _sec(s.get(sk)), _sec(d.get(dk))
                rs[name], rd[name] = a, b
                if a != b and len(lr["field_mismatches"]) < max_rows:
                    lr["field_mismatches"].append({"id": iid, "field": name, "sharepoint": a, "app": b})
            for name in ("Author", "Editor"):
                a, b = s.get(f"{name}Id"), (d.get(name) or {}).get("id")
                rs[name], rd[name] = a, b
                if a != b and len(lr["field_mismatches"]) < max_rows:
                    lr["field_mismatches"].append({"id": iid, "field": name, "sharepoint": a, "app": b})
            sp_files = {a["FileName"] for a in ((s.get("AttachmentFiles") or {}).get("results") or [])}
            app_files = set(d.get("Attachments") or [])
            for n in sorted(sp_files | app_files):
                p = export_dir / "attachments" / key / str(iid) / n
                sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.exists() else None
                got = (d.get("_attachment_sha256") or {}).get(n)
                if sha != got:
                    lr["attachment_mismatches"].append({"id": iid, "file": n, "sharepoint_sha256": sha, "app_sha256": got})
            canon_src.append(rs)
            canon_dst.append(rd)
        fp = lambda rows: hashlib.sha256(json.dumps(rows, sort_keys=True, default=str).encode()).hexdigest()[:16]
        lr["fingerprint_sharepoint"], lr["fingerprint_app"] = fp(canon_src), fp(canon_dst)
        lr["ok"] = not (lr["missing_in_app"] or lr["extra_in_app"] or lr["field_mismatches"] or lr["orphan_lookups"]
                        or lr["attachment_mismatches"] or lr["fields_not_in_export"])
        report["lists"][key] = lr
        report["ok"] = report["ok"] and lr["ok"]
    return report


def report_markdown(rep: dict, export_meta: dict) -> str:
    lines = ["# Data reconciliation: SharePoint lists vs the converted app", "",
             f"Export taken {export_meta.get('at', '?')} from {export_meta.get('source', '?')}. Values were read back through the app's own repository.", "",
             f"**Result: {'all lists match' if rep['ok'] else 'MISMATCHES FOUND'}**", "",
             "| List | SharePoint items | App items | Missing | Extra | Field mismatches | Orphan lookups | Attachments | Fingerprint (SP / app) |",
             "|---|---:|---:|---:|---:|---:|---:|---|---|"]
    for key, l in rep["lists"].items():
        att = "ok" if not l["attachment_mismatches"] else f"{len(l['attachment_mismatches'])} differ"
        lines.append(f"| {key} | {l['source_items']} | {l['app_items']} | {len(l['missing_in_app'])} | {len(l['extra_in_app'])} | "
                     f"{len(l['field_mismatches'])} | {len(l['orphan_lookups'])} | {att} | `{l['fingerprint_sharepoint']}` / `{l['fingerprint_app']}` |")
    for key, l in rep["lists"].items():
        if l["ok"]:
            continue
        lines += ["", f"## {key}", ""]
        if l.get("fields_not_in_export"):
            lines.append(f"- Not found in any exported item, so not compared: {', '.join(l['fields_not_in_export'])} "
                         "(the field's REST name differs from its internal name; re-run extract to record it)")
        if l["missing_in_app"]:
            lines.append(f"- Missing in the app: IDs {l['missing_in_app'][:50]}")
        if l["extra_in_app"]:
            lines.append(f"- In the app but not in SharePoint: IDs {l['extra_in_app'][:50]}")
        for m in l["field_mismatches"][:100]:
            lines.append(f"- ID {m['id']} `{m['field']}`: SharePoint `{m['sharepoint']!r}` vs app `{m['app']!r}`")
        for o in l["orphan_lookups"][:50]:
            lines.append(f"- ID {o['id']} `{o['field']}` points to {o['list']} item {o['points_to']}, which does not exist")
        for a in l["attachment_mismatches"][:50]:
            lines.append(f"- ID {a['id']} attachment `{a['file']}` differs (SharePoint {a['sharepoint_sha256']}, app {a['app_sha256']})")
    return "\n".join(lines) + "\n"
