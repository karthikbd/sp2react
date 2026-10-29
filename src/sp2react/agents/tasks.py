"""The concrete agents: what each one is given, and how its output is checked before it is accepted."""
from __future__ import annotations

import json
import py_compile
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Optional

from pydantic import ValidationError

from ..analysis.aspx import load_page
from ..analysis.inventory import Legacy
from ..spec.coverage import check
from ..spec.model import Spec
from .core import Agent, AgentResult

MAX_SOURCE_LINES = 3500
ALLOWED_PAGE_IMPORTS = {
    "react", "react-router-dom", "../../api", "../../runtime/user", "../../runtime/format", "../../runtime/spec",
    "../../runtime/rules", "../../components/sp/Layout", "../../components/sp/DataTable", "../../components/sp/Tiles",
    "../../components/sp/ListView", "../../components/sp/LegacyHtml", "../../components/sp/Banner",
}
FORBIDDEN_CODE = [(r"dangerouslySetInnerHTML", "use <LegacyHtml html=...> instead of dangerouslySetInnerHTML"),
                  (r"\bfetch\s*\(", "use the api client instead of fetch()"), (r"XMLHttpRequest", "use the api client"),
                  (r"\beval\s*\(", "eval is not allowed"), (r"(?<![\w.])\$\(", "jQuery is not available in the new app"),
                  (r"_spPageContextInfo", "use useUser() instead of _spPageContextInfo")]


# ----------------------------------------------------------------- helpers
def numbered(text: str, start: int = 1, only: Optional[set[int]] = None) -> str:
    out, last = [], None
    for i, line in enumerate(text.splitlines(), start):
        if only is not None and i not in only:
            continue
        if only is not None and last is not None and i != last + 1:
            out.append("   ...")
        out.append(f"{i:5d}| {line}")
        last = i
    return "\n".join(out)


def script_sources(legacy: Legacy, inv: dict, budget: int = MAX_SOURCE_LINES) -> str:
    texts: list[tuple[str, str]] = []
    for s in inv["scripts"]["custom"]:
        name = s["path"]
        if "#inline" in name:
            page, n = name.split("#inline")
            parsed = load_page(legacy.root, page)
            code = parsed.inline_scripts[int(n) - 1]["code"] if int(n) - 1 < len(parsed.inline_scripts) else ""
        else:
            code = legacy.file_text(name) or ""
        texts.append((name, code))
    total = sum(t.count("\n") + 1 for _, t in texts)
    lines_by_file: dict[str, set[int]] = {}
    if total > budget:  # keep windows around the behaviours only
        for b in inv["behaviors"]:
            if b.get("line"):
                lines_by_file.setdefault(b["file"], set()).update(range(max(1, b["line"] - 12), b["line"] + 13))
    parts = []
    for name, code in texts:
        only = lines_by_file.get(name) if total > budget else None
        modes = next((s.get("modes") for s in inv["scripts"]["custom"] if s["path"] == name), None)
        parts.append(f'<source file="{name}" loaded_on="{",".join(modes or []) or "page"}">\n{numbered(code, only=only)}\n</source>')
    return "\n".join(parts)


def compact_spec(spec: Spec) -> str:
    d = json.loads(spec.model_dump_json(exclude_none=True))
    for l in d["lists"].values():
        l["fields"] = [{k: f[k] for k in ("name", "label", "type", "required", "choices", "lookup", "default", "multi", "max_length", "read_only") if k in f}
                       for f in l["fields"]]
        l.pop("views", None)
    for c in d["screen"]["components"]:
        if "legacy_html" in c.get("props", {}):
            c["props"]["legacy_html"] = c["props"]["legacy_html"][:600]
    return json.dumps(d, indent=1)


def compact_behaviors(inv: dict) -> str:
    rows = []
    for b in inv["behaviors"]:
        r = {"id": b["id"], "level": b["level"], "kind": b["kind"], "code": b.get("code")}
        for k in ("function", "message", "condition"):
            if b.get(k):
                r[k] = b[k]
        if b.get("presave"):
            r["in"] = "PreSaveAction"
        if b.get("fields"):
            r["fields"] = [f["name"] if f["list"] == inv["screen"].get("list") else f"{f['list']}.{f['name']}" for f in b["fields"]]
        det = {k: v for k, v in (b.get("detail") or {}).items() if k in ("method", "url", "group", "messages", "presentation", "mode", "event",
                                                                          "operation", "spservices", "listName", "CAMLQuery", "relationshipList",
                                                                          "relationshipListParentColumn", "parentColumn", "childColumn", "ported", "list", "view_xml", "param")}
        if det:
            r["detail"] = det
        rows.append(json.dumps(r, ensure_ascii=False))
    return "\n".join(rows)


def merge_patch(base: Spec, patch: dict) -> Spec:
    d = json.loads(base.model_dump_json())
    base_ids = {r["id"] for r in d["rules"]}
    for r in patch.get("rules", []):
        if r.get("id") in base_ids:
            raise ValueError(f"rule id {r.get('id')} collides with a base rule; use R1, R2, ...")
    d["rules"] = d["rules"] + list(patch.get("rules", []))
    for key, target in (("components", d["screen"]["components"]), ("endpoints", d["endpoints"])):
        for item in patch.get(key, []):
            idx = next((i for i, x in enumerate(target) if x["id"] == item.get("id")), None)
            if idx is None:
                target.append(item)
            else:
                target[idx] = item
    d["not_carried"] = d.get("not_carried", []) + list(patch.get("not_carried", []))
    d["open_questions"] = d.get("open_questions", []) + list(patch.get("open_questions", []))
    return Spec.model_validate(d)


def _pydantic_problems(e: ValidationError) -> list[str]:
    return [f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors()[:40]]


def literal_chunks(message: str) -> list[str]:
    return [c.strip() for c in re.split(r"\{[^{}]*\}", message) if len(c.strip()) >= 8]


# -------------------------------------------------------------- spec agent
def run_spec_agent(agent: Agent, legacy: Legacy, inv: dict, base: Spec) -> tuple[Spec, AgentResult]:
    holder: dict[str, Spec] = {}

    def validate(patch: dict) -> list[str]:
        try:
            spec = merge_patch(base, patch)
        except ValidationError as e:
            return _pydantic_problems(e)
        except (ValueError, KeyError, TypeError) as e:
            return [str(e)]
        rep = check(spec, inv)
        if rep.ok:
            holder["spec"] = spec
        return rep.problems

    sections = {
        "screen_summary": f"Screen {inv['screen']['id']} ({inv['screen']['kind']}), pages: {', '.join(inv['screen']['pages'])}. "
                          f"Primary list: {inv['screen'].get('list') or 'none'}. Site: {inv['site'].get('title')}.",
        "base_spec": compact_spec(base),
        "behaviors": compact_behaviors(inv),
        "sources": script_sources(legacy, inv),
        "html_fragments": "\n".join(f'<fragment page="{f["page"]}" mode="{f.get("mode") or ""}" web_part="{f.get("web_part", "")}">\n{f["html"][:3000]}\n</fragment>'
                                    for f in inv.get("html_fragments", [])),
        "unresolved": "\n".join(f"- {u['kind']}: {u['detail']}" for u in inv.get("unresolved", [])),
    }
    res = agent.run(inv["screen"]["id"], sections, validate)
    return holder["spec"], res


# -------------------------------------------------------------- page agent
def ts_problems(out: Path, files: dict[str, str], timeout: int = 120) -> list[str]:
    """Type-check candidate files inside the generated frontend when its node_modules exist."""
    fe = out / "frontend"
    tsc = fe / "node_modules" / ".bin" / "tsc"
    if not tsc.exists():
        return []
    backups = {}
    try:
        for rel, content in files.items():
            p = out / rel
            backups[p] = p.read_text(encoding="utf-8") if p.exists() else None
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
        r = subprocess.run([str(tsc), "--noEmit", "-p", str(fe)], cwd=fe, capture_output=True, text=True, timeout=timeout)
        errs = []
        for line in r.stdout.splitlines():
            m = re.match(r"(src/[^(]+)\((\d+),(\d+)\): error (TS\d+): (.*)", line)
            if m and f"frontend/{m.group(1)}" in files:
                errs.append(f"{m.group(1)}:{m.group(2)}:{m.group(3)} {m.group(4)} {m.group(5)}")
        return errs[:30]
    finally:
        for p, old in backups.items():
            if old is None:
                p.unlink(missing_ok=True)
            else:
                p.write_text(old, encoding="utf-8")


def page_file_problems(files: dict[str, str], prefix: str, must_texts: list[str]) -> list[str]:
    problems = []
    if not any(p == f"{prefix}Page.tsx" for p in files):
        problems.append(f"Missing {prefix}Page.tsx")
    for path, code in files.items():
        if not path.startswith(prefix) or not path.endswith((".tsx", ".ts")):
            problems.append(f"{path}: files must be .ts/.tsx under {prefix}")
            continue
        for mod in re.findall(r"""from\s+["']([^"']+)["']""", code):
            if mod not in ALLOWED_PAGE_IMPORTS and not mod.startswith("./"):
                problems.append(f"{path}: import '{mod}' is not allowed (allowed: {sorted(ALLOWED_PAGE_IMPORTS)} or ./local files)")
        for pat, why in FORBIDDEN_CODE:
            if re.search(pat, code):
                problems.append(f"{path}: {why}")
        if code.count("{") != code.count("}") or code.count("(") != code.count(")"):
            problems.append(f"{path}: unbalanced braces/parentheses (file looks truncated)")
    page = files.get(f"{prefix}Page.tsx", "")
    if page and not re.search(r"export\s+default\s+function\s+Page\s*\(", page):
        problems.append(f"{prefix}Page.tsx must `export default function Page({{ spec }}: {{ spec: Spec }})`")
    allcode = "\n".join(files.values())
    for msg in must_texts:
        for chunk in literal_chunks(msg):
            if chunk not in allcode:
                problems.append(f"Legacy text missing or reworded: \"{chunk}\" (from \"{msg}\")")
    return problems


def run_page_agent(agent: Agent, legacy: Legacy, inv: dict, spec: Spec, routes: list[dict], out: Path) -> AgentResult:
    sid = spec.screen.id
    prefix = f"frontend/src/screens/{sid}/"
    dropped = {c for n in spec.not_carried for c in n.covers}
    must_texts = []
    for b in inv["behaviors"]:
        if b["level"] == "must" and b["id"] not in dropped:
            if b.get("message"):
                must_texts.append(b["message"])
            must_texts += (b.get("detail") or {}).get("messages", [])

    def validate(parsed: dict) -> list[str]:
        files = parsed["files"]
        probs = page_file_problems(files, prefix, must_texts)
        return probs or ts_problems(out, files)

    css = "\n".join(f"/* {rel} */\n{legacy.file_text(rel) or ''}" for rel in spec.screen.stylesheets)
    existing = out / prefix / "Page.tsx"
    sections = {
        "spec": compact_spec(spec),
        "routes": json.dumps(routes, indent=1),
        "legacy_html": "\n".join(f'<fragment web_part="{f.get("web_part", "")}">\n{f["html"]}\n</fragment>' for f in inv.get("html_fragments", [])),
        "legacy_css": css[:12000],
        "sources": script_sources(legacy, inv),
        "existing_file": existing.read_text(encoding="utf-8") if existing.exists() else "",
        "task": f"Write {prefix}Page.tsx for screen {sid} ('{spec.screen.title}').",
    }
    res = agent.run(sid, sections, validate)
    for rel, content in res.output["files"].items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return res


# ----------------------------------------------------------- handler agent
def run_handler_agent(agent: Agent, legacy: Legacy, inv: dict, spec: Spec, rule: Any, out: Path) -> AgentResult:
    handler = rule.params["handler"]
    allowed = {f"frontend/src/custom/{handler}.ts", f"backend/app/custom/{handler}.py"}

    def validate(parsed: dict) -> list[str]:
        probs = []
        for path, code in parsed["files"].items():
            if path not in allowed:
                probs.append(f"{path}: only {sorted(allowed)} may be written")
            elif path.endswith(".py"):
                with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as t:
                    t.write(code)
                try:
                    py_compile.compile(t.name, doraise=True)
                except py_compile.PyCompileError as e:
                    probs.append(f"{path}: {e.msg}")
            else:
                for mod in re.findall(r"""from\s+["']([^"']+)["']""", code):
                    if mod not in ("../runtime/rules", "../api", "../runtime/spec"):
                        probs.append(f"{path}: import '{mod}' is not allowed")
        return probs or ts_problems(out, {p: c for p, c in parsed["files"].items() if p.endswith(".ts")})

    sections = {"rule": rule.model_dump_json(indent=1, exclude_none=True), "spec": compact_spec(spec),
                "behaviors": compact_behaviors({**inv, "behaviors": [b for b in inv["behaviors"] if b["id"] in rule.covers]}),
                "sources": script_sources(legacy, inv)}
    res = agent.run(f"{spec.screen.id}-{handler}", sections, validate)
    for rel, content in res.output["files"].items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_text(content, encoding="utf-8")
    return res


# ------------------------------------------------------------ review agent
def run_review_agent(agent: Agent, legacy: Legacy, inv: dict, spec: Spec, out: Path) -> AgentResult:
    def validate(r: dict) -> list[str]:
        probs = []
        if r.get("verdict") not in ("pass", "fail"):
            probs.append("verdict must be 'pass' or 'fail'")
        if not isinstance(r.get("findings"), list):
            probs.append("findings must be a list")
        else:
            for i, f in enumerate(r["findings"]):
                if f.get("severity") not in ("blocker", "major", "minor"):
                    probs.append(f"findings[{i}].severity must be blocker|major|minor")
                if not f.get("problem"):
                    probs.append(f"findings[{i}] needs a problem description")
            if r.get("verdict") == "pass" and any(f.get("severity") in ("blocker", "major") for f in r["findings"]):
                probs.append("verdict cannot be 'pass' with blocker/major findings")
        return probs

    code = []
    sid = spec.screen.id
    for p in sorted((out / "frontend" / "src" / "screens" / sid).glob("*.ts*")) if (out / "frontend" / "src" / "screens" / sid).exists() else []:
        code.append(f'<file path="{p.relative_to(out).as_posix()}">\n{p.read_text(encoding="utf-8")}\n</file>')
    for r in spec.rules:
        if r.kind == "custom":
            for rel in (f"frontend/src/custom/{r.params['handler']}.ts", f"backend/app/custom/{r.params['handler']}.py"):
                if (out / rel).exists():
                    code.append(f'<file path="{rel}">\n{(out / rel).read_text(encoding="utf-8")}\n</file>')
    sections = {"behaviors": compact_behaviors(inv), "spec": spec.model_dump_json(indent=1, exclude_none=True),
                "sources": script_sources(legacy, inv), "generated_code": "\n".join(code),
                "note": "List forms are rendered by the shared form engine directly from the spec rules; review the rules for them."}
    return agent.run(sid, sections, validate)


# --------------------------------------------------------------- fix agent
def run_fix_agent(agent: Agent, inv: dict, spec: Spec, failures: str, out: Path, task_id: str) -> tuple[AgentResult, Optional[Spec]]:
    sid = spec.screen.id
    editable = {p.relative_to(out).as_posix() for p in (out / "frontend" / "src" / "screens" / sid).glob("*.ts*")} if (out / "frontend" / "src" / "screens" / sid).exists() else set()
    for r in spec.rules:
        if r.kind == "custom":
            editable |= {f"frontend/src/custom/{r.params['handler']}.ts", f"backend/app/custom/{r.params['handler']}.py"}
    holder: dict = {}

    def validate(parsed: dict) -> list[str]:
        probs = [f"{p}: not an editable file (editable: {sorted(editable)})" for p in parsed["files"] if p not in editable]
        if parsed.get("spec_patch"):
            patch = parsed["spec_patch"]
            d = json.loads(spec.model_dump_json())
            by_id = {r["id"]: i for i, r in enumerate(d["rules"])}
            for r in patch.get("rules", []):
                if r.get("id") in by_id:
                    d["rules"][by_id[r["id"]]] = r
                else:
                    d["rules"].append(r)
            try:
                new = Spec.model_validate(d)
            except ValidationError as e:
                return probs + _pydantic_problems(e)
            rep = check(new, inv)
            probs += rep.problems
            holder["spec"] = new
        if not probs and parsed["files"]:
            probs += ts_problems(out, {p: c for p, c in parsed["files"].items() if p.endswith((".ts", ".tsx"))})
        return probs

    files = "\n".join(f'<file path="{p}">\n{(out / p).read_text(encoding="utf-8")}\n</file>' for p in sorted(editable) if (out / p).exists())
    sections = {"failures": failures[-12000:], "files": files, "spec": compact_spec(spec)}
    res = agent.run(task_id, sections, validate)
    for rel, content in res.output["files"].items():
        (out / rel).write_text(content, encoding="utf-8")
    return res, holder.get("spec")


# ------------------------------------------------------------- dbmap agent
def run_dbmap_agent(agent: Agent, lists: dict, db: dict, draft_mapping: dict, notes: list[str]) -> tuple[dict, list[str], AgentResult]:
    from ..dbmap import validate as validate_mapping
    holder: dict = {}

    def validate(out: dict) -> list[str]:
        m = out.get("mapping")
        if not isinstance(m, dict) or "lists" not in m:
            return ['Return {"mapping": {...}, "notes": [...]} with mapping.lists']
        problems, _ = validate_mapping(m, lists, db)
        if not problems:
            holder["mapping"] = m
        return problems

    compact_lists = {k: {"title": v["title"], "fields": [{x: f.get(x) for x in ("name", "label", "type", "required", "multi", "lookup") if f.get(x) is not None}
                                                         for f in v["fields"]]} for k, v in lists.items()}
    sections = {"sharepoint_lists": json.dumps(compact_lists, indent=1), "database_schema": json.dumps(db["tables"], indent=1),
                "draft_mapping": json.dumps(draft_mapping, indent=1), "unresolved": "\n".join(f"- {n}" for n in notes)}
    res = agent.run("db-mapping", sections, validate)
    return holder["mapping"], list(res.output.get("notes") or []), res
