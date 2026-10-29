"""A small HTTP server that answers the SharePoint REST calls sp2react makes, from the fixture site.

It speaks odata=verbose JSON like SharePoint 2013/2016, rejects every non-GET request (so tests prove
the extractor is read-only) and records each request for assertions.
"""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

FIXTURE = Path(__file__).parent / "fixtures" / "legacy-site"
FORM_TYPES = {"New": 8, "Edit": 6, "Display": 4}


def _wrap(results):
    return {"d": {"results": results}} if isinstance(results, list) else {"d": results}


class MockSharePoint:
    def __init__(self, fixture: Path = FIXTURE, cookie: str = "FedAuth=test-cookie"):
        self.fx = fixture
        self.site = json.loads((fixture / "site.json").read_text())
        self.prefix = self.site["serverRelativeUrl"]
        self.cookie = cookie
        self.requests: list[tuple[str, str]] = []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def site_url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}{self.prefix}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *a):
        self.server.shutdown()

    # ------------------------------------------------------------- routing
    def _list(self, guid: str):
        for l in self.site["lists"]:
            if l["id"].strip("{}").lower() == guid.lower():
                return l
        return None

    def _site_rel(self, server_rel: str) -> str:
        return server_rel[len(self.prefix) + 1:] if server_rel.lower().startswith(self.prefix.lower() + "/") else server_rel.lstrip("/")

    def route(self, path: str, accept: str, query: dict | None = None):
        api = self.prefix + "/_api/"
        if not path.startswith(api):
            # a page request: serve the rendered capture
            rel = self._site_rel(path)
            r = self.fx / "rendered" / (re.sub(r"\.aspx$", "", rel, flags=re.I) + ".html")
            if r.exists():
                return 200, "text/html", r.read_text()
            if (self.fx / "pages" / rel).exists():
                return 200, "text/html", "<html><body><form id='aspnetForm'></form></body></html>"
            return 404, "text/plain", "not found"
        rest = path[len(api):]
        if rest == "web":
            return 200, "json", _wrap({"Title": self.site["title"], "Url": self.site_url, "ServerRelativeUrl": self.prefix, "UIVersion": 15, "Language": 1033})
        if rest == "web/lists":
            return 200, "json", _wrap([{
                "Id": l["id"].strip("{}"), "Title": l["title"], "EntityTypeName": l["entityTypeName"], "BaseTemplate": 100, "BaseType": 0,
                "Hidden": False, "EnableAttachments": l.get("enableAttachments", False), "EnableVersioning": l.get("enableVersioning", False),
                "ItemCount": len(json.loads((self.fx / "lists" / l["url"].split("/")[-1] / "items.json").read_text())["d"]["results"]),
                "ValidationFormula": l.get("validationFormula") or "", "ValidationMessage": l.get("validationMessage") or "",
                "RootFolder": {"ServerRelativeUrl": f"{self.prefix}/{l['url']}"}} for l in self.site["lists"]])
        m = re.match(r"web/lists\(guid'([^']+)'\)/(forms|views|fields|items)$", rest)
        if m:
            l = self._list(m.group(1))
            if not l:
                return 404, "json", {"error": "list not found"}
            folder = self.fx / "lists" / l["url"].split("/")[-1]
            kind = m.group(2)
            if kind == "forms":
                return 200, "json", _wrap([{"ServerRelativeUrl": f"{self.prefix}/{l['url']}/{f}", "FormType": FORM_TYPES[k]} for k, f in l.get("forms", {}).items()])
            if kind == "views":
                return 200, "json", _wrap([{"Title": "All Items", "ServerRelativeUrl": f"{self.prefix}/{l['url']}/{n}.aspx", "DefaultView": True,
                                            "ViewQuery": "", "RowLimit": v.get("rowLimit", 30), "Hidden": False, "ViewFields": {"Items": {"results": v["fields"]}}}
                                           for n, v in l.get("views", {}).items()])
            data = json.loads((folder / f"{kind}.json").read_text())
            if kind == "items" and query is not None:
                rows = data["d"]["results"]
                after = int(re.search(r"p_ID=(\d+)", query.get("$skiptoken", "p_ID=0")).group(1))
                rows = [r for r in rows if r["ID"] > after]
                top = int(query.get("$top", "5000"))
                page, rest = rows[:top], rows[top:]
                att_root = self.fx / "files" / l["url"] / "Attachments"
                for r in page:
                    names = sorted(p.name for p in (att_root / str(r["ID"])).glob("*")) if (att_root / str(r["ID"])).exists() else []
                    r["Attachments"] = bool(names)
                    r["AttachmentFiles"] = {"results": [{"FileName": n, "ServerRelativeUrl": f"{self.prefix}/{l['url']}/Attachments/{r['ID']}/{n}"} for n in names]}
                out = {"d": {"results": page}}
                if rest:
                    out["d"]["__next"] = f"{self.site_url}/_api/web/lists(guid'{m.group(1)}')/items?%24skiptoken=Paged%3DTRUE%26p_ID%3D{page[-1]['ID']}&%24top={top}&%24expand=AttachmentFiles"
                return 200, "json", out
            return 200, "json", data
        if rest == "web/navigation/quicklaunch":
            return 200, "json", _wrap([{"Title": q["title"], "Url": q["url"]} for q in self.site.get("quickLaunch", [])])
        if rest == "web/siteusers":
            data = json.loads((self.fx / "siteusers.json").read_text())
            for u in data["d"]["results"]:
                u["PrincipalType"] = 1
            return 200, "json", data
        if rest == "web/sitegroups":
            users = {u["login"]: u for u in self.site["users"]}
            return 200, "json", _wrap([{"Id": i + 1, "Title": g["name"], "Users": {"results": [{"LoginName": "i:0#.w|" + m_, "Title": users[m_]["title"]} for m_ in g["members"]]}}
                                       for i, g in enumerate(self.site["groups"])])
        m = re.match(r"web/getfilebyserverrelativeurl\('(.+)'\)/(\$value|getlimitedwebpartmanager\(1\)/webparts)$", rest)
        if m:
            rel = self._site_rel(m.group(1).replace("''", "'"))
            if m.group(2) == "$value":
                for base in ("pages", "files"):
                    f = self.fx / base / rel
                    if f.exists():
                        if "/Attachments/" in rel:
                            return 200, "application/octet-stream", f.read_bytes()
                        return 200, "text/plain", f.read_text()
                return 404, "json", {"error": {"message": {"value": "File Not Found."}}}
            wpf = self.fx / "pages" / (rel + ".webparts.json")
            return 200, "json", json.loads(wpf.read_text()) if wpf.exists() else _wrap([])
        m = re.match(r"web/getfolderbyserverrelativeurl\('(.+)'\)/files$", rest)
        if m:
            rel = self._site_rel(m.group(1))
            folder = self.fx / "pages" / rel
            files = sorted(folder.glob("*.aspx")) if folder.exists() else []
            return 200, "json", _wrap([{"Name": f.name, "ServerRelativeUrl": f"{self.prefix}/{rel}/{f.name}"} for f in files])
        return 404, "json", {"error": f"mock has no route for {rest}"}

    def _handler(self):
        mock = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):  # quiet
                pass

            def _deny(self):
                mock.requests.append((self.command, self.path))
                self.send_response(405)
                self.end_headers()

            do_POST = do_PUT = do_PATCH = do_DELETE = do_MERGE = _deny

            def do_GET(self):
                mock.requests.append(("GET", self.path))
                if mock.cookie and mock.cookie not in (self.headers.get("Cookie") or ""):
                    self.send_response(401)
                    self.end_headers()
                    return
                parts = urlsplit(self.path)
                path = unquote(parts.path)
                from urllib.parse import parse_qs
                q = {k: v[0] for k, v in parse_qs(parts.query).items()}
                if "$skiptoken" in q:
                    q["$skiptoken"] = unquote(q["$skiptoken"])
                status, ctype, body = mock.route(path, self.headers.get("Accept", ""), q)
                payload = json.dumps(body).encode() if ctype == "json" else (body if isinstance(body, bytes) else body.encode())
                self.send_response(status)
                self.send_header("Content-Type", "application/json;odata=verbose;charset=utf-8" if ctype == "json" else f"{ctype}; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

        return H
