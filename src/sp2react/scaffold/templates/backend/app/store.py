"""Specs (one JSON per converted screen) and the data repository behind the generic list API."""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

ROOT = Path(__file__).resolve().parent.parent
SPEC_DIR = Path(os.environ.get("SPEC_DIR", ROOT / "specs"))
DATA_DIR = Path(os.environ.get("DATA_DIR", ROOT / "data"))


class Specs:
    def __init__(self, spec_dir: Path = SPEC_DIR):
        self.screens: dict[str, dict] = {}
        self.lists: dict[str, dict] = {}
        self.rules: dict[str, list[dict]] = {}
        self.endpoints: list[dict] = []
        for f in sorted(spec_dir.glob("*.json")):
            spec = json.loads(f.read_text(encoding="utf-8"))
            sid = spec["screen"]["id"]
            self.screens[sid] = spec
            for name, l in spec["lists"].items():
                cur = self.lists.setdefault(name, {"title": l["title"], "fields": [], "attachments": False})
                known = {x["name"] for x in cur["fields"]}
                cur["fields"] += [x for x in l["fields"] if x["name"] not in known]
                cur["attachments"] = cur["attachments"] or l.get("attachments", False)
            primary = spec["screen"].get("list")
            for r in spec.get("rules", []):
                lst = r.get("list") or primary
                if lst:
                    self.rules.setdefault(lst, []).append({**r, "id": f"{sid}:{r['id']}"})
            self.endpoints += [{**e, "screen": sid} for e in spec.get("endpoints", [])]

    def fields(self, list_name: str) -> list[dict]:
        if list_name not in self.lists:
            raise KeyError(list_name)
        return self.lists[list_name]["fields"]

    def field(self, list_name: str, name: str) -> Optional[dict]:
        return next((f for f in self.fields(list_name) if f["name"] == name), None)

    def list_rules(self, list_name: str) -> list[dict]:
        # several screens can carry the same rule for one list (e.g. a form and a dashboard): keep one copy
        seen, out = set(), []
        for r in self.rules.get(list_name, []):
            key = json.dumps({k: r.get(k) for k in ("kind", "field", "when", "params", "message", "modes")}, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(r)
        return out

    def roles_for(self, method: str, path: str) -> list[str]:
        roles: list[str] = []
        for e in self.endpoints:
            if e["method"] == method and e["path"] == path:
                roles += e.get("roles", [])
        return sorted(set(roles))


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class Conflict(Exception):
    pass


class _Rows(list):
    """fetchall() result with the cursor methods the repository uses."""

    def fetchall(self):
        return list(self)

    def fetchone(self):
        return self[0] if self else None


class SqliteRepo:
    """Migrated copy of the SharePoint lists. Lookups/users are stored as ids and expanded on read."""

    def __init__(self, specs: Specs, db_path: Optional[Path] = None):
        self.specs = specs
        self.path = Path(db_path or os.environ.get("DB_PATH", DATA_DIR / "app.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self.db = sqlite3.connect(self.path, check_same_thread=False)  # one connection, serialised by self._lock
        self._x("create table if not exists items (list text, id integer, data text, version integer, created text, modified text, author integer, editor integer, primary key (list, id))")
        self._x("create table if not exists attachments (list text, item_id integer, name text, content blob, primary key (list, item_id, name))")
        self._commit()
        self.users = json.loads((DATA_DIR / "users.json").read_text(encoding="utf-8")) if (DATA_DIR / "users.json").exists() else []
        if not self._x("select 1 from items limit 1").fetchone():
            self.seed()

    def _x(self, sql: str, params: tuple = ()):
        with self._lock:
            return _Rows(self.db.execute(sql, params).fetchall())

    def _commit(self) -> None:
        with self._lock:
            self.db.commit()

    # ------------------------------------------------------------- users
    def user(self, uid: Any) -> Optional[dict]:
        if isinstance(uid, dict):
            uid = uid.get("id")
        u = next((u for u in self.users if u["id"] == uid), None)
        return {"id": u["id"], "login": u["login"], "title": u["title"], "email": u.get("email")} if u else None

    def user_by_login(self, login: str) -> Optional[dict]:
        login = (login or "").lower()
        return next((u for u in self.users if u["login"].lower() == login or (u.get("email") or "").lower() == login), None)

    # -------------------------------------------------------------- seed
    def seed(self) -> None:
        seed_dir = DATA_DIR / "seed"
        for f in sorted(seed_dir.glob("*.json")) if seed_dir.exists() else []:
            for row in json.loads(f.read_text(encoding="utf-8")):
                meta = row.pop("_meta", {})
                self._x("insert or replace into items values (?,?,?,?,?,?,?,?)",
                                (f.stem, row["ID"], json.dumps(row), meta.get("version", 1), meta.get("created") or now(),
                                 meta.get("modified") or now(), meta.get("author"), meta.get("editor")))
        att = DATA_DIR / "attachments"          # migrated attachments: attachments/<List>/<ID>/<file>
        for lst in sorted(att.iterdir()) if att.exists() else []:
            for item in sorted(lst.iterdir()):
                for f in sorted(item.iterdir()):
                    self._x("insert or replace into attachments values (?,?,?,?)", (lst.name, int(item.name), f.name, f.read_bytes()))
        self._commit()

    # ------------------------------------------------------------ expand
    def _expand(self, list_name: str, row: tuple) -> dict:
        _, iid, data, version, created, modified, author, editor = row
        raw = json.loads(data)
        item: dict = {"ID": iid}
        fields = {f["name"]: f for f in self.specs.lists.get(list_name, {}).get("fields", [])}
        for name, v in raw.items():
            f = fields.get(name)
            if f and f["type"] == "lookup":
                item[name] = self._lookup_obj(f, v)
            elif f and f["type"] == "user":
                item[name] = [self.user(x) for x in v] if isinstance(v, list) else (self.user(v) if v else None)
            else:
                item[name] = v
        for name, f in fields.items():
            item.setdefault(name, None)
        item.update({"Created": created, "Modified": modified, "Author": self.user(author), "Editor": self.user(editor),
                     "_version": f"{version}.0", "_etag": f'"{version}"'})
        item["Attachments"] = [r[0] for r in self._x("select name from attachments where list=? and item_id=? order by name", (list_name, iid))]
        return item

    def _lookup_obj(self, f: dict, v: Any) -> Any:
        target, col = f["lookup"]["list"], f["lookup"].get("field", "Title")

        def one(x):
            if x in (None, "", 0):
                return None
            xid = x.get("id") if isinstance(x, dict) else int(x)
            row = self._x("select data from items where list=? and id=?", (target, xid)).fetchone()
            title = json.loads(row[0]).get(col) if row else None
            return {"id": xid, "title": title}
        return [o for o in (one(x) for x in v) if o] if isinstance(v, list) else one(v)

    def _store_value(self, f: Optional[dict], v: Any) -> Any:
        if f and f["type"] in ("lookup", "user"):
            if isinstance(v, list):
                return [x.get("id") if isinstance(x, dict) else x for x in v]
            return v.get("id") if isinstance(v, dict) else v
        return v

    # -------------------------------------------------------------- CRUD
    def all(self, list_name: str) -> list[dict]:
        rows = self._x("select * from items where list=? order by id", (list_name,)).fetchall()
        return [self._expand(list_name, r) for r in rows]

    def get(self, list_name: str, iid: int) -> Optional[dict]:
        row = self._x("select * from items where list=? and id=?", (list_name, iid)).fetchone()
        return self._expand(list_name, row) if row else None

    def create(self, list_name: str, values: dict, user: dict) -> dict:
        fields = {f["name"]: f for f in self.specs.lists.get(list_name, {}).get("fields", [])}
        data = {k: self._store_value(fields.get(k), v) for k, v in values.items() if k in fields}
        with self._lock:
            nid = (self._x("select max(id) from items where list=?", (list_name,)).fetchone()[0] or 0) + 1
            data["ID"] = nid
            self._x("insert into items values (?,?,?,?,?,?,?,?)", (list_name, nid, json.dumps(data), 1, now(), now(), user.get("id"), user.get("id")))
            self._commit()
        return self.get(list_name, nid)

    def update(self, list_name: str, iid: int, values: dict, user: dict, etag: Optional[str] = None) -> dict:
        fields = {f["name"]: f for f in self.specs.lists.get(list_name, {}).get("fields", [])}
        with self._lock:
            row = self._x("select data, version from items where list=? and id=?", (list_name, iid)).fetchone()
            if not row:
                raise KeyError(iid)
            if etag not in (None, "", "*") and etag.strip('"') != str(row[1]):
                raise Conflict()
            data = json.loads(row[0])
            data.update({k: self._store_value(fields.get(k), v) for k, v in values.items() if k in fields})
            self._x("update items set data=?, version=?, modified=?, editor=? where list=? and id=?",
                            (json.dumps(data), row[1] + 1, now(), user.get("id"), list_name, iid))
            self._commit()
        return self.get(list_name, iid)

    def delete(self, list_name: str, iid: int) -> None:
        self._x("delete from items where list=? and id=?", (list_name, iid))
        self._x("delete from attachments where list=? and item_id=?", (list_name, iid))
        self._commit()

    def add_attachment(self, list_name: str, iid: int, name: str, content_b64: str) -> None:
        self._x("insert or replace into attachments values (?,?,?,?)", (list_name, iid, name, base64.b64decode(content_b64)))
        self._commit()

    def attachment(self, list_name: str, iid: int, name: str) -> Optional[bytes]:
        r = self._x("select content from attachments where list=? and item_id=? and name=?", (list_name, iid, name)).fetchone()
        return r[0] if r else None

    def delete_attachment(self, list_name: str, iid: int, name: str) -> None:
        self._x("delete from attachments where list=? and item_id=? and name=?", (list_name, iid, name))
        self._commit()
