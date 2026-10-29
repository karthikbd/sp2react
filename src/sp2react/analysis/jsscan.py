"""Lightweight JavaScript scanning for legacy SharePoint customisations.

Not a full parser: it tokenises strings/comments/regex literals well enough to
  * know every string literal and its line,
  * mask strings so structural regexes (braces, '+', ';') are safe,
  * find function ranges, simple variable assignments and `$.ajax({...})` blocks,
  * rebuild string-concatenation expressions as templates: "{VR.siteUrl}/_api/...(" + id + ")" -> "{VR.siteUrl}/_api/...({id})".
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

REGEX_PRECEDERS = set("(,=:[!&|?{};+-*%<>~^") | {""}
REGEX_KEYWORDS = {"return", "typeof", "case", "do", "else", "in", "of", "new", "delete", "void", "throw"}


@dataclass
class Literal:
    index: int
    value: str
    start: int
    end: int
    line: int


@dataclass
class FuncRange:
    name: str
    start: int       # offset of the opening brace in code
    end: int         # offset of the closing brace
    line_start: int
    line_end: int


@dataclass
class Scan:
    source: str
    code: str                      # strings -> __S<n>__ placeholders, comments -> spaces; newlines preserved
    literals: list[Literal]
    lines: list[str]               # original source lines
    code_lines: list[str]
    functions: list[FuncRange] = field(default_factory=list)
    assignments: dict[str, tuple[str, int]] = field(default_factory=dict)  # name -> (code expr, line)

    def line_of(self, code_offset: int) -> int:
        return self.code.count("\n", 0, code_offset) + 1

    def lit(self, placeholder: str) -> Optional[Literal]:
        m = re.fullmatch(r"__S(\d+)__", placeholder.strip())
        return self.literals[int(m.group(1))] if m else None

    def literals_in(self, code_fragment: str) -> list[Literal]:
        return [self.literals[int(i)] for i in re.findall(r"__S(\d+)__", code_fragment)]

    def restore(self, code_fragment: str) -> str:
        return re.sub(r"__S(\d+)__", lambda m: _quote(self.literals[int(m.group(1))].value), code_fragment)

    def enclosing(self, code_offset: int) -> list[FuncRange]:
        """Functions containing the offset, innermost last."""
        return sorted((f for f in self.functions if f.start <= code_offset <= f.end), key=lambda f: f.start)


def _quote(v: str) -> str:
    return '"' + v.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _unescape(raw: str) -> str:
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == "\\" and i + 1 < len(raw):
            n = raw[i + 1]
            out.append({"n": "\n", "t": "\t", "r": "\r", "'": "'", '"': '"', "\\": "\\", "/": "/"}.get(n, n))
            i += 2
            continue
        out.append(c)
        i += 1
    return "".join(out)


def tokenize(src: str) -> tuple[str, list[Literal]]:
    code: list[str] = []
    lits: list[Literal] = []
    i, n, line = 0, len(src), 1
    prev_sig = ""            # last significant code char (for regex detection)
    prev_word = ""
    while i < n:
        c = src[i]
        if c == "\n":
            code.append(c)
            line += 1
            i += 1
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            j = n if j == -1 else j
            code.append(" " * (j - i))
            i = j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            j = src.find("*/", i + 2)
            j = n if j == -1 else j + 2
            chunk = src[i:j]
            code.append(re.sub(r"[^\n]", " ", chunk))
            line += chunk.count("\n")
            i = j
            continue
        if c in "'\"`":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    buf.append(src[j:j + 2])
                    j += 2
                    continue
                if src[j] == "\n" and c != "`":
                    break
                buf.append(src[j])
                j += 1
            raw = "".join(buf)
            idx = len(lits)
            lits.append(Literal(idx, _unescape(raw), i, j + 1, line))
            nl = raw.count("\n")
            code.append(f"__S{idx}__" + "\n" * nl)
            line += nl
            i = j + 1
            prev_sig, prev_word = "s", ""
            continue
        if c == "/" and (prev_sig in REGEX_PRECEDERS or prev_word in REGEX_KEYWORDS):
            # regex literal: skip to the closing unescaped slash (respecting [...] classes)
            j, in_class = i + 1, False
            while j < n and src[j] != "\n":
                ch = src[j]
                if ch == "\\":
                    j += 2
                    continue
                if ch == "[":
                    in_class = True
                elif ch == "]":
                    in_class = False
                elif ch == "/" and not in_class:
                    break
                j += 1
            j += 1
            while j < n and src[j].isalpha():
                j += 1
            code.append("_RE_" + " " * max(0, (j - i) - 4) if (j - i) >= 4 else "_RE_")
            i = j
            prev_sig, prev_word = "r", ""
            continue
        code.append(c)
        if not c.isspace():
            if c.isalnum() or c in "_$":
                m = re.match(r"[\w$]+", src[i:])
                word = m.group(0)
                code.append(word[1:])
                i += len(word)
                prev_sig, prev_word = "w", word
                continue
            prev_sig, prev_word = c, ""
        i += 1
    return "".join(code), lits


def match_brace(code: str, open_pos: int) -> int:
    """Offset of the bracket closing the one at open_pos (code is already string-masked)."""
    pairs = {"{": "}", "(": ")", "[": "]"}
    opener = code[open_pos]
    closer = pairs[opener]
    depth = 0
    for k in range(open_pos, len(code)):
        ch = code[k]
        if ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return k
    return len(code) - 1


FUNC_PATTERNS = [
    re.compile(r"\bfunction\s+([\w$]+)\s*\([^)]*\)\s*\{"),
    re.compile(r"([\w$.]+)\s*[:=]\s*function\s*[\w$]*\s*\([^)]*\)\s*\{"),
    re.compile(r"\$\(\s*document\s*\)\s*\.ready\s*\(\s*function\s*\([^)]*\)\s*\{"),
    re.compile(r"(?<![\w.])(?:\$|jQuery)\(\s*function\s*\([^)]*\)\s*\{"),
    re.compile(r"\b(_spBodyOnLoadFunctionNames)\.push"),
]


def scan(source: str) -> Scan:
    code, lits = tokenize(source)
    s = Scan(source=source, code=code, literals=lits, lines=source.splitlines(), code_lines=code.split("\n"))
    for pat in FUNC_PATTERNS[:4]:
        for m in pat.finditer(code):
            brace = code.rfind("{", m.start(), m.end())
            if brace < 0:
                continue
            end = match_brace(code, brace)
            name = m.group(1) if m.groups() and m.group(1) else "document.ready"
            s.functions.append(FuncRange(name, brace, end, s.line_of(brace), s.line_of(end)))
    # simple assignments: name = <expr>;   (expr on masked code, may span lines)
    for m in re.finditer(r"(?:\b(?:var|let|const)\s+)?([\w$]+(?:\.[\w$]+)*)\s*=(?!=)\s*([^;{}]+?);", code):
        name, expr = m.group(1), m.group(2).strip()
        if name in ("if", "for", "while", "return"):
            continue
        s.assignments.setdefault(name, (expr, s.line_of(m.start())))
    return s


# ------------------------------------------------------------ expressions
_ARGS = r"\((?:[^(){}]|\([^(){}]*\))*\)"
OPERAND = rf"(?:__S\d+__|[\w$]+(?:\.[\w$]+)*(?:{_ARGS})?(?:\.[\w$]+(?:{_ARGS})?)*)"
CONCAT = re.compile(rf"{OPERAND}(?:\s*\+\s*{OPERAND})*")


def split_plus(expr: str) -> list[str]:
    parts, depth, cur = [], 0, []
    for ch in expr:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "+" and depth == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    parts.append("".join(cur))
    return [p.strip() for p in parts if p.strip()]


def template(scan_: Scan, expr: str, depth: int = 0) -> str:
    """Rebuild a concatenation as text with {placeholders}; substitutes known variable templates."""
    out = []
    for part in split_plus(expr):
        lit = scan_.lit(part)
        if lit is not None:
            out.append(lit.value)
            continue
        name = part.strip("() ")
        if depth < 4 and name in scan_.assignments and re.fullmatch(r"[\w$.]+", name):
            sub = scan_.assignments[name][0]
            if "__S" in sub:
                rendered = template(scan_, sub, depth + 1)
                if re.search(r"[/?&]", rendered):      # only inline URL-like fragments, keep other vars as {name}
                    out.append(rendered)
                    continue
        out.append("{" + scan_.restore(part) + "}")
    return "".join(out)


def concat_expressions(scan_: Scan) -> list[tuple[int, int, str]]:
    """All maximal concatenation expressions, including those nested in call arguments: (start, end, code)."""
    out: list[tuple[int, int, str]] = []

    def walk(text: str, base: int, depth: int) -> None:
        for m in CONCAT.finditer(text):
            frag = m.group(0)
            if "+" in frag or "__S" in frag or "." in frag:
                out.append((base + m.start(), base + m.end(), frag))
            if depth < 4:
                for a in re.finditer(r"\(", frag):
                    close = match_brace(frag, a.start())
                    inner = frag[a.start() + 1:close]
                    if "+" in inner or "__S" in inner:
                        walk(inner, base + m.start() + a.start() + 1, depth + 1)

    walk(scan_.code, 0, 0)
    return out


def enclosing_call(scan_: Scan, offset: int, callee_pattern: str) -> Optional[tuple[int, int, str]]:
    """Innermost call like `$.ajax(` whose parentheses contain offset -> (start, end, code of args)."""
    best = None
    for m in re.finditer(callee_pattern + r"\s*\(", scan_.code[:offset]):
        open_pos = m.end() - 1
        close = match_brace(scan_.code, open_pos)
        if open_pos < offset <= close:
            best = (open_pos, close, scan_.code[open_pos + 1:close])
    return best


def object_props(scan_: Scan, obj_code: str) -> dict[str, str]:
    """Top-level `key: value` pairs of an object literal (values returned as restored source)."""
    body = obj_code.strip()
    if body.startswith("{"):
        body = body[1:body.rfind("}")]
    props, depth, cur = {}, 0, []
    chunks = []
    for ch in body:
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        if ch == "," and depth == 0:
            chunks.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    chunks.append("".join(cur))
    for c in chunks:
        m = re.match(r"\s*(__S\d+__|[\w$]+)\s*:\s*(.*)$", c, re.S)
        if not m:
            continue
        key = m.group(1)
        lit = scan_.lit(key)
        props[lit.value if lit else key] = m.group(2).strip()
    return props


def if_condition(scan_: Scan, offset: int) -> Optional[str]:
    """Condition of the innermost `if (...) {` block containing offset, as restored source."""
    best = None
    for m in re.finditer(r"\bif\s*\(", scan_.code[:offset]):
        open_p = m.end() - 1
        close_p = match_brace(scan_.code, open_p)
        rest = scan_.code[close_p + 1:]
        brace = re.match(r"\s*\{", rest)
        if brace:
            b = close_p + 1 + brace.end() - 1
            end = match_brace(scan_.code, b)
            if b < offset <= end:
                best = scan_.code[open_p + 1:close_p]
        else:  # single statement if
            stmt_end = scan_.code.find(";", close_p)
            if close_p < offset <= stmt_end:
                best = scan_.code[open_p + 1:close_p]
    return re.sub(r"\s+", " ", scan_.restore(best)).strip() if best else None
