"""Stage 4 gate: the spec may only be approved when it accounts for every 'must' behaviour.

Returns plain-language problems; the spec agent gets them back verbatim on retry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Optional

from .model import NEEDS_FIELD, NEEDS_MESSAGE, RULE_PARAMS, Spec

OPS = {"eq", "ne", "in", "nin", "gt", "gte", "lt", "lte", "empty", "notEmpty", "changed"}
COMPARE_OPS = {"eq", "ne", "gt", "gte", "lt", "lte"}
ENDPOINT_PATH = re.compile(r"^/api/[A-Za-z0-9_\-/{}.]+$")


@dataclass
class CoverageReport:
    ok: bool
    problems: list[str] = field(default_factory=list)
    covered: int = 0
    must: int = 0
    not_carried: int = 0
    matrix: list[dict] = field(default_factory=list)   # behavior -> what covers it

    def summary(self) -> str:
        return f"{self.covered}/{self.must} required behaviours covered ({self.not_carried} not carried, with reasons); {len(self.problems)} problem(s)"


def _norm(msg: str) -> str:
    m = re.sub(r"\{[^{}]*\}", "{}", msg or "")
    return re.sub(r"\s+", " ", m).strip()


def _condition_problems(cond: Any, fields: set[str], groups: set[str], where: str) -> list[str]:
    out = []
    if not isinstance(cond, dict) or not cond:
        return [f"{where}: condition must be a non-empty object"]
    keys = set(cond)
    if keys & {"all", "any"}:
        k = "all" if "all" in cond else "any"
        if not isinstance(cond[k], list) or not cond[k]:
            return [f"{where}: '{k}' needs a non-empty list"]
        for i, c in enumerate(cond[k]):
            out += _condition_problems(c, fields, groups, f"{where}.{k}[{i}]")
        return out
    if "not" in keys:
        return _condition_problems(cond["not"], fields, groups, f"{where}.not")
    if "role" in keys:
        if cond["role"] not in groups:
            out.append(f"{where}: role '{cond['role']}' is not one of the spec roles {sorted(groups)}")
        return out
    if "mode" in keys:
        ms = cond["mode"] if isinstance(cond["mode"], list) else [cond["mode"]]
        bad = [m for m in ms if m not in ("new", "edit", "display")]
        return [f"{where}: unknown mode {bad}"] if bad else []
    if "field" in keys:
        f = str(cond["field"]).split(".")[0]
        if f not in fields and f not in ("ID", "Author", "Editor", "Created", "Modified"):
            out.append(f"{where}: field '{cond['field']}' does not exist")
        ops = keys - {"field"}
        if not ops or not ops <= OPS:
            out.append(f"{where}: needs one operator from {sorted(OPS)}, got {sorted(ops)}")
        return out
    return [f"{where}: unknown condition shape {sorted(keys)} (use field/role/mode/all/any/not)"]


def check(spec: Spec, inv: dict) -> CoverageReport:
    problems: list[str] = []
    behaviors = {b["id"]: b for b in inv["behaviors"]}
    must = {k: b for k, b in behaviors.items() if b["level"] == "must"}
    covers = spec.all_covers()

    # 1. no invented ids
    for cid, by in covers.items():
        if cid not in behaviors:
            problems.append(f"{by[0]} covers '{cid}', which is not in the inventory. Use ids exactly as listed.")

    # 2. every must behaviour is accounted for
    matrix = []
    for bid, b in must.items():
        by = covers.get(bid, [])
        matrix.append({"behavior": bid, "kind": b["kind"], "covered_by": by})
        if not by:
            hint = f" message: \"{b['message']}\"" if b.get("message") else ""
            problems.append(f"Not covered: {bid} ({b['kind']}, `{b.get('code', '')[:90]}`){hint}")

    # 3. messages are carried verbatim by whatever covers the behaviour
    texts: list[str] = []

    def collect(v) -> None:
        if isinstance(v, str):
            texts.append(_norm(v))
        elif isinstance(v, dict):
            for x in v.values():
                collect(x)
        elif isinstance(v, list):
            for x in v:
                collect(x)

    for r in spec.rules:
        if r.message:
            texts.append(_norm(r.message))
        collect(r.params)
    for c in spec.screen.components:
        collect(c.props)
    not_carried_ids = {c for n in spec.not_carried for c in n.covers}
    for bid, b in must.items():
        if bid in not_carried_ids:
            continue
        msgs = [b["message"]] if b.get("message") else list((b.get("detail") or {}).get("messages", []))
        for m in msgs:
            if _norm(m) and _norm(m) not in texts:
                problems.append(f"Message from {bid} is not carried verbatim. Use exactly: \"{m}\" (placeholders like {{name}} may differ)")

    # 4. rules are well formed
    fields_by_list = {k: {f["name"] for f in v.fields} for k, v in spec.lists.items()}
    groups = set(spec.roles)
    ids = set()
    for r in spec.rules:
        where = f"rule {r.id}"
        if r.id in ids:
            problems.append(f"{where}: duplicate rule id")
        ids.add(r.id)
        lst = r.list or spec.screen.list
        flds = fields_by_list.get(lst or "", set())
        if r.kind in NEEDS_FIELD and not r.field:
            problems.append(f"{where}: kind '{r.kind}' needs 'field'")
        if r.field and r.field not in flds:
            problems.append(f"{where}: field '{r.field}' is not in list {lst}")
        for p in RULE_PARAMS.get(r.kind, ()):
            if p not in r.params:
                problems.append(f"{where}: kind '{r.kind}' needs params.{p}")
        if r.kind in NEEDS_MESSAGE and not r.message:
            problems.append(f"{where}: kind '{r.kind}' needs a message")
        if r.kind in ("compare",) and r.params.get("other") and r.params["other"] not in flds:
            problems.append(f"{where}: params.other '{r.params['other']}' is not in list {lst}")
        if r.kind in ("compare", "length", "range") and r.params.get("op") not in COMPARE_OPS:
            problems.append(f"{where}: params.op must be one of {sorted(COMPARE_OPS)}")
        if r.kind == "derive":
            src = r.params.get("from_field")
            if src not in flds:
                problems.append(f"{where}: params.from_field '{src}' is not in list {lst}")
            else:
                f = next(x for x in spec.lists[lst].fields if x["name"] == src)
                target = (f.get("lookup") or {}).get("list")
                if not target:
                    problems.append(f"{where}: params.from_field '{src}' must be a lookup field")
                elif target in spec.lists and r.params.get("column") not in fields_by_list[target]:
                    problems.append(f"{where}: params.column '{r.params.get('column')}' is not a field of {target}")
        if r.kind == "cascade":
            for p in ("parent",):
                if r.params.get(p) not in flds:
                    problems.append(f"{where}: params.{p} '{r.params.get(p)}' is not in list {lst}")
        if r.kind == "on_save":
            act = r.params.get("action")
            if not isinstance(act, dict) or act.get("type") not in ("create_item", "update_item", "custom"):
                problems.append(f"{where}: params.action must be an object with type create_item | update_item | custom")
            elif act.get("type") == "create_item" and act.get("list") not in spec.lists:
                problems.append(f"{where}: params.action.list '{act.get('list')}' is not one of the spec lists")
        if r.when is not None:
            problems += _condition_problems(r.when, flds, groups, f"{where}.when")
        if r.covers and not r.src and r.origin == "agent":
            problems.append(f"{where}: covers behaviours but has no src (file:line)")

    # 5. endpoints and components
    eids = set()
    for e in spec.endpoints:
        if e.id in eids:
            problems.append(f"endpoint {e.id}: duplicate id")
        eids.add(e.id)
        if not ENDPOINT_PATH.match(e.path):
            problems.append(f"endpoint {e.id}: path '{e.path}' must start with /api/ and contain only path characters")
        for g in e.roles:
            if g not in groups:
                problems.append(f"endpoint {e.id}: role '{g}' is not one of the spec roles")
    for c in spec.screen.components:
        for d in c.data:
            if d not in eids:
                problems.append(f"component {c.id}: data '{d}' is not an endpoint id")
        for g in c.roles:
            if g not in groups:
                problems.append(f"component {c.id}: role '{g}' is not one of the spec roles")
    for n in spec.not_carried:
        if len(n.reason.strip()) < 15:
            problems.append(f"not_carried {n.covers}: give a real reason (why the new app does not need it)")

    covered = sum(1 for m in matrix if m["covered_by"] and m["covered_by"] != ["not_carried"])
    nc = sum(1 for m in matrix if m["covered_by"] == ["not_carried"])
    return CoverageReport(ok=not problems, problems=problems, covered=covered + nc, must=len(must), not_carried=nc, matrix=matrix)
