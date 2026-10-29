"""Deterministic part of the spec: everything that can be derived without judgement.

The spec agent receives this base and adds the rules/components that need interpretation
(what a jQuery handler *means*). Keeping this part deterministic means it is never hallucinated.
"""
from __future__ import annotations

import re

from ..analysis.inventory import kebab
from .model import Component, Endpoint, ListSpec, Rule, Screen, Spec

MODES_ORDER = ["new", "edit", "display"]


def _src(b: dict) -> list[str]:
    return [f"{b['file']}:{b['line']}"] if b.get("line") else [b["file"]]


def base_spec(inv: dict) -> Spec:
    scr = inv["screen"]
    primary = scr.get("list")
    modes = [m for m in MODES_ORDER if any(p.get("mode") == m for p in inv["pages"])]
    site_prefix = re.sub(r"^https?://[^/]+", "", inv["site"].get("url") or "").rstrip("/")
    screen = Screen(
        id=scr["id"], kind=scr["kind"], title=scr["title"], route=scr["route"], list=primary, modes=modes,
        legacy_urls=[f"{site_prefix}/{p['path']}" for p in inv["pages"]],
        stylesheets=inv.get("stylesheets", []),
    )
    rules: list[Rule] = []
    by_kind: dict[str, list[dict]] = {}
    for b in inv["behaviors"]:
        by_kind.setdefault(b["kind"], []).append(b)

    if scr["kind"] == "list-form":
        form = Component(id="form", kind="form", title=scr["title"],
                         props={"list": primary, "modes": modes, "toolbar": {"new": ["Save", "Cancel"], "edit": ["Save", "Cancel"], "display": ["Edit Item", "Close"]}},
                         covers=[b["id"] for b in by_kind.get("attachments", [])])
        screen.components.append(form)
        # schema validations that translate mechanically
        for b in by_kind.get("column_validation", []) + by_kind.get("list_validation", []):
            ported = (b.get("detail") or {}).get("ported")
            if not ported:
                continue
            n = len(rules) + 1
            rules.append(Rule(id=f"S{n}", origin="schema", message=b.get("message"), presentation="inline",
                              covers=[b["id"]], src=_src(b), list=primary, **ported))
    else:
        for i, frag in enumerate(inv.get("html_fragments", []), 1):
            screen.components.append(Component(id=f"fragment{i}", kind="html", title=frag.get("web_part"), order=i,
                                               props={"legacy_html": frag["html"][:4000], "page": frag["page"]}))
        for b in by_kind.get("list_view", []):
            d = b.get("detail") or {}
            screen.components.append(Component(id=f"listview-{kebab(b['id'].split(':')[-2])}", kind="list_view",
                                               title=b["code"].split("'")[1] if "'" in b["code"] else None,
                                               region=d.get("zone"), props={"list": d.get("list"), "view_xml": d.get("view_xml")},
                                               covers=[b["id"]], src=_src(b)))

    # endpoints proposed from the data calls, merged by method+path
    endpoints: dict[tuple, Endpoint] = {}
    for c in inv["calls"]:
        p = c.get("proposed") or {}
        if not p.get("path") or p.get("method") not in ("GET", "POST", "PATCH", "DELETE"):
            continue
        key = (p["method"], p["path"])
        if key not in endpoints:
            m = re.match(r"/api/lists/(\w+)", p["path"])
            eid = f"E{len(endpoints) + 1}"
            endpoints[key] = Endpoint(id=eid, method=p["method"], path=p["path"], purpose=p.get("purpose", ""),
                                      list=m.group(1) if m else None, body=p.get("body", []) or [])
        e = endpoints[key]
        e.covers.append(c["behavior"])
        e.src.append(f"{c['behavior'].split('#L')[0]}:{c.get('line')}")
        if p.get("query"):
            e.query.setdefault("usages", []).append({k: v for k, v in p["query"].items() if v})
    lists = {k: ListSpec(title=v["title"], primary=(v["role"] == "primary"), fields=v["fields"],
                         attachments=v.get("attachments", False), views=v.get("views", {}))
             for k, v in inv["lists"].items()}
    roles = sorted({r["group"] for r in inv.get("roles", []) if r.get("referenced")})
    return Spec(screen=screen, lists=lists, rules=rules, endpoints=list(endpoints.values()), roles=roles)
