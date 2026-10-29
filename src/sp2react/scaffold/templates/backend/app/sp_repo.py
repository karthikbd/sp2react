"""Optional data source: keep the data in SharePoint and use this API as a backend-for-frontend.

Select with DATA_SOURCE=sharepoint. Same interface as SqliteRepo, so the rules engine and routes
do not change. Auth for the service account: SP_AUTH=ntlm|cookie|bearer with SP_USERNAME/SP_PASSWORD,
SP_COOKIE or SP_TOKEN. Writes use the request digest from /_api/contextinfo.
"""
from __future__ import annotations

import base64
import os
from typing import Any, Optional

import requests

from .store import Conflict, Specs


class SharePointRepo:
    def __init__(self, specs: Specs):
        self.specs = specs
        self.site = os.environ["SP_SITE_URL"].rstrip("/")
        self.s = requests.Session()
        self.s.headers.update({"Accept": "application/json;odata=verbose"})
        self.s.verify = os.environ.get("SP_VERIFY_SSL", "true").lower() not in ("0", "false", "no")
        mode = os.environ.get("SP_AUTH", "ntlm")
        if mode == "ntlm":
            from requests_ntlm import HttpNtlmAuth  # type: ignore
            self.s.auth = HttpNtlmAuth(os.environ["SP_USERNAME"], os.environ["SP_PASSWORD"])
        elif mode == "cookie":
            self.s.headers["Cookie"] = os.environ["SP_COOKIE"]
        elif mode == "bearer":
            self.s.headers["Authorization"] = "Bearer " + os.environ["SP_TOKEN"]
        self.users: list[dict] = []

    # -------------------------------------------------------------- helpers
    def _title(self, list_name: str) -> str:
        return self.specs.lists[list_name]["title"].replace("'", "''")

    def _url(self, list_name: str, suffix: str = "") -> str:
        return f"{self.site}/_api/web/lists/getbytitle('{self._title(list_name)}')/items{suffix}"

    def _digest(self) -> str:
        r = self.s.post(f"{self.site}/_api/contextinfo")
        r.raise_for_status()
        return r.json()["d"]["GetContextWebInformation"]["FormDigestValue"]

    def _fields(self, list_name: str) -> dict[str, dict]:
        return {f["name"]: f for f in self.specs.lists[list_name]["fields"]}

    def _query(self, list_name: str) -> dict:
        sel, exp = ["*", "Author/Id", "Author/Title", "Author/Name", "Editor/Id", "Editor/Title", "Editor/Name", "AttachmentFiles"], ["Author", "Editor", "AttachmentFiles"]
        for f in self._fields(list_name).values():
            if f["type"] == "lookup":
                sel += [f"{f['name']}/Id", f"{f['name']}/{f['lookup'].get('field', 'Title')}"]
                exp.append(f["name"])
            if f["type"] == "user":
                sel += [f"{f['name']}/Id", f"{f['name']}/Title", f"{f['name']}/Name"]
                exp.append(f["name"])
        return {"$select": ",".join(sel), "$expand": ",".join(exp)}

    @staticmethod
    def _user(u: Any) -> Optional[dict]:
        if not u or not isinstance(u, dict) or "Id" not in u:
            return None
        return {"id": u["Id"], "login": (u.get("Name") or "").split("|")[-1], "title": u.get("Title")}

    def _to_item(self, list_name: str, d: dict) -> dict:
        item: dict = {"ID": d["Id"]}
        for name, f in self._fields(list_name).items():
            v = d.get(name)
            if f["type"] == "lookup":
                col = f["lookup"].get("field", "Title")
                conv = lambda x: {"id": x["Id"], "title": x.get(col)} if x and x.get("Id") else None
                item[name] = [conv(x) for x in v.get("results", [])] if isinstance(v, dict) and "results" in v else conv(v)
            elif f["type"] == "user":
                item[name] = [self._user(x) for x in v.get("results", [])] if isinstance(v, dict) and "results" in v else self._user(v)
            elif f["type"] == "date" and v:
                item[name] = v[:10]
            else:
                item[name] = v
        etag = d.get("__metadata", {}).get("etag", '"1"')
        item.update({"Created": d.get("Created"), "Modified": d.get("Modified"), "Author": self._user(d.get("Author")),
                     "Editor": self._user(d.get("Editor")), "_etag": etag, "_version": etag.strip('"') + ".0",
                     "Attachments": [a["FileName"] for a in (d.get("AttachmentFiles") or {}).get("results", [])]})
        return item

    def _payload(self, list_name: str, values: dict) -> dict:
        out: dict = {}
        for name, v in values.items():
            f = self._fields(list_name).get(name)
            if not f:
                continue
            if f["type"] in ("lookup", "user"):
                if isinstance(v, list):
                    out[f"{name}Id"] = {"results": [x.get("id") if isinstance(x, dict) else x for x in v]}
                else:
                    out[f"{name}Id"] = v.get("id") if isinstance(v, dict) else v
            else:
                out[name] = v
        return out

    # ----------------------------------------------------------------- API
    def user(self, uid):
        return None

    def user_by_login(self, login: str):
        r = self.s.get(f"{self.site}/_api/web/siteusers", params={"$filter": f"substringof('{login}',LoginName)"})
        r.raise_for_status()
        res = r.json()["d"]["results"]
        if not res:
            return None
        u = res[0]
        g = self.s.get(f"{self.site}/_api/web/getuserbyid({u['Id']})/groups").json()["d"]["results"]
        return {"id": u["Id"], "login": login, "title": u["Title"], "email": u.get("Email"), "groups": [x["Title"] for x in g]}

    def all(self, list_name: str) -> list[dict]:
        r = self.s.get(self._url(list_name), params={**self._query(list_name), "$top": "5000"})
        r.raise_for_status()
        return [self._to_item(list_name, d) for d in r.json()["d"]["results"]]

    def get(self, list_name: str, iid: int) -> Optional[dict]:
        r = self.s.get(self._url(list_name, f"({iid})"), params=self._query(list_name))
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return self._to_item(list_name, r.json()["d"])

    def create(self, list_name: str, values: dict, user: dict) -> dict:
        body = {"__metadata": {"type": f"SP.Data.{self.specs.lists[list_name].get('entity', list_name + 'List')}Item"}, **self._payload(list_name, values)}
        r = self.s.post(self._url(list_name), json=body, headers={"X-RequestDigest": self._digest(), "Content-Type": "application/json;odata=verbose"})
        r.raise_for_status()
        return self.get(list_name, r.json()["d"]["Id"])

    def update(self, list_name: str, iid: int, values: dict, user: dict, etag: Optional[str] = None) -> dict:
        body = {"__metadata": {"type": f"SP.Data.{self.specs.lists[list_name].get('entity', list_name + 'List')}Item"}, **self._payload(list_name, values)}
        r = self.s.post(self._url(list_name, f"({iid})"), json=body, headers={
            "X-RequestDigest": self._digest(), "Content-Type": "application/json;odata=verbose",
            "X-HTTP-Method": "MERGE", "IF-MATCH": etag or "*"})
        if r.status_code == 412:
            raise Conflict()
        r.raise_for_status()
        return self.get(list_name, iid)

    def delete(self, list_name: str, iid: int) -> None:
        r = self.s.post(self._url(list_name, f"({iid})"), headers={"X-RequestDigest": self._digest(), "X-HTTP-Method": "DELETE", "IF-MATCH": "*"})
        r.raise_for_status()

    def add_attachment(self, list_name: str, iid: int, name: str, content_b64: str) -> None:
        r = self.s.post(self._url(list_name, f"({iid})/AttachmentFiles/add(FileName='{name}')"), data=base64.b64decode(content_b64),
                        headers={"X-RequestDigest": self._digest()})
        r.raise_for_status()

    def attachment(self, list_name: str, iid: int, name: str) -> Optional[bytes]:
        r = self.s.get(self._url(list_name, f"({iid})/AttachmentFiles('{name}')/$value"))
        return r.content if r.ok else None

    def delete_attachment(self, list_name: str, iid: int, name: str) -> None:
        r = self.s.post(self._url(list_name, f"({iid})/AttachmentFiles('{name}')"), headers={"X-RequestDigest": self._digest(), "X-HTTP-Method": "DELETE"})
        r.raise_for_status()
