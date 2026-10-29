"""Find what custom JavaScript does to a SharePoint form/page, with source line references.

Every finding is a Behavior. Behaviors with level "must" have to be accounted for in the spec
(covered by a rule/endpoint/component, or explicitly listed as not carried, with a reason);
"info" findings are context for the agents.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Optional
from urllib.parse import unquote

from .jsscan import Scan, concat_expressions, enclosing_call, if_condition, object_props, scan, template

MUST = "must"
INFO = "info"

LIBRARY_HINTS = re.compile(
    r"(jquery|spservices|bootstrap|moment|datatables|knockout|underscore|lodash|angular|select2|chosen|handlebars|"
    r"require|es5-shim|json2|popper|tether|fontawesome|font-awesome|chart(\.min)?\.js|d3(\.min)?\.js|vue|react)[\w.\-]*\.js$", re.I)
LIBRARY_HEADER = re.compile(r"^\s*/\*[!*]?\s*(jQuery|SPServices|Bootstrap|Moment|DataTables|Knockout|Underscore|lodash|AngularJS|Select2|@license)", re.I | re.M)
SHAREPOINT_BUILTIN = re.compile(r"(^|/)(_layouts|_vti_bin)/|scriptresource\.axd|webresource\.axd|^(sp|init|core|clienttemplates|clientforms|clientpeoplepicker|autofill|sp\.runtime|sp\.core|sp\.ui\.\w+|callout|inplview|menu|strings|initstrings|blank|mquery|sp\.init|ms\.rte|SP\.UI\.Dialog)\.js$", re.I)


def classify_script(url: str, text: Optional[str] = None) -> str:
    """sharepoint | library | external | custom"""
    path = url.split("?")[0]
    name = path.rsplit("/", 1)[-1]
    if SHAREPOINT_BUILTIN.search(path) or SHAREPOINT_BUILTIN.search(name):
        return "sharepoint"
    if LIBRARY_HINTS.search(name) or (text and LIBRARY_HEADER.search(text[:600])):
        return "library"
    if path.startswith(("http://", "https://", "//")):
        return "external"
    return "custom"


@dataclass
class FieldRef:
    list: str
    name: str
    label: str


@dataclass
class Behavior:
    id: str
    kind: str
    level: str
    file: str
    line: int
    code: str
    function: Optional[str] = None
    presave: bool = False
    fields: list[FieldRef] = field(default_factory=list)
    message: Optional[str] = None
    condition: Optional[str] = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        d = asdict(self)
        return {k: v for k, v in d.items() if v not in (None, [], {}, False) or k in ("id", "kind", "level", "file", "line")}


class FieldIndex:
    """Resolve string literals to list fields by display name or internal name."""

    def __init__(self):
        self.by_label: dict[str, list[FieldRef]] = {}
        self.by_name: dict[str, list[FieldRef]] = {}
        self.list_titles: dict[str, str] = {}   # list title -> list key

    def add_list(self, key: str, title: str, fields: list[dict]) -> None:
        self.list_titles[title.lower()] = key
        for f in fields:
            ref = FieldRef(key, f["name"], f["label"])
            self.by_label.setdefault(f["label"].lower(), []).append(ref)
            self.by_name.setdefault(f["name"].lower(), []).append(ref)

    def resolve(self, text: str, prefer: Optional[str] = None, internal_ok: bool = False) -> list[FieldRef]:
        t = re.sub(r"\s+Required Field$", "", text.strip(), flags=re.I).lower()
        refs = self.by_label.get(t) or (self.by_name.get(t) if internal_ok else None) or []
        if prefer and len(refs) > 1:
            pref = [r for r in refs if r.list == prefer]
            refs = pref or refs
        return refs[:1] if prefer and refs and refs[0].list == prefer else refs[:1]


SELECTOR_FIELD = re.compile(r"""\[\s*title\s*[*^$]?=\s*['"]?([^'"\]]+)['"]?\s*\]|:contains\(\s*['"]?([^'")]+)['"]?\s*\)""", re.I)
EVENT = re.compile(r"\.(change|blur|click|keyup|keydown|focusout|input|dblclick|submit)\s*\(|\.on\(\s*__S(\d+)__")
VISIBILITY = re.compile(r"\.(toggle|hide|show|fadeIn|fadeOut|slideUp|slideDown|slideToggle)\s*\(|\.css\(\s*__S\d+__\s*,\s*__S\d+__")
READONLY = re.compile(r"\.(prop|attr)\(\s*__S(\d+)__\s*,|\b[\w.$]*(lock|disable|readonly|readOnly|makeReadOnly)[\w$]*\s*\(", re.I)
SETVAL = re.compile(r"\.val\(\s*(?!\))")
MESSAGE_CALL = re.compile(r"\b(alert|confirm)\s*\(")
NAVIGATE = re.compile(r"\b(?:window\.)?location(?:\.href)?\s*=(?!=)|\blocation\.(?:replace|assign)\s*\(|\bwindow\.open\s*\(|\bSTSNavigate\s*\(|\bSP\.UI\.ModalDialog\.\w+\s*\(")
QUERY_PARAM = re.compile(r"\bGetUrlKeyValue\(\s*__S(\d+)__")
SPSERVICES = re.compile(r"\$\(\)\.SPServices(?:\.(\w+))?\s*\(")
CONTEXT = re.compile(r"_spPageContextInfo\.(\w+)")


def _labels_in_selectors(scan_: Scan, line_code: str) -> list[str]:
    out = []
    for lit in scan_.literals_in(line_code):
        for m in SELECTOR_FIELD.finditer(lit.value):
            out.append(m.group(1) or m.group(2))
    return out


def analyze_script(name: str, source: str, index: FieldIndex, prefer_list: Optional[str] = None) -> tuple[list[Behavior], list[dict]]:
    """-> (behaviors, calls). Calls are REST/SPServices invocations with parsed detail."""
    s = scan(source)
    behaviors: list[Behavior] = []
    ids: dict[str, int] = {}

    def add(kind: str, level: str, line: int, offset: int, **kw) -> Behavior:
        base = f"{name}#L{line}:{kind}"
        ids[base] = ids.get(base, 0) + 1
        bid = base if ids[base] == 1 else f"{base}.{ids[base]}"
        encl = s.enclosing(offset)
        b = Behavior(id=bid, kind=kind, level=level, file=name, line=line,
                     code=(s.lines[line - 1].strip() if line - 1 < len(s.lines) else "")[:220],
                     function=encl[-1].name if encl else None,
                     presave=any(f.name in ("PreSaveAction", "PreSaveItem") for f in encl), **kw)
        behaviors.append(b)
        return b

    # variables that hold a field row/control, e.g. `var row = VR.getFieldRow("High Risk Justification")`
    var_fields: dict[str, list[FieldRef]] = {}
    for var, (expr, _) in s.assignments.items():
        refs = []
        for lit in s.literals_in(expr):
            refs += index.resolve(lit.value, prefer_list)
        for label in _labels_in_selectors(s, expr):
            refs += index.resolve(label, prefer_list)
        if refs:
            var_fields[var] = refs

    def fields_on(line_code: str) -> list[FieldRef]:
        refs: list[FieldRef] = []
        for lit in s.literals_in(line_code):
            refs += index.resolve(lit.value, prefer_list)
        for label in _labels_in_selectors(s, line_code):
            refs += index.resolve(label, prefer_list)
        for var, vrefs in var_fields.items():
            if re.search(rf"(?<![\w$.]){re.escape(var)}(?![\w$])", line_code) and not re.search(rf"\b(var|let|const)\s+{re.escape(var)}\b", line_code):
                refs += vrefs
        seen, out = set(), []
        for r in refs:
            if (r.list, r.name) not in seen:
                seen.add((r.list, r.name))
                out.append(r)
        return out

    offsets = [0]
    for ln in s.code_lines:
        offsets.append(offsets[-1] + len(ln) + 1)

    helper_funcs = {f.name for f in s.functions}

    for i, line_code in enumerate(s.code_lines, start=1):
        if not line_code.strip():
            continue
        off = offsets[i - 1]
        flds = fields_on(line_code)

        # function definitions of known SharePoint hooks
        if re.search(r"\bfunction\s+(PreSaveAction|PreSaveItem)\s*\(", line_code):
            add("presave_hook", INFO, i, off, detail={"hook": "PreSaveAction"})

        m = EVENT.search(line_code)
        if m and flds:
            ev = m.group(1) or (s.literals[int(m.group(2))].value if m.group(2) else "on")
            add("event", INFO, i, off, fields=flds, detail={"event": ev})

        if VISIBILITY.search(line_code):
            add("visibility", MUST if flds else INFO, i, off, fields=flds,
                condition=if_condition(s, off + len(line_code) - len(line_code.lstrip())))

        rm = READONLY.search(line_code)
        if rm:
            prop = s.literals[int(rm.group(2))].value.lower() if rm.group(2) else ""
            if rm.group(3) or prop in ("disabled", "readonly", "contenteditable"):
                # a helper called with a field literal is the behaviour; the helper's own body is "info"
                add("readonly", MUST if flds else INFO, i, off, fields=flds)

        if SETVAL.search(line_code) and flds and not re.search(r"\.val\(\s*\)", line_code):
            if re.search(r"\$\(", line_code):
                add("set_value", MUST, i, off, fields=flds, condition=if_condition(s, off + 1),
                    detail={"value": s.restore(line_code.split(".val(", 1)[1].rsplit(")", 1)[0]).strip()})

        mm = MESSAGE_CALL.search(line_code)
        if mm:
            call = enclosing_call(s, off + mm.end(), r"\b" + mm.group(1))
            text = template(s, call[2]) if call else None
            options = []
            if call and ("?" in call[2] or "||" in call[2]):
                options = [l.value for l in s.literals_in(call[2]) if len(l.value) > 10]
                text = None if options else text
            kind = "save_validation" if (s.enclosing(off) and any(f.name in ("PreSaveAction", "PreSaveItem") for f in s.enclosing(off))
                                          and mm.group(1) == "alert") else ("confirm" if mm.group(1) == "confirm" else "message")
            add(kind, MUST, i, off + mm.start(), fields=flds, message=text, condition=if_condition(s, off + mm.start()),
                detail={"presentation": mm.group(1), **({"messages": options} if options else {})})

        for lit in s.literals_in(line_code):
            if "ms-formvalidation" in lit.value or "ms-error" in lit.value:
                pos = off + line_code.find(f"__S{lit.index}__")
                cands = [(en - st, c) for (st, en, c) in concat_expressions(s) if st <= pos < en and not re.match(r"[\w$.]*\$\(", c)]
                expr = min(cands)[1] if cands else None
                txt = re.sub(r"<[^>]+>", "", template(s, expr)) if expr else re.sub(r"<[^>]+>", "", lit.value)
                add("message", MUST, i, off, fields=flds, message=txt.strip(), condition=if_condition(s, off + 1),
                    detail={"presentation": "inline"})
                break
        tm = re.search(r"\.(text|html)\(\s*(__S\d+__(?:\s*\+[^)]*)?)\)", line_code)
        if tm and not flds:
            txt = re.sub(r"<[^>]+>", "", template(s, tm.group(2))).strip()
            if len(txt) > 15 and " " in txt and not txt.lower().startswith(("loading", "<")):
                add("message", MUST, i, off, message=txt, condition=if_condition(s, off + 1), detail={"presentation": "banner"})

        if NAVIGATE.search(line_code):
            add("navigate", MUST, i, off, condition=if_condition(s, off + 1), detail={"target": s.restore(line_code.strip())[:200]})

        for q in QUERY_PARAM.finditer(line_code):
            add("query_param", INFO, i, off, detail={"param": s.literals[int(q.group(1))].value})

        for lit in s.literals_in(line_code):
            g = re.search(r"Group\[Name=['\"]?([^'\"\]]+)", lit.value)
            if g:
                add("role_check", MUST, i, off, detail={"group": g.group(1)})
            if re.search(r"(new|edit|disp)form\.aspx", lit.value, re.I):
                add("mode_check", INFO, i, off, detail={"form": lit.value})

        for c in CONTEXT.finditer(line_code):
            add("context", INFO, i, off, detail={"property": c.group(1)})

    # ---------------------------------------------------------------- calls
    calls: list[dict] = []
    seen_urls = set()
    for st, en, expr in concat_expressions(s):
        url = template(s, expr)
        if "/_api/" not in url and "_vti_bin" not in url:
            continue
        line = s.line_of(st)
        parsed = parse_rest_url(url)
        if parsed.get("resource") in ("list",) and not parsed.get("item") and parsed.get("op") is None and not parsed.get("query"):
            continue   # base URL definition such as `listUrl = site + "/_api/web/lists/getbytitle('X')"`
        fn = (s.enclosing(st)[-1].name if s.enclosing(st) else None)
        key = (url, fn)
        if key in seen_urls:
            continue
        seen_urls.add(key)
        method, body = "GET", {}
        ajax = enclosing_call(s, st, r"(?:\$|jQuery)\.ajax")
        if ajax:
            props = {k: s.restore(v) for k, v in object_props(s, ajax[2]).items()}
            t = props.get("type") or props.get("method")
            if t:
                method = t.strip("'\" ").upper()
            hdrs = props.get("headers", "")
            xm = re.search(r"X-HTTP-Method['\"]?\s*:\s*['\"](\w+)", hdrs, re.I)
            if xm:
                method = xm.group(1).upper()
            if "IF-MATCH" in hdrs.upper():
                body["if_match"] = True
            data_masked = object_props(s, ajax[2]).get("data", "")
            obj = re.search(r"\{.*\}", data_masked, re.S)
            body["fields"] = [k for k in (object_props(s, obj.group(0)).keys() if obj else []) if k not in ("__metadata", "type")]
        level_kind = "rest_call"
        b = add(level_kind, MUST, line, st, fields=_fields_from_query(parsed, index, body.get("fields", [])),
                detail={"method": method, "url": url, **parsed, **({"body": body} if body.get("fields") else {}),
                        **({"if_match": True} if body.get("if_match") else {})})
        calls.append({"behavior": b.id, "type": "rest", "method": method, "url": url, **parsed, "line": line, "function": fn,
                      **({"body_fields": body["fields"]} if body.get("fields") else {})})

    for m in SPSERVICES.finditer(s.code):
        open_p = m.end() - 1
        from .jsscan import match_brace
        close_p = match_brace(s.code, open_p)
        args = s.code[open_p + 1:close_p]
        props = {k: (s.lit(v).value if s.lit(v) else s.restore(v)) for k, v in object_props(s, args).items()} if args.strip().startswith("{") else {}
        sub = m.group(1) or "call"
        op = props.get("operation") or sub
        line = s.line_of(m.start())
        if sub in ("SPGetCurrentUser",) or op == "SPGetCurrentUser":
            continue
        kind = {"SPCascadeDropdowns": "cascade", "SPFindPeoplePicker": "default_value"}.get(sub, "spservices_call")
        flds = []
        for key in ("parentColumn", "childColumn", "peoplePickerDisplayName", "columnName"):
            if key in props:
                flds += index.resolve(props[key], prefer_list)
        for key in ("CAMLQuery", "CAMLViewFields"):
            if key in props:
                for fr in re.findall(r"FieldRef\s+Name=['\"](\w+)['\"]", props[key]):
                    lst = index.list_titles.get((props.get("listName") or "").lower())
                    flds += index.resolve(fr, lst, internal_ok=True)
        b = add(kind, MUST, line, m.start(), fields=flds, detail={"spservices": sub, "operation": op, **{k: v for k, v in props.items() if k not in ("completefunc",)}})
        calls.append({"behavior": b.id, "type": "spservices", "operation": op, "function": sub, "line": line,
                      **{k: v for k, v in props.items() if k in ("listName", "CAMLQuery", "CAMLViewFields", "CAMLRowLimit", "webURL",
                                                                   "relationshipList", "parentColumn", "childColumn")}})
    behaviors.sort(key=lambda b: (b.line, b.id))
    return behaviors, calls


def _fields_from_query(parsed: dict, index: FieldIndex, body_fields: list[str]) -> list[FieldRef]:
    lst = index.list_titles.get((parsed.get("list") or "").lower())
    names = set(body_fields)
    q = parsed.get("query", {})
    for k in ("$select", "$filter", "$orderby", "$expand"):
        names |= set(re.findall(r"\b([A-Za-z_]\w*)", q.get(k, "")))
    out, seen = [], set()
    for n in names:
        base = re.sub(r"Id$", "", n)
        for cand in (n, base):
            refs = index.resolve(cand, lst, internal_ok=True)
            if refs and refs[0].list == lst and (refs[0].list, refs[0].name) not in seen:
                seen.add((refs[0].list, refs[0].name))
                out.append(refs[0])
                break
    return sorted(out, key=lambda r: r.name)


def parse_rest_url(url: str) -> dict:
    out: dict = {}
    path, _, qs = url.partition("?")
    m = re.search(r"getbytitle\(\s*'((?:[^']|'')+)'\s*\)", path, re.I)
    if m:
        out["resource"] = "list"
        out["list"] = m.group(1).replace("''", "'")
    m2 = re.search(r"lists\(\s*guid'([^']+)'\s*\)", path, re.I)
    if m2:
        out["resource"] = "list"
        out["list_id"] = m2.group(1)
    if re.search(r"/_api/web/(currentuser|siteusers|sitegroups)", path, re.I):
        out["resource"] = "user"
    if re.search(r"/_api/(SP\.UserProfiles|sp\.userprofiles)", path, re.I):
        out["resource"] = "userprofile"
    if re.search(r"/_api/search/", path, re.I):
        out["resource"] = "search"
    if "_vti_bin" in path:
        out["resource"] = "soap"
    mi = re.search(r"/items\(\s*([^)]*)\)", path)
    if mi:
        out["item"] = mi.group(1)
    elif re.search(r"/items/?$", path):
        out["op"] = "items"
    tail = re.search(r"/items\([^)]*\)/(\w+)", path)
    if tail:
        out["op"] = tail.group(1)  # AttachmentFiles, FieldValuesAsText...
    if re.search(r"/items/?$", path) and "item" not in out:
        out["op"] = "items"
    if qs:
        q = {}
        for part in re.split(r"&(?=\$)", qs):
            k, _, v = part.partition("=")
            q[k] = unquote(v)
        out["query"] = q
    return out
