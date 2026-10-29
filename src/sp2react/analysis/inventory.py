"""Stage 3 (inspect): build the inventory for one screen.

A screen is either a list's forms taken together (NewForm/EditForm/DispForm share fields and usually
one script) or a standalone page (SitePages/Dashboard.aspx ...). The inventory is deterministic: it is
what the spec agent must account for, and what the coverage gate checks the spec against.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from .aspx import ParsedPage, load_page, resolve_tokens, scan_html
from .behaviors import INFO, MUST, Behavior, FieldIndex, analyze_script, classify_script
from .fields import map_fields, translate_formula

MODE_BY_FORM = {"newform": "new", "editform": "edit", "dispform": "display"}


def kebab(name: str) -> str:
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name)
    return re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()


class Legacy:
    """Read access to an extracted workspace (<workspace>/legacy)."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.site = json.loads((self.root / "site.json").read_text(encoding="utf-8"))
        self.prefix = self.site.get("serverRelativeUrl", "").rstrip("/")
        self.lists = {l["url"].rstrip("/").split("/")[-1]: l for l in self.site["lists"]}
        self.list_by_id = {l["id"].strip("{}").lower(): k for k, l in self.lists.items()}
        self.list_by_title = {l["title"].lower(): k for k, l in self.lists.items()}
        self._fields: dict[str, tuple[list[dict], list[dict]]] = {}
        self.index = FieldIndex()
        for key, l in self.lists.items():
            flds, _ = self.fields(key)
            self.index.add_list(key, l["title"], flds)

    def fields(self, key: str) -> tuple[list[dict], list[dict]]:
        if key not in self._fields:
            f = self.root / "lists" / key / "fields.json"
            self._fields[key] = map_fields(json.loads(f.read_text(encoding="utf-8")), self.list_by_id) if f.exists() else ([], [])
        return self._fields[key]

    def items(self, key: str) -> list[dict]:
        f = self.root / "lists" / key / "items.json"
        if not f.exists():
            return []
        data = json.loads(f.read_text(encoding="utf-8"))
        return data.get("d", {}).get("results", []) if isinstance(data, dict) else data

    def site_rel(self, url: str) -> str:
        url = resolve_tokens(url, self.prefix).split("?")[0].split("#")[0]
        url = re.sub(r"^https?://[^/]+", "", url)
        if url.lower().startswith(self.prefix.lower() + "/"):
            return url[len(self.prefix) + 1:]
        return url.lstrip("/")

    def file_text(self, rel: str) -> Optional[str]:
        f = self.root / "files" / rel
        return f.read_text(encoding="utf-8", errors="replace") if f.exists() else None

    def pages(self) -> list[str]:
        base = self.root / "pages"
        return sorted(str(p.relative_to(base)).replace("\\", "/") for p in base.rglob("*.aspx"))

    def form_list(self, page_rel: str, parsed: Optional[ParsedPage] = None) -> Optional[str]:
        if parsed and parsed.list_id and parsed.list_id in self.list_by_id:
            return self.list_by_id[parsed.list_id]
        for key, l in self.lists.items():
            for form in l.get("forms", {}).values():
                if f"{l['url']}/{form}".lower() == page_rel.lower():
                    return key
        return None


def screens(legacy: Legacy, only: Optional[list[str]] = None) -> list[dict]:
    """Group pages into screens: one per list with forms, one per other page."""
    out, used = [], set()
    pages = legacy.pages()
    wanted = None
    if only:
        wanted = {legacy.site_rel(p) if p.startswith(("/", "http")) else p for p in only}
    for page in pages:
        if page in used:
            continue
        parsed = load_page(legacy.root, page)
        key = legacy.form_list(page, parsed)
        if key:
            l = legacy.lists[key]
            members = [f"{l['url']}/{f}" for f in l.get("forms", {}).values() if f"{l['url']}/{f}" in pages] or [page]
            used.update(members)
            scr = {"id": f"{key}-form", "kind": "list-form", "list": key, "title": l["title"], "pages": members,
                   "route": f"/lists/{kebab(key)}"}
        else:
            used.add(page)
            stem = page.rsplit("/", 1)[-1].rsplit(".", 1)[0]
            scr = {"id": stem, "kind": "page", "list": None, "title": parsed.title or stem, "pages": [page],
                   "route": f"/pages/{kebab(stem)}"}
        if wanted is None or wanted & set(scr["pages"]):
            out.append(scr)
    return out


def propose_endpoint(call: dict, legacy: Legacy) -> dict:
    """Deterministic mapping of a legacy data call to the generated FastAPI contract."""
    if call["type"] == "spservices":
        op = call.get("operation", "")
        if op in ("GetGroupCollectionFromUser", "GetUserProfileByName", "GetCurrentUser") or call.get("function") == "SPGetCurrentUser":
            return {"method": "GET", "path": "/api/me", "purpose": "current user and roles (replaces SharePoint group lookup)"}
        if call.get("function") == "SPCascadeDropdowns":
            child = legacy.index.resolve(call.get("childColumn", ""))
            lst, fld = (child[0].list, child[0].name) if child else ("?", "?")
            return {"method": "GET", "path": f"/api/lists/{lst}/lookup/{fld}", "query": {"parent": "<parent id>"}, "purpose": "cascading choices"}
        if op in ("GetListItems",):
            key = legacy.list_by_title.get((call.get("listName") or "").lower(), call.get("listName"))
            return {"method": "GET", "path": f"/api/lists/{key}/items", "query": {"caml": call.get("CAMLQuery"), "rowLimit": call.get("CAMLRowLimit")},
                    "purpose": "list query (CAML to be converted to the API filter)"}
        if op in ("UpdateListItems",):
            key = legacy.list_by_title.get((call.get("listName") or "").lower(), call.get("listName"))
            return {"method": "POST|PATCH", "path": f"/api/lists/{key}/items", "purpose": "create/update via UpdateListItems"}
        return {"method": "?", "path": None, "purpose": f"SPServices {op}: needs an agent decision"}
    key = legacy.list_by_title.get((call.get("list") or "").lower()) or (legacy.list_by_id.get((call.get("list_id") or "").lower()))
    if call.get("resource") == "user":
        return {"method": "GET", "path": "/api/me", "purpose": "current user"}
    if call.get("resource") != "list" or not key:
        return {"method": call["method"], "path": None, "purpose": f"{call.get('resource', 'unknown')} endpoint: needs an agent decision"}
    m = call["method"]
    item = call.get("item")
    base = f"/api/lists/{key}/items"
    if m == "GET":
        return {"method": "GET", "path": base + ("/{id}" if item else ""), "query": call.get("query", {}),
                "purpose": "read item" if item else "query items"}
    if m == "POST" and not item:
        return {"method": "POST", "path": base, "body": call.get("body_fields", []), "purpose": "create item"}
    if m in ("MERGE", "PATCH", "PUT") or (m == "POST" and item):
        return {"method": "PATCH", "path": base + "/{id}", "body": call.get("body_fields", []), "if_match": True, "purpose": "update item"}
    if m == "DELETE":
        return {"method": "DELETE", "path": base + "/{id}", "purpose": "delete item"}
    return {"method": m, "path": base, "purpose": "needs an agent decision"}


def build_inventory(legacy: Legacy, screen: dict) -> dict:
    inv: dict = {"screen": screen, "site": {"url": legacy.site.get("url"), "title": legacy.site.get("title")},
                 "pages": [], "scripts": {"custom": [], "library": [], "sharepoint": [], "external": [], "missing": []},
                 "stylesheets": [], "html_fragments": [], "behaviors": [], "calls": [], "lists": {}, "roles": [],
                 "unresolved": [], "stats": {}}
    prefer = screen.get("list")
    analysed: dict[str, list[str]] = {}       # script rel -> modes using it
    behaviors: list[Behavior] = []
    calls: list[dict] = []
    rendered_counts = {"sharepoint": 0, "library": 0, "custom": 0, "external": 0}

    for page in screen["pages"]:
        parsed = load_page(legacy.root, page)
        stem = page.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()
        mode = (parsed.form_mode or "").lower() or MODE_BY_FORM.get(stem)
        if mode not in ("new", "edit", "display"):
            mode = None
        inv["pages"].append({"path": page, "mode": mode, **parsed.to_dict()})
        for css in parsed.stylesheets:
            rel = legacy.site_rel(css)
            if rel not in inv["stylesheets"] and not rel.startswith("_layouts"):
                inv["stylesheets"].append(rel)
        for frag in parsed.html_fragments:
            inv["html_fragments"].append({"page": page, "mode": mode, **frag})
        for wp in parsed.web_parts:
            if wp.content_link:
                rel = legacy.site_rel(wp.content_link)
                txt = legacy.file_text(rel)
                if txt is None:
                    inv["unresolved"].append({"kind": "missing_file", "detail": f"Content Editor link {rel} was not exported", "page": page})
                    continue
                srcs, inline, css, stripped = scan_html(txt)
                parsed.scripts += srcs
                parsed.inline_scripts += [{"where": f"contentlink:{rel}", "code": c} for c in inline]
                if stripped:
                    inv["html_fragments"].append({"page": page, "mode": mode, "web_part": wp.title, "source": rel, "html": stripped})
            if wp.type == "ListView":
                lk = legacy.list_by_id.get((wp.list_id or "").lower()) or (wp.list_url or "").split("/")[-1] or None
                b = Behavior(id=f"{page}#webpart:{wp.title}:listview", kind="list_view", level=MUST, file=page, line=0,
                             code=f"List view web part '{wp.title}' on {lk}", detail={"list": lk, "view_xml": wp.view_xml, "zone": wp.zone})
                behaviors.append(b)
        for src in parsed.scripts:
            rel = legacy.site_rel(src)
            text = legacy.file_text(rel)
            cls = classify_script(src, text)
            bucket = inv["scripts"][cls]
            if rel not in [s["path"] for s in bucket]:
                bucket.append({"path": rel})
            if cls != "custom":
                continue
            if text is None:
                if rel not in inv["scripts"]["missing"]:
                    inv["scripts"]["missing"].append(rel)
                    inv["unresolved"].append({"kind": "missing_file", "detail": f"Custom script {rel} was referenced but not exported", "page": page})
                continue
            analysed.setdefault(rel, [])
            if mode:
                analysed[rel].append(mode)
            if len(analysed[rel]) > 1 or (not mode and analysed[rel]):
                continue
            bs, cs = analyze_script(rel, text, legacy.index, prefer)
            behaviors += bs
            calls += cs
            next(x for x in bucket if x["path"] == rel)["lines"] = text.count("\n") + 1
        for n, inl in enumerate(parsed.inline_scripts, 1):
            name = f"{page}#inline{n}"
            bs, cs = analyze_script(name, inl["code"], legacy.index, prefer)
            for b in bs:
                b.detail.setdefault("mode", mode)
            behaviors += bs
            calls += cs
            inv["scripts"]["custom"].append({"path": name, "lines": inl["code"].count("\n") + 1, "inline": True, "where": inl["where"], "modes": [mode] if mode else []})

        # what the browser actually loads (master page / custom actions add scripts the .aspx never mentions)
        rf = legacy.root / "rendered" / (re.sub(r"\.aspx$", "", page, flags=re.I) + ".html")
        if rf.exists():
            srcs, _, _, _ = scan_html(rf.read_text(encoding="utf-8", errors="replace"))
            for s in srcs:
                cls = classify_script(s, None)
                rendered_counts[cls] += 1
                rel = legacy.site_rel(s)
                if cls == "custom" and rel not in analysed and rel not in [x["path"] for x in inv["scripts"]["custom"]]:
                    inv["unresolved"].append({"kind": "runtime_script", "detail": f"{rel} is loaded at runtime (master page or custom action) but not referenced by the page", "page": page})

    for s in inv["scripts"]["custom"]:
        if s["path"] in analysed:
            s["modes"] = sorted(set(analysed[s["path"]]))

    # ------------------------------------------------ list schema behaviours
    involved: list[str] = []

    def involve(key: Optional[str]) -> None:
        if key and key in legacy.lists and key not in involved:
            involved.append(key)

    involve(prefer)
    for c in calls:
        involve(legacy.list_by_title.get((c.get("list") or c.get("listName") or c.get("relationshipList") or "").lower()))
    for b in behaviors:
        for f in b.fields:
            involve(f.list)
        if b.kind == "list_view":
            involve(b.detail.get("list"))
    for key in list(involved):
        for f in legacy.fields(key)[0]:
            if f.get("lookup"):
                involve(f["lookup"]["list"])

    for key in involved:
        l = legacy.lists[key]
        flds, formulas = legacy.fields(key)
        names = {}
        for f in flds:
            names[f["label"]] = f["name"]
            names[f["name"]] = f["name"]
            names[f["label"].lower()] = f["name"]
        ported = []
        for fm in formulas:
            rule = translate_formula(fm["formula"], names)
            entry = {"field": fm["field"], "formula": fm["formula"], "message": fm["message"], "ported": rule}
            ported.append(entry)
            if key == prefer:
                behaviors.append(Behavior(id=f"schema:{key}.{fm['field']}:column_validation", kind="column_validation", level=MUST,
                                          file=f"lists/{key}/fields.json", line=0, code=fm["formula"], message=fm["message"],
                                          detail={"ported": rule}))
        lv = None
        if l.get("validationFormula"):
            lv = {"formula": l["validationFormula"], "message": l.get("validationMessage") or "",
                  "ported": translate_formula(l["validationFormula"], names)}
            if key == prefer:
                behaviors.append(Behavior(id=f"schema:{key}:list_validation", kind="list_validation", level=MUST,
                                          file="site.json", line=0, code=l["validationFormula"], message=lv["message"], detail={"ported": lv["ported"]}))
        if key == prefer and l.get("enableAttachments"):
            behaviors.append(Behavior(id=f"schema:{key}:attachments", kind="attachments", level=MUST, file="site.json", line=0,
                                      code="EnableAttachments=true", detail={}))
        inv["lists"][key] = {"title": l["title"], "role": "primary" if key == prefer else "related", "fields": flds,
                             "column_validations": ported, "list_validation": lv,
                             "views": l.get("views", {}), "attachments": l.get("enableAttachments", False),
                             "item_count": len(legacy.items(key))}

    # roles: SharePoint groups referenced in code, plus the site's groups for context
    referenced = sorted({b.detail["group"] for b in behaviors if b.kind == "role_check"})
    inv["roles"] = [{"group": g["name"], "members": len(g.get("members", [])), "referenced": g["name"] in referenced}
                    for g in legacy.site.get("groups", [])]
    for g in referenced:
        if g not in [r["group"] for r in inv["roles"]]:
            inv["roles"].append({"group": g, "members": None, "referenced": True})

    for c in calls:
        if c.get("function") == "SPFindPeoplePicker":
            c["proposed"] = {"method": "GET", "path": "/api/me", "purpose": "default a person field to the current user"}
            continue
        c["proposed"] = propose_endpoint(c, legacy)
        if c["proposed"].get("path") is None:
            inv["unresolved"].append({"kind": "endpoint", "detail": f"No standard endpoint for {c.get('url') or c.get('operation')}", "behavior": c["behavior"]})

    inv["behaviors"] = [b.to_dict() for b in behaviors]
    inv["calls"] = calls
    inv["stats"] = {
        "pages": len(inv["pages"]), "custom_scripts": len(inv["scripts"]["custom"]),
        "library_scripts": len(inv["scripts"]["library"]), "behaviors_must": sum(1 for b in behaviors if b.level == MUST),
        "behaviors_info": sum(1 for b in behaviors if b.level == INFO), "data_calls": len(calls),
        "rendered_scripts": rendered_counts, "lists": len(involved), "unresolved": len(inv["unresolved"]),
    }
    return inv


def must_behaviors(inv: dict) -> list[dict]:
    return [b for b in inv["behaviors"] if b["level"] == MUST]
