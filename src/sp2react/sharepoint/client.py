"""Read-only SharePoint REST client (SharePoint Server 2013/2016/2019/SE and SharePoint Online).

Only GET requests are ever issued: the extractor must never change the source site.
"""
from __future__ import annotations

import logging
from typing import Any, Optional
from urllib.parse import quote, urlsplit

import requests

from ..config import SharePointConfig, secret

log = logging.getLogger(__name__)


class SharePointError(RuntimeError):
    def __init__(self, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.status = status


def odata_quote(value: str) -> str:
    """Escape a value for use inside '...' in a SharePoint REST path."""
    return quote(value.replace("'", "''"), safe="/:")


def unwrap(data: Any) -> Any:
    """Strip odata=verbose wrappers: {"d": {...}} and {"results": [...]}."""
    if isinstance(data, dict) and "d" in data and len(data) == 1:
        data = data["d"]
    if isinstance(data, dict) and "results" in data and isinstance(data["results"], list):
        return data["results"]
    return data


class ItemReadBlocked(SharePointError):
    pass


class SharePointClient:
    """`policy` limits which hosts may be contacted; `item_reads=False` forbids reading list items, attachments,
    user profiles and rendered pages (anything that carries business data), leaving only code and schema."""

    def __init__(self, cfg: SharePointConfig, session: Optional[requests.Session] = None, policy=None, item_reads: bool = True):
        self.cfg = cfg
        self.item_reads = item_reads
        self.site_url = cfg.site_url
        parts = urlsplit(cfg.site_url)
        self.origin = f"{parts.scheme}://{parts.netloc}"
        self.server_relative = parts.path.rstrip("/") or "/"
        self.session = session or requests.Session()
        self.session.verify = cfg.verify_ssl
        self.session.headers.update({"Accept": "application/json;odata=verbose", "User-Agent": "sp2react/0.1 (read-only)"})
        self.session.headers.update(cfg.extra_headers)
        if policy is not None:
            policy.guard(self.session)
        send = self.session.send

        def get_only(request, **kwargs):          # the extractor must never change the source site
            if request.method not in ("GET", "HEAD"):
                raise SharePointError(f"sp2react only reads from SharePoint; refused {request.method} {request.url}")
            return send(request, **kwargs)

        self.session.send = get_only  # type: ignore[method-assign]
        self._configure_auth()

    # ------------------------------------------------------------------ auth
    def _configure_auth(self) -> None:
        mode = self.cfg.auth
        if mode == "ntlm":
            try:
                from requests_ntlm import HttpNtlmAuth  # type: ignore
            except ImportError as e:  # pragma: no cover - depends on optional extra
                raise SharePointError("NTLM auth needs the extra: pip install 'sp2react[ntlm]'") from e
            self.session.auth = HttpNtlmAuth(
                secret(self.cfg.username_env, "SharePoint user name (DOMAIN\\user)"),
                secret(self.cfg.password_env, "SharePoint password"),
            )
        elif mode == "cookie":
            self.session.headers["Cookie"] = secret(self.cfg.cookie_env, "SharePoint session cookie")
        elif mode == "bearer":
            self.session.headers["Authorization"] = "Bearer " + secret(self.cfg.token_env, "SharePoint bearer token")

    # --------------------------------------------------------------- helpers
    def absolute(self, url_or_path: str) -> str:
        if url_or_path.startswith(("http://", "https://")):
            return url_or_path
        if url_or_path.startswith("/"):
            return self.origin + url_or_path
        return f"{self.site_url}/{url_or_path}"

    def site_relative(self, server_relative_url: str) -> str:
        """'/sites/x/Lists/A/NewForm.aspx' -> 'Lists/A/NewForm.aspx'."""
        prefix = self.server_relative.rstrip("/") + "/"
        if server_relative_url.lower().startswith(prefix.lower()):
            return server_relative_url[len(prefix):]
        return server_relative_url.lstrip("/")

    def server_relative_url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return urlsplit(path).path
        if path.startswith("/"):
            return path
        return self.server_relative.rstrip("/") + "/" + path

    def _data(self, what: str) -> None:
        if not self.item_reads:
            raise ItemReadBlocked(f"Reading {what} from SharePoint is disabled (data_source=database / security.sharepoint_item_reads=false).")

    def _get(self, url: str, accept: Optional[str] = None, params: Optional[dict] = None) -> requests.Response:
        headers = {"Accept": accept} if accept else None
        try:
            r = self.session.get(self.absolute(url), headers=headers, params=params, timeout=self.cfg.timeout)
        except requests.RequestException as e:
            raise SharePointError(f"GET {url} failed: {e}") from e
        if r.status_code >= 400:
            raise SharePointError(f"GET {url} -> HTTP {r.status_code}: {r.text[:300]}", r.status_code)
        return r

    def api(self, path: str, params: Optional[dict] = None) -> Any:
        r = self._get(f"{self.site_url}/_api/{path.lstrip('/')}", params=params)
        return unwrap(r.json())

    def text(self, url: str, accept: str = "*/*") -> str:
        r = self._get(url, accept=accept)
        r.encoding = r.encoding or "utf-8"
        return r.text

    # ------------------------------------------------------------ endpoints
    def web(self) -> dict:
        return self.api("web", {"$select": "Title,Url,ServerRelativeUrl,UIVersion,Language"})

    def lists(self) -> list[dict]:
        return self.api("web/lists", {
            "$select": "Id,Title,EntityTypeName,BaseTemplate,BaseType,Hidden,EnableAttachments,EnableVersioning,ItemCount,"
                       "ValidationFormula,ValidationMessage,RootFolder/ServerRelativeUrl",
            "$expand": "RootFolder",
            "$filter": "Hidden eq false",
        })

    def list_forms(self, list_id: str) -> list[dict]:
        return self.api(f"web/lists(guid'{list_id.strip('{}')}')/forms", {"$select": "ServerRelativeUrl,FormType"})

    def list_views(self, list_id: str) -> list[dict]:
        return self.api(f"web/lists(guid'{list_id.strip('{}')}')/views", {
            "$select": "Title,ServerRelativeUrl,DefaultView,ViewQuery,RowLimit,Hidden",
            "$expand": "ViewFields",
        })

    def fields(self, list_id: str) -> list[dict]:
        return self.api(f"web/lists(guid'{list_id.strip('{}')}')/fields")

    def items(self, list_id: str, top: int) -> list[dict]:
        self._data("list items")
        return self.api(f"web/lists(guid'{list_id.strip('{}')}')/items", {"$top": str(top)})

    def quick_launch(self) -> list[dict]:
        return self.api("web/navigation/quicklaunch", {"$select": "Title,Url"})

    def all_items(self, list_id: str, page_size: int = 1000):
        """Every item of a list, following SharePoint's __next paging links (works past the 5,000 view threshold
        because it pages by ID). Yields raw odata=verbose items, attachments listed under AttachmentFiles."""
        self._data("list items")
        url = f"{self.site_url}/_api/web/lists(guid'{list_id.strip('{}')}')/items"
        params: Optional[dict] = {"$top": str(page_size), "$orderby": "ID", "$expand": "AttachmentFiles"}
        while url:
            r = self._get(url, params=params)
            data = r.json().get("d", {})
            for it in data.get("results", []):
                yield it
            url, params = data.get("__next"), None

    def file_bytes(self, server_relative_url: str) -> bytes:
        self._data("attachments")
        url = self.server_relative_url(server_relative_url)
        return self._get(f"{self.site_url}/_api/web/getfilebyserverrelativeurl('{odata_quote(url)}')/$value", accept="*/*").content

    def site_users(self) -> list[dict]:
        self._data("site users")
        return self.api("web/siteusers", {"$select": "Id,LoginName,Title,Email,PrincipalType"})

    def site_groups(self) -> list[dict]:
        if not self.item_reads:      # group names only; membership (people) stays in SharePoint
            return self.api("web/sitegroups", {"$select": "Id,Title"})
        return self.api("web/sitegroups", {"$select": "Id,Title,Users/LoginName,Users/Title", "$expand": "Users"})

    def file_text(self, server_relative_url: str) -> str:
        """Raw stored content of a file (the .aspx source, not the rendered page)."""
        url = self.server_relative_url(server_relative_url)
        return self.text(f"{self.site_url}/_api/web/getfilebyserverrelativeurl('{odata_quote(url)}')/$value")

    def web_parts(self, server_relative_url: str) -> list[dict]:
        """Web parts added through the browser live in the content DB, not the .aspx; this is how to see them."""
        url = self.server_relative_url(server_relative_url)
        return self.api(
            f"web/getfilebyserverrelativeurl('{odata_quote(url)}')/getlimitedwebpartmanager(1)/webparts",
            {"$expand": "WebPart/Properties"},
        )

    def folder_files(self, server_relative_folder: str) -> list[dict]:
        url = self.server_relative_url(server_relative_folder)
        return self.api(f"web/getfolderbyserverrelativeurl('{odata_quote(url)}')/files", {"$select": "Name,ServerRelativeUrl,TimeLastModified"})

    def rendered(self, server_relative_url: str) -> str:
        """The page as a browser receives it (shows runtime-injected scripts). Can contain list data, so it is
        only fetched when item reads are allowed."""
        self._data("rendered pages")
        return self.text(self.server_relative_url(server_relative_url), accept="text/html")
