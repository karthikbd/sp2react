"""Stage 2 (scan and crawl): pull everything the conversion needs from the live site, read-only.

Workspace layout written under <workspace>/legacy (identical to tests/fixtures/legacy-site):
  site.json, siteusers.json
  lists/<ListUrlName>/fields.json, items.json
  pages/<site-relative path>.aspx              raw stored source
  pages/<site-relative path>.aspx.webparts.json browser-added web parts (web part manager)
  rendered/<site-relative path without .aspx>.html  what the browser receives
  files/<site-relative path>                   custom scripts, css, CEWP html (SiteAssets, Style Library...)
  manifest.json                                what was fetched and what failed
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Iterable, Optional

from ..analysis.aspx import asset_refs, parse_page, resolve_tokens
from .client import ItemReadBlocked, SharePointClient, SharePointError, unwrap

log = logging.getLogger(__name__)

FORM_TYPES = {8: "New", 6: "Edit", 4: "Display"}
SKIP_PREFIXES = ("/_layouts/", "/_vti_bin/", "/_catalogs/masterpage/", "/scriptresource.axd", "/webresource.axd")


def _write(path: Path, content) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, (dict, list)):
        path.write_text(json.dumps(content, indent=2, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(content, encoding="utf-8")


def _list_folder(list_entry: dict) -> str:
    return list_entry["url"].rstrip("/").split("/")[-1]


class Extractor:
    def __init__(self, client: SharePointClient, workspace: Path, progress=None):
        self.sp = client
        self.root = workspace / "legacy"
        self.progress = progress or (lambda msg: log.info(msg))
        self.manifest: dict = {"site": client.site_url, "pages": [], "lists": [], "files": [], "errors": []}

    def _err(self, what: str, e: Exception) -> None:
        self.manifest["errors"].append({"what": what, "error": str(e)[:400]})
        log.warning("%s: %s", what, e)

    # ----------------------------------------------------------- site/lists
    def site(self) -> dict:
        web = self.sp.web()
        site = {"url": self.sp.site_url, "serverRelativeUrl": web.get("ServerRelativeUrl", self.sp.server_relative),
                "title": web.get("Title"), "uiVersion": web.get("UIVersion"), "lists": [], "groups": [], "users": []}
        for l in self.sp.lists():
            if l.get("BaseType", 0) not in (0, None) or l.get("BaseTemplate") in (101, 109, 119, 851, 700):
                continue
            root = (l.get("RootFolder") or {}).get("ServerRelativeUrl", "")
            entry = {"title": l["Title"], "url": self.sp.site_relative(root), "id": "{" + l["Id"].strip("{}") + "}",
                     "entityTypeName": l.get("EntityTypeName"), "enableAttachments": l.get("EnableAttachments", False),
                     "enableVersioning": l.get("EnableVersioning", False), "itemCount": l.get("ItemCount"),
                     "validationFormula": l.get("ValidationFormula") or None, "validationMessage": l.get("ValidationMessage") or None,
                     "forms": {}, "views": {}}
            try:
                for f in self.sp.list_forms(l["Id"]):
                    mode = FORM_TYPES.get(f.get("FormType"))
                    if mode and mode not in entry["forms"]:
                        entry["forms"][mode] = f["ServerRelativeUrl"].split("/")[-1]
            except SharePointError as e:
                self._err(f"forms of {l['Title']}", e)
            try:
                for v in self.sp.list_views(l["Id"]):
                    if v.get("Hidden"):
                        continue
                    vf = v.get("ViewFields") or {}
                    fields = unwrap(vf.get("Items")) or []
                    name = (v.get("ServerRelativeUrl") or v.get("Title", "View")).split("/")[-1].replace(".aspx", "")
                    entry["views"][name] = {"title": v.get("Title"), "fields": fields, "query": v.get("ViewQuery"),
                                            "rowLimit": v.get("RowLimit"), "default": v.get("DefaultView", False)}
            except SharePointError as e:
                self._err(f"views of {l['Title']}", e)
            site["lists"].append(entry)
        return site

    def list_data(self, site: dict, sample_items: int) -> None:
        for entry in site["lists"]:
            folder = self.root / "lists" / _list_folder(entry)
            self.progress(f"list {entry['title']}: fields and sample items")
            try:
                _write(folder / "fields.json", {"d": {"results": self.sp.fields(entry["id"])}})
            except SharePointError as e:
                self._err(f"fields of {entry['title']}", e)
                continue
            if not self.sp.item_reads:
                _write(folder / "items.json", {"d": {"results": []}, "note": "list items are not read: data_source=database"})
            else:
                try:
                    _write(folder / "items.json", {"d": {"results": self.sp.items(entry["id"], sample_items)}})
                except SharePointError as e:
                    self._err(f"items of {entry['title']}", e)
            self.manifest["lists"].append(entry["title"])

    def principals(self, site: dict) -> None:
        if not self.sp.item_reads:
            site["users"] = []
        try:
            users = self.sp.site_users() if self.sp.item_reads else []
            _write(self.root / "siteusers.json", {"d": {"results": users}})
            site["users"] = [{"login": re.sub(r"^i:0#\.\w\|", "", u.get("LoginName", "")), "title": u.get("Title"), "email": u.get("Email")}
                             for u in users if u.get("PrincipalType", 1) == 1]
        except SharePointError as e:
            self._err("site users", e)
        try:
            site["groups"] = [{"name": g["Title"], "members": [re.sub(r"^i:0#\.\w\|", "", u.get("LoginName", "")) for u in (unwrap(g.get("Users")) or [])] if isinstance(g.get("Users"), dict) else []}
                              for g in self.sp.site_groups()]
        except SharePointError as e:
            self._err("site groups (needs permission to enumerate groups)", e)

    # ---------------------------------------------------------------- pages
    def discover_pages(self, site: dict) -> list[str]:
        pages = []
        for entry in site["lists"]:
            for form in entry.get("forms", {}).values():
                pages.append(f"{entry['url']}/{form}")
        try:
            for f in self.sp.folder_files("SitePages"):
                if f["Name"].lower().endswith(".aspx"):
                    pages.append(self.sp.site_relative(f["ServerRelativeUrl"]))
        except SharePointError as e:
            self._err("SitePages library", e)
        return pages

    def page(self, page: str) -> Optional[str]:
        rel = self.sp.site_relative(self.sp.server_relative_url(page))
        self.progress(f"page {rel}")
        try:
            source = self.sp.file_text(rel)
        except SharePointError as e:
            self._err(f"source of {rel}", e)
            return None
        _write(self.root / "pages" / rel, source)
        wps = None
        try:
            wps = self.sp.web_parts(rel)
            _write(self.root / "pages" / (rel + ".webparts.json"), {"d": {"results": wps}})
        except SharePointError as e:
            self._err(f"web parts of {rel}", e)
        try:
            if self.sp.item_reads:
                _write(self.root / "rendered" / (re.sub(r"\.aspx$", "", rel, flags=re.I) + ".html"), self.sp.rendered(rel))
        except SharePointError as e:
            self._err(f"rendered {rel}", e)
        self.manifest["pages"].append(rel)
        return rel

    # --------------------------------------------------------------- assets
    def assets(self, pages: Iterable[str]) -> None:
        queue: list[str] = []
        for rel in pages:
            src = (self.root / "pages" / rel).read_text(encoding="utf-8", errors="replace")
            wpf = self.root / "pages" / (rel + ".webparts.json")
            wpj = json.loads(wpf.read_text(encoding="utf-8"))["d"]["results"] if wpf.exists() else None
            queue += asset_refs(parse_page(rel, src, wpj))
            rendered = self.root / "rendered" / (re.sub(r"\.aspx$", "", rel, flags=re.I) + ".html")
            if rendered.exists():
                from ..analysis.aspx import scan_html
                s, _, css, _ = scan_html(rendered.read_text(encoding="utf-8", errors="replace"))
                queue += s + css
        done = set()
        while queue:
            ref = resolve_tokens(queue.pop(0), self.sp.server_relative)
            url = ref.split("?")[0].split("#")[0]
            if url.startswith(("http://", "https://")):
                if not url.lower().startswith(self.sp.origin.lower()):
                    continue                      # CDN / external: recorded by the inventory, not downloaded
                url = url[len(self.sp.origin):]
            if not url.startswith("/"):
                url = self.sp.server_relative_url(url)
            if url.lower().startswith(SKIP_PREFIXES) or url in done:
                continue
            if not url.lower().startswith(self.sp.server_relative.lower().rstrip("/") + "/"):
                continue                          # outside this site (another site collection): not ours to export
            done.add(url)
            rel = self.sp.site_relative(url)
            try:
                text = self.sp.file_text(url)
            except SharePointError as e:
                self._err(f"asset {rel}", e)
                continue
            _write(self.root / "files" / rel, text)
            self.manifest["files"].append(rel)
            if rel.lower().endswith((".html", ".htm", ".txt")):  # CEWP content links can pull in more scripts
                from ..analysis.aspx import scan_html
                s, _, css, _ = scan_html(text)
                queue += s + css

    # ------------------------------------------------------------------ run
    def run(self, pages: Optional[list[str]] = None, sample_items: int = 200) -> dict:
        self.root.mkdir(parents=True, exist_ok=True)
        self.progress("site and lists")
        site = self.site()
        self.principals(site)
        try:
            site["quickLaunch"] = [{"title": n.get("Title"), "url": n.get("Url")} for n in self.sp.quick_launch()]
        except SharePointError as e:
            self._err("quick launch navigation", e)
        self.list_data(site, sample_items)
        _write(self.root / "site.json", site)
        targets = pages or self.discover_pages(site)
        fetched = [p for p in (self.page(t) for t in targets) if p]
        self.assets(fetched)
        self.manifest["summary"] = {"lists": len(self.manifest["lists"]), "pages": len(fetched),
                                    "files": len(self.manifest["files"]), "errors": len(self.manifest["errors"])}
        _write(self.root / "manifest.json", self.manifest)
        return self.manifest
