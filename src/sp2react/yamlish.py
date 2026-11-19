"""A YAML reader for configuration files, using only the standard library.

It reads the YAML people write in config files: nested mappings and lists by indentation, comments, plain,
single- and double-quoted scalars, flow lists and mappings on one line ([a, b], {k: v}), and block scalars
(| and >). Scalars resolve as PyYAML's safe_load does: null/~, true/false/yes/no/on/off, integers, floats,
everything else a string. Anchors, aliases, tags and multiple documents are refused with the line number,
rather than guessed at.
"""
from __future__ import annotations

import re
from typing import Any, List, Optional, Tuple


class YAMLError(ValueError):
    def __init__(self, msg: str, line: Optional[int] = None):
        super().__init__(f"line {line}: {msg}" if line else msg)
        self.line = line


_BOOL_TRUE = {"true", "yes", "on", "y"}
_BOOL_FALSE = {"false", "no", "off", "n"}
_INT = re.compile(r"^[-+]?(0|[1-9][0-9_]*)$")
_HEX = re.compile(r"^0x[0-9a-fA-F_]+$")
_OCT = re.compile(r"^0o[0-7_]+$")
_FLOAT = re.compile(r"^[-+]?(\.[0-9]+|[0-9][0-9_]*(\.[0-9_]*)?)([eE][-+]?[0-9]+)?$")
_ESC = {"0": "\0", "a": "\a", "b": "\b", "t": "\t", "\t": "\t", "n": "\n", "v": "\v", "f": "\f", "r": "\r", "e": "\x1b",
        " ": " ", '"': '"', "/": "/", "\\": "\\", "N": "\u0085", "_": "\u00a0", "L": "\u2028", "P": "\u2029"}


def _resolve(text: str) -> Any:
    t = text.strip()
    low = t.lower()
    if t in ("", "~") or low == "null":
        return None
    if low in _BOOL_TRUE and low != "y":
        return True
    if low in _BOOL_FALSE and low != "n":
        return False
    if _INT.match(t):
        return int(t.replace("_", ""))
    if _HEX.match(t):
        return int(t[2:].replace("_", ""), 16)
    if _OCT.match(t):
        return int(t[2:].replace("_", ""), 8)
    if _FLOAT.match(t) and any(c.isdigit() for c in t):
        return float(t.replace("_", ""))
    if low in (".inf", "+.inf"):
        return float("inf")
    if low == "-.inf":
        return float("-inf")
    if low == ".nan":
        return float("nan")
    return t


def _strip_comment(s: str) -> str:
    """Drop a trailing # comment that is outside quotes (a # must follow whitespace or start the text)."""
    quote = None
    i = 0
    while i < len(s):
        c = s[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 2
                continue
            if c == quote:
                if quote == "'" and i + 1 < len(s) and s[i + 1] == "'":
                    i += 2
                    continue
                quote = None
        elif c in "\"'" and (i == 0 or s[i - 1] in " \t[{,:"):
            quote = c
        elif c == "#" and (i == 0 or s[i - 1] in " \t"):
            return s[:i].rstrip()
        i += 1
    return s.rstrip()


def _double(s: str, line: int) -> Tuple[str, int]:
    """Parse a double-quoted scalar starting at s[0] == '"'; return (value, index after the closing quote)."""
    out: List[str] = []
    i = 1
    while i < len(s):
        c = s[i]
        if c == '"':
            return "".join(out), i + 1
        if c == "\\":
            i += 1
            if i >= len(s):
                break
            e = s[i]
            if e in _ESC:
                out.append(_ESC[e])
            elif e in "xuU":
                n = {"x": 2, "u": 4, "U": 8}[e]
                hexs = s[i + 1:i + 1 + n]
                if len(hexs) != n or not re.fullmatch(r"[0-9a-fA-F]+", hexs):
                    raise YAMLError(f"bad escape \\{e}{hexs}", line)
                code = int(hexs, 16)
                if code > 0x10FFFF:
                    raise YAMLError(f"escape \\{e}{hexs} is beyond Unicode", line)
                out.append(chr(code))
                i += n
            else:
                raise YAMLError(f"unknown escape \\{e}", line)
        else:
            out.append(c)
        i += 1
    raise YAMLError("unterminated double-quoted string", line)


def _single(s: str, line: int) -> Tuple[str, int]:
    out, i = [], 1
    while i < len(s):
        if s[i] == "'":
            if i + 1 < len(s) and s[i + 1] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out), i + 1
        out.append(s[i])
        i += 1
    raise YAMLError("unterminated single-quoted string", line)


class _Flow:
    """[a, b, {c: d}] and {k: v, k2: [1, 2]} on one line."""

    def __init__(self, text: str, line: int):
        self.s, self.i, self.line = text, 0, line

    def ws(self) -> None:
        while self.i < len(self.s) and self.s[self.i] in " \t":
            self.i += 1

    def value(self) -> Any:
        self.ws()
        if self.i >= len(self.s):
            raise YAMLError("unexpected end of flow collection", self.line)
        c = self.s[self.i]
        if c == "[":
            self.i += 1
            out: List[Any] = []
            self.ws()
            if self.s[self.i:self.i + 1] == "]":
                self.i += 1
                return out
            while True:
                out.append(self.value())
                self.ws()
                c = self.s[self.i:self.i + 1]
                self.i += 1
                if c == "]":
                    return out
                if c != ",":
                    raise YAMLError("expected ',' or ']' in flow list", self.line)
                self.ws()
                if self.s[self.i:self.i + 1] == "]":
                    self.i += 1
                    return out
        if c == "{":
            self.i += 1
            obj: dict[str, Any] = {}
            self.ws()
            if self.s[self.i:self.i + 1] == "}":
                self.i += 1
                return obj
            while True:
                key = self.scalar(stop=":,}")
                self.ws()
                if self.s[self.i:self.i + 1] != ":":
                    raise YAMLError("expected ':' in flow mapping", self.line)
                self.i += 1
                if key in obj:
                    raise YAMLError(f"duplicate key {key!r}", self.line)
                obj[key] = self.value()
                self.ws()
                c = self.s[self.i:self.i + 1]
                self.i += 1
                if c == "}":
                    return obj
                if c != ",":
                    raise YAMLError("expected ',' or '}' in flow mapping", self.line)
                self.ws()
                if self.s[self.i:self.i + 1] == "}":
                    self.i += 1
                    return obj
        return self.scalar(stop=",]}")

    def scalar(self, stop: str) -> Any:
        self.ws()
        c = self.s[self.i:self.i + 1]
        if c == '"':
            v, n = _double(self.s[self.i:], self.line)
            self.i += n
            return v
        if c == "'":
            v, n = _single(self.s[self.i:], self.line)
            self.i += n
            return v
        start = self.i
        while self.i < len(self.s) and self.s[self.i] not in stop:
            if self.s[self.i] == ":" and ":" in stop and (self.i + 1 >= len(self.s) or self.s[self.i + 1] in " ,}"):
                break
            self.i += 1
        return _resolve(self.s[start:self.i])


def _scalar_value(text: str, line: int) -> Any:
    t = text.strip()
    if not t:
        return None
    if t[0] in "&*!":
        raise YAMLError("anchors, aliases and tags are not supported in sp2react config files", line)
    if t[0] in "[{":
        f = _Flow(t, line)
        v = f.value()
        if f.s[f.i:].strip():
            raise YAMLError(f"unexpected text after flow collection: {f.s[f.i:].strip()!r}", line)
        return v
    if t[0] == '"':
        v, n = _double(t, line)
        if t[n:].strip():
            raise YAMLError(f"unexpected text after string: {t[n:].strip()!r}", line)
        return v
    if t[0] == "'":
        v, n = _single(t, line)
        if t[n:].strip():
            raise YAMLError(f"unexpected text after string: {t[n:].strip()!r}", line)
        return v
    if t[0] in "@`":
        raise YAMLError(f"a plain value cannot start with {t[0]!r}; quote it", line)
    return _resolve(t)


def _split_key(text: str, line: int) -> Optional[Tuple[str, str]]:
    """'key: rest' -> (key, rest); None when the text is not a mapping entry."""
    if text and text[0] in "\"'":
        key, n = (_double if text[0] == '"' else _single)(text, line)
        rest = text[n:].lstrip()
        if rest.startswith(":") and (len(rest) == 1 or rest[1] in " \t"):
            return key, rest[1:]
        return None
    m = re.match(r"^([^#\[\]{},][^#]*?)\s*:(\s+|$)(.*)$", text)
    if not m or m.group(1).startswith(("- ", "-\t")) or m.group(1) == "-":
        return None
    return m.group(1).strip(), m.group(3)


class _Lines:
    def __init__(self, text: str):
        self.items: List[Tuple[int, int, str, str]] = []      # (line no, indent, content without comment, raw)
        for n, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), 1):
            if "\t" in raw[:len(raw) - len(raw.lstrip(" \t"))]:
                raise YAMLError("tabs cannot be used for indentation", n)
            stripped = raw.strip()
            if stripped in ("---", "...") or stripped.startswith("%"):
                if stripped == "---" and self.items:
                    raise YAMLError("more than one YAML document in the file", n)
                continue
            body = _strip_comment(raw)
            self.items.append((n, len(raw) - len(raw.lstrip(" ")), body.strip(), raw))
        self.pos = 0

    def next_content(self) -> Optional[Tuple[int, int, str, str]]:
        while self.pos < len(self.items) and not self.items[self.pos][2]:
            self.pos += 1
        return self.items[self.pos] if self.pos < len(self.items) else None


def _block_scalar(lines: _Lines, header: str, parent_indent: int, line: int) -> str:
    m = re.fullmatch(r"([|>])([+-]?)(\d?)([+-]?)", header)
    if not m:
        raise YAMLError(f"bad block scalar header {header!r}", line)
    style, chomp = m.group(1), m.group(2) or m.group(4)
    body: List[str] = []
    indent = int(m.group(3)) + parent_indent if m.group(3) else None
    while lines.pos < len(lines.items):
        _n, ind, _content, raw = lines.items[lines.pos]
        if raw.strip() == "":
            body.append("")
            lines.pos += 1
            continue
        if indent is None:
            if ind <= parent_indent:
                break
            indent = ind
        if ind < indent:
            break
        body.append(raw[indent:])
        lines.pos += 1
    while body and body[-1] == "" and chomp != "+":
        body.pop()
    if style == "|":
        text = "\n".join(body)
    else:
        parts: List[str] = []
        for b in body:
            if b == "" or b.startswith(" "):
                parts.append("\n" + b if parts else b)
            else:
                parts.append((" " if parts and not parts[-1].endswith("\n") else "") + b)
        text = "".join(parts)
    return text if chomp == "-" or not text else text + "\n"


def _node(lines: _Lines, indent: int) -> Any:
    first = lines.next_content()
    if first is None:
        return None
    n, ind, content, _ = first
    if ind < indent:
        return None
    if content == "-" or content.startswith(("- ", "-\t")):
        return _sequence(lines, ind)
    if _split_key(content, n) is not None:
        return _mapping(lines, ind)
    lines.pos += 1
    value = _scalar_value(content, n)
    return _continue_plain(lines, value, ind - 1, content, n)


def _continue_plain(lines: _Lines, value: Any, indent: int, content: str, line: int) -> Any:
    """A plain scalar may go on over more-indented lines (folded with spaces)."""
    if not isinstance(value, str) or content.strip()[0] in "\"'[{":
        return value
    extra = []
    while True:
        nxt = lines.next_content()
        if nxt is None or nxt[1] <= indent:
            break
        nl, _ni, nc, _ = nxt
        if nc.startswith(("- ", "-\t")) or nc == "-" or _split_key(nc, nl) is not None:
            raise YAMLError("unexpected nested entry under a plain value", nl)
        extra.append(nc)
        lines.pos += 1
    return " ".join([value, *extra]) if extra else value


def _value_after(lines: _Lines, rest: str, indent: int, line: int) -> Any:
    rest = rest.strip()
    if rest and rest[0] in "|>":
        return _block_scalar(lines, rest, indent, line)
    if rest:
        value = _scalar_value(rest, line)
        return _continue_plain(lines, value, indent, rest, line)
    nxt = lines.next_content()
    if nxt is None:
        return None
    if nxt[1] > indent:
        return _node(lines, nxt[1])
    if nxt[1] == indent and (nxt[2] == "-" or nxt[2].startswith(("- ", "-\t"))):   # list at the key's own indent
        return _sequence(lines, indent)
    return None


def _mapping_key(key: str, content: str) -> Any:
    """Plain keys resolve like values (1: -> 1), except that yes/no/on/off/null stay text; quoted keys are text."""
    if content[0] in "\"'":
        return key
    v = _resolve(key)
    return key if isinstance(v, bool) or v is None else v


def _mapping(lines: _Lines, indent: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    while True:
        cur = lines.next_content()
        if cur is None or cur[1] < indent:
            return out
        n, ind, content, _ = cur
        if ind > indent:
            raise YAMLError("unexpected indentation", n)
        kv = _split_key(content, n)
        if kv is None:
            if content == "-" or content.startswith(("- ", "-\t")):
                return out
            raise YAMLError(f"expected 'key: value', found {content!r}", n)
        key, rest = kv
        if (key and key[0] in "&*!") or key == "<<":
            raise YAMLError("anchors, aliases, tags and merge keys are not supported", n)
        if key in out:
            raise YAMLError(f"duplicate key {key!r}", n)
        lines.pos += 1
        out[_mapping_key(key, content)] = _value_after(lines, rest, indent, n)


def _sequence(lines: _Lines, indent: int) -> list[Any]:
    out: list[Any] = []
    while True:
        cur = lines.next_content()
        if cur is None or cur[1] < indent:
            return out
        n, ind, content, _raw = cur
        if ind > indent:
            raise YAMLError("unexpected indentation", n)
        if not (content == "-" or content.startswith(("- ", "-\t"))):
            return out
        rest = content[1:].lstrip(" \t")
        lines.pos += 1
        if not rest:
            out.append(_value_after(lines, "", indent, n))
            continue
        child = indent + (len(content) - len(rest))        # where the item's own content starts
        if (rest == "-" or rest.startswith(("- ", "-\t"))) or _split_key(rest, n) is not None:
            # put the rest of this line back as a line of its own at the item's indent
            lines.pos -= 1
            lines.items[lines.pos] = (n, child, rest, " " * child + rest)
            out.append(_node(lines, child))
        else:
            out.append(_value_after(lines, rest, indent, n))


def safe_load(text: str) -> Any:
    """Parse one YAML document of the kind used for configuration; returns dict / list / scalar / None."""
    if not isinstance(text, str):
        raise TypeError("safe_load expects text")
    lines = _Lines(text)
    first = lines.next_content()
    if first is None:
        return None
    value = _node(lines, first[1])
    rest = lines.next_content()
    if rest is not None:
        raise YAMLError(f"unexpected content {rest[2]!r}", rest[0])
    return value
