"""The OData subset the legacy jQuery used against /_api, evaluated over items.

Supported: $filter with eq ne gt ge lt le, and/or/not, parentheses, startswith(f,'x'), substringof('x',f),
datetime'...' literals; field paths Name, NameId, Name/Title, Name/Id, AuthorId, Created, Modified, ID;
$orderby (asc/desc, several keys); $top; $skip; $select; $expand (accepted; lookups are always expanded).
"""
from __future__ import annotations

import re
from typing import Any, Callable

TOKEN = re.compile(r"\s*(?:(\()|(\))|(,)|('(?:[^']|'')*')|(datetime'[^']*')|(-?\d+(?:\.\d+)?)|([A-Za-z_][\w/]*))")


class ODataError(ValueError):
    pass


def tokenize(expr: str) -> list[tuple[str, str]]:
    out, pos = [], 0
    expr = expr.strip()
    while pos < len(expr):
        m = TOKEN.match(expr, pos)
        if not m:
            raise ODataError(f"cannot parse $filter near: {expr[pos:pos + 30]!r}")
        pos = m.end()
        if m.group(1):
            out.append(("(", "("))
        elif m.group(2):
            out.append((")", ")"))
        elif m.group(3):
            out.append((",", ","))
        elif m.group(4):
            out.append(("str", m.group(4)[1:-1].replace("''", "'")))
        elif m.group(5):
            out.append(("str", m.group(5)[9:-1]))
        elif m.group(6):
            out.append(("num", m.group(6)))
        else:
            out.append(("id", m.group(7)))
    return out


def resolve(item: dict, path: str) -> Any:
    if path in item:
        v = item[path]
        return v.get("title") if isinstance(v, dict) and "title" in v else v
    m = re.fullmatch(r"(\w+)Id", path)
    if m and isinstance(item.get(m.group(1)), dict):
        return item[m.group(1)].get("id")
    if m and m.group(1) in item and item[m.group(1)] is None:
        return None
    if "/" in path:
        head, prop = path.split("/", 1)
        v = item.get(head)
        if isinstance(v, dict):
            return v.get(prop.lower()) if prop.lower() in v else v.get(prop)
        return None
    if path == "Id":
        return item.get("ID")
    return None


def _norm(v: Any) -> Any:
    if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}T[\d:.]+Z?", v):
        return v[:19]
    return v


class Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self, k=0):
        return self.t[self.i + k] if self.i + k < len(self.t) else (None, None)

    def take(self, kind=None):
        tok = self.peek()
        if kind and tok[0] != kind:
            raise ODataError(f"expected {kind}, got {tok}")
        self.i += 1
        return tok

    def expr(self) -> Callable[[dict], bool]:
        """or-expression: and-expr ('or' and-expr)*"""
        left = self.expr_and()
        while self.peek() == ("id", "or"):
            self.take()
            right = self.expr_and()
            left = (lambda it, l=left, r=right: l(it) or r(it))
        return left

    def expr_and(self) -> Callable[[dict], bool]:
        left = self.term()
        while self.peek() == ("id", "and"):
            self.take()
            right = self.term()
            left = (lambda it, l=left, r=right: l(it) and r(it))
        return left

    def value(self):
        kind, v = self.take()
        if kind == "str":
            return v
        if kind == "num":
            return float(v) if "." in v else int(v)
        if v in ("true", "false"):
            return v == "true"
        if v == "null":
            return None
        raise ODataError(f"unexpected value {v}")

    def term(self) -> Callable[[dict], bool]:
        kind, v = self.peek()
        if kind == "(":
            self.take()
            e = self.expr()
            self.take(")")
            return e
        if v == "not":
            self.take()
            inner = self.term()
            return lambda it: not inner(it)
        if v in ("startswith", "substringof", "endswith"):
            self.take()
            self.take("(")
            if v == "substringof":
                needle = self.value()
                self.take(",")
                field = self.take("id")[1]
                self.take(")")
                return lambda it: needle.lower() in str(resolve(it, field) or "").lower()
            field = self.take("id")[1]
            self.take(",")
            needle = self.value()
            self.take(")")
            fn = str.startswith if v == "startswith" else str.endswith
            return lambda it: fn(str(resolve(it, field) or ""), needle)
        field = self.take("id")[1]
        op = self.take("id")[1]
        val = self.value()
        ops = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b, "gt": lambda a, b: a is not None and a > b,
               "ge": lambda a, b: a is not None and a >= b, "lt": lambda a, b: a is not None and a < b, "le": lambda a, b: a is not None and a <= b}
        if op not in ops:
            raise ODataError(f"unsupported operator {op}")

        def pred(it, field=field, f=ops[op], val=val):
            a = _norm(resolve(it, field))
            b = _norm(val)
            if isinstance(a, bool) and isinstance(b, int) and not isinstance(b, bool):
                b = bool(b)
            try:
                return f(a, b)
            except TypeError:
                return False
        return pred


def compile_filter(expr: str | None) -> Callable[[dict], bool]:
    if not expr:
        return lambda it: True
    p = Parser(tokenize(expr))
    fn = p.expr()
    if p.i != len(p.t):
        raise ODataError(f"unexpected trailing tokens in $filter: {p.t[p.i:]}")
    return fn


def apply_query(items: list[dict], filter: str | None = None, orderby: str | None = None,
                top: int | None = None, skip: int | None = None, select: str | None = None) -> list[dict]:
    pred = compile_filter(filter)
    out = [it for it in items if pred(it)]
    if orderby:
        for part in reversed([p.strip() for p in orderby.split(",") if p.strip()]):
            name, _, direction = part.partition(" ")
            out.sort(key=lambda it: (resolve(it, name) is None, resolve(it, name) if resolve(it, name) is not None else ""),
                     reverse=direction.lower() == "desc")
    if skip:
        out = out[skip:]
    if top is not None:
        out = out[:top]
    if select:
        keep = {s.strip().split("/")[0] for s in select.split(",")} | {"ID", "_etag"}
        out = [{k: v for k, v in it.items() if k in keep} for it in out]
    return out
