"""Parse classic SharePoint .aspx pages and web part definitions.

Handles the three places page behaviour lives:
  * web parts embedded in the .aspx (SharePoint Designer / site definition forms),
  * web parts added in the browser (exported via the web part manager -> *.webparts.json),
  * script/link tags in the page itself and inside web part HTML.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

TAG_VALUE = r"<(?:\w+:)?{tag}\b[^>]*>(.*?)</(?:\w+:)?{tag}>"


def _tag(xml: str, tag: str) -> Optional[str]:
    m = re.search(TAG_VALUE.format(tag=tag), xml, re.S | re.I)
    if not m:
        return None
    val = m.group(1).strip()
    if val.startswith("<![CDATA["):
        val = val[9:-3]
    return html.unescape(val)


def _attrs(tag_text: str) -> dict[str, str]:
    out = {}
    for m in re.finditer(r'([\w:\-]+)\s*=\s*"([^"]*)"', tag_text, re.S):
        out[m.group(1)] = html.unescape(m.group(2))
    return out


@dataclass
class WebPart:
    id: str
    type: str                     # ListForm | ScriptEditor | ContentEditor | ListView | Other:<name>
    title: str
    zone: Optional[str] = None
    order: int = 0
    source: str = "aspx"          # aspx | webpartmanager
    control_mode: Optional[str] = None   # New | Edit | Display (ListForm)
    list_id: Optional[str] = None
    list_url: Optional[str] = None
    content: Optional[str] = None        # inline HTML/script
    content_link: Optional[str] = None   # CEWP link to an .html file
    jslink: Optional[str] = None
    view_xml: Optional[str] = None
    hidden: bool = False

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v not in (None, "", False) or k in ("id", "type", "title")}


@dataclass
class ParsedPage:
    path: str
    master: Optional[str] = None
    title: Optional[str] = None
    web_parts: list[WebPart] = field(default_factory=list)
    stylesheets: list[str] = field(default_factory=list)
    scripts: list[str] = field(default_factory=list)      # src URLs in page order
    inline_scripts: list[dict] = field(default_factory=list)  # {where, code}
    html_fragments: list[dict] = field(default_factory=list)  # {web_part, html} non-script markup authored in web parts

    @property
    def form_mode(self) -> Optional[str]:
        for wp in self.web_parts:
            if wp.type == "ListForm" and wp.control_mode:
                return wp.control_mode
        return None

    @property
    def list_id(self) -> Optional[str]:
        for wp in self.web_parts:
            if wp.type in ("ListForm",) and wp.list_id:
                return wp.list_id
        return None

    def to_dict(self) -> dict:
        return {
            "path": self.path, "master": self.master, "title": self.title, "form_mode": self.form_mode,
            "list_id": self.list_id, "web_parts": [w.to_dict() for w in self.web_parts],
            "stylesheets": self.stylesheets, "scripts": self.scripts,
            "inline_scripts": [{"where": s["where"], "lines": s["code"].count("\n") + 1} for s in self.inline_scripts],
        }


# ------------------------------------------------------------------ markup
SCRIPT_SRC = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']([^\"']+)[\"'][^>]*>", re.I)
SCRIPT_INLINE = re.compile(r"<script\b(?![^>]*\bsrc\s*=)[^>]*>(.*?)</script>", re.I | re.S)
LINK_CSS = re.compile(r"<link\b[^>]*\bhref\s*=\s*[\"']([^\"']+\.css[^\"']*)[\"'][^>]*>", re.I)
CSS_REG = re.compile(r"<SharePoint:CssRegistration\b[^>]*\bName\s*=\s*\"([^\"]+)\"", re.I)
SCRIPT_LINK = re.compile(r"<SharePoint:ScriptLink\b[^>]*\bName\s*=\s*\"([^\"]+)\"", re.I)


def scan_html(markup: str) -> tuple[list[str], list[str], list[str], str]:
    """-> (script srcs, inline scripts, stylesheets, markup without scripts)."""
    srcs = [html.unescape(s) for s in SCRIPT_SRC.findall(markup)]
    inline = [c for c in SCRIPT_INLINE.findall(markup) if c.strip()]
    css = [html.unescape(s) for s in LINK_CSS.findall(markup)] + CSS_REG.findall(markup)
    stripped = re.sub(r"<script\b.*?</script>", "", markup, flags=re.I | re.S).strip()
    return srcs, inline, css, stripped


# ---------------------------------------------------------- web part parsing
WP_BLOCK = re.compile(r"<WebPartPages:(\w+)\b([^>]*?)(/>|>(.*?)</WebPartPages:\1>)", re.S | re.I)


def _wp_from_markup(kind: str, attr_text: str, body: str, order: int) -> WebPart:
    attrs = _attrs(attr_text)
    body = body or ""
    wid = attrs.get("__WebPartId") or _tag(body, "ID") or attrs.get("ID") or f"wp{order}"
    title = attrs.get("Title") or _tag(body, "Title") or kind
    k = kind.lower()
    if k == "listformwebpart":
        return WebPart(id=wid, type="ListForm", title=title, order=order, control_mode=_tag(body, "ControlMode"),
                       list_id=(_tag(body, "ListName") or _tag(body, "ListId") or "").strip("{}").lower() or None,
                       jslink=_tag(body, "JSLink"), hidden=(_tag(body, "IsVisible") or "true").lower() == "false")
    if k == "scripteditorwebpart":
        return WebPart(id=wid, type="ScriptEditor", title=title, order=order, content=attrs.get("Content") or _tag(body, "Content"))
    if k == "contenteditorwebpart":
        return WebPart(id=wid, type="ContentEditor", title=title, order=order,
                       content=_tag(body, "Content") or attrs.get("Content"),
                       content_link=_tag(body, "ContentLink") or attrs.get("ContentLink"))
    if k in ("xsltlistviewwebpart", "listviewwebpart"):
        return WebPart(id=wid, type="ListView", title=title, order=order,
                       list_id=(attrs.get("ListName") or attrs.get("ListId") or _tag(body, "ListName") or "").strip("{}").lower() or None,
                       list_url=attrs.get("ListUrl") or _tag(body, "ListUrl"),
                       view_xml=attrs.get("XmlDefinition") or _tag(body, "XmlDefinition"),
                       jslink=attrs.get("JSLink") or _tag(body, "JSLink"))
    if k in ("webpartzone",):
        raise ValueError("zone")
    return WebPart(id=wid, type=f"Other:{kind}", title=title, order=order, content=attrs.get("Content"))


def web_parts_from_aspx(source: str) -> list[WebPart]:
    out: list[WebPart] = []
    # zones contain web parts; iterate zones to record the zone id
    zones = list(re.finditer(r"<WebPartPages:WebPartZone\b([^>]*)>(.*?)</WebPartPages:WebPartZone>", source, re.S | re.I))
    regions = [(_attrs(z.group(1)).get("ID"), z.group(2)) for z in zones] or [(None, source)]
    order = 0
    for zone_id, region in regions:
        for m in WP_BLOCK.finditer(region):
            if m.group(1).lower() == "webpartzone":
                continue
            order += 1
            try:
                wp = _wp_from_markup(m.group(1), m.group(2), m.group(4) or "", order)
            except ValueError:
                continue
            wp.zone = zone_id
            out.append(wp)
    return out


def web_parts_from_manager(items: list[dict]) -> list[WebPart]:
    """Classify REST web part manager output (properties only; SharePoint gives no type name)."""
    out = []
    for i, d in enumerate(items):
        wpd = d.get("WebPart") or {}
        props = wpd.get("Properties") or {}
        if isinstance(props, dict) and "results" in props:  # some versions wrap it
            props = {p.get("Key"): p.get("Value") for p in props["results"]}
        title = props.get("Title") or wpd.get("Title") or f"Web part {i + 1}"
        common = dict(id=str(d.get("Id")), title=title, zone=d.get("ZoneId"), order=wpd.get("ZoneIndex", i),
                      source="webpartmanager", hidden=bool(wpd.get("Hidden") or wpd.get("IsClosed")))
        if props.get("XmlDefinition") or props.get("ListUrl") or props.get("ViewGuid"):
            wp = WebPart(type="ListView", list_id=(props.get("ListName") or props.get("ListId") or "").strip("{}").lower() or None,
                         list_url=props.get("ListUrl"), view_xml=props.get("XmlDefinition"), jslink=props.get("JSLink") or None, **common)
        elif props.get("ContentLink"):
            wp = WebPart(type="ContentEditor", content_link=props.get("ContentLink"), content=props.get("Content"), **common)
        elif props.get("ControlMode") or props.get("FormType"):
            wp = WebPart(type="ListForm", control_mode=props.get("ControlMode"),
                         list_id=(props.get("ListName") or props.get("ListId") or "").strip("{}").lower() or None,
                         jslink=props.get("JSLink") or None, **common)
        elif props.get("Content") is not None:
            # Script Editor and inline Content Editor are indistinguishable over REST; both are "authored HTML"
            wp = WebPart(type="ScriptEditor", content=props.get("Content"), **common)
        else:
            wp = WebPart(type="Other", **common)
        out.append(wp)
    return out


def parse_page(path: str, source: str, webparts_json: Optional[list[dict]] = None) -> ParsedPage:
    page = ParsedPage(path=path)
    m = re.search(r'MasterPageFile\s*=\s*"([^"]+)"', source)
    page.master = m.group(1) if m else None
    t = re.search(r'ContentPlaceHolderId="PlaceHolderPageTitle"[^>]*>(.*?)</asp:Content>', source, re.S)
    if t:
        page.title = re.sub(r"<[^>]+>", "", t.group(1)).strip() or None

    wps = web_parts_from_aspx(source)
    if webparts_json:
        seen = {w.id.strip("{}").lower() for w in wps}
        for w in web_parts_from_manager(webparts_json):
            if w.id.strip("{}").lower() not in seen:
                wps.append(w)
    page.web_parts = wps

    # page-level tags (outside web parts)
    outside = WP_BLOCK.sub("", source)
    srcs, inline, css, _ = scan_html(outside)
    page.scripts += srcs + SCRIPT_LINK.findall(outside)
    page.stylesheets += css
    page.inline_scripts += [{"where": "page", "code": c} for c in inline]

    for w in wps:
        if w.jslink:
            page.scripts += [j.strip() for j in w.jslink.split("|") if j.strip()]
        if w.content:
            srcs, inline, css, stripped = scan_html(w.content)
            page.scripts += srcs
            page.stylesheets += css
            page.inline_scripts += [{"where": f"webpart:{w.title}", "code": c} for c in inline]
            if stripped:
                page.html_fragments.append({"web_part": w.title, "html": stripped})
    return page


def asset_refs(page: ParsedPage) -> list[str]:
    refs = list(page.scripts) + list(page.stylesheets)
    refs += [w.content_link for w in page.web_parts if w.content_link]
    seen, out = set(), []
    for r in refs:
        r = resolve_tokens(r)
        if r and r not in seen:
            seen.add(r)
            out.append(r)
    return out


def resolve_tokens(url: str, site_rel: str = "") -> str:
    """Expand ~site/~sitecollection tokens used in JSLink/ScriptLink."""
    url = url.strip()
    for tok in ("~sitecollection", "~site", "~layouts"):
        if url.lower().startswith(tok):
            rest = url[len(tok):]
            return ("/_layouts/15" + rest) if tok == "~layouts" else (site_rel + rest)
    return url


def load_page(legacy_dir: Path, rel_path: str) -> ParsedPage:
    src = (legacy_dir / "pages" / rel_path).read_text(encoding="utf-8", errors="replace")
    wpf = legacy_dir / "pages" / (rel_path + ".webparts.json")
    wpj = None
    if wpf.exists():
        data = json.loads(wpf.read_text(encoding="utf-8"))
        wpj = data.get("d", {}).get("results", data) if isinstance(data, dict) else data
    return parse_page(rel_path, src, wpj)
