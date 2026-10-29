"""Data source for an EXISTING database (MySQL, SQL Server, PostgreSQL, Oracle...) via SQLAlchemy.

Select with DATA_SOURCE=database and DB_URL (SQLAlchemy URL), e.g.
    mysql+pymysql://user:password@db-host:3306/sea
    mssql+pyodbc://user:password@db-host/sea?driver=ODBC+Driver+18+for+SQL+Server
The mapping (MAPPING_FILE, default ./mapping.json) says which table holds each SharePoint list and which
column holds each field. Queries are translated to SQL (filter, sort, paging and counts run in the database).

mapping.json
{
  "lists": {
    "VendorRequests": {
      "table": "vendor_requests", "key": "id",
      "fields": {"Title": "vendor_name", "Department": "department_id",
                 "Requester": {"column": "requester_login", "ref": "login"},
                 "Tags": {"column": "tags", "delimiter": ";"}},
      "system": {"Created": "created_at", "Modified": "modified_at", "Author": "created_by", "Editor": "modified_by", "version": "row_version"},
      "attachments": {"table": "vendor_request_files", "item": "request_id", "name": "file_name", "content": "content"}
    }
  },
  "users": {"table": "app_users", "id": "user_id", "login": "login", "title": "display_name", "email": "email",
            "groups": {"table": "user_groups", "user": "user_id", "group": "group_name"}}
}
Lookup columns hold the key of the row in the mapped target list's table. Person columns hold the users
table id (default) or the login ("ref": "login"). Without a users table, people are their login and groups
come from data/roles.json: {"Compliance Reviewers": ["CORP\\\\bob", ...]}.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import MetaData, Table, and_, create_engine, func, not_, or_, select
from sqlalchemy.engine import Engine

from .odata import ODataError, tokenize
from .store import DATA_DIR, ROOT, Conflict, Specs


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _iso(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(v, date):
        return v.isoformat()
    return v


class SqlRepo:
    def __init__(self, specs: Specs, url: Optional[str] = None, mapping_file: Optional[Path] = None, engine: Optional[Engine] = None):
        self.specs = specs
        self.engine = engine or create_engine(url or os.environ["DB_URL"], pool_pre_ping=True, future=True)
        mf = Path(mapping_file or os.environ.get("MAPPING_FILE", ROOT / "mapping.json"))
        self.mapping = json.loads(mf.read_text(encoding="utf-8"))
        self.schema = self.mapping.get("schema") or os.environ.get("DB_SCHEMA") or None
        self.md = MetaData()
        self._tables: dict[str, Table] = {}
        roles = DATA_DIR / "roles.json"
        self.roles = json.loads(roles.read_text(encoding="utf-8")) if roles.exists() else {}
        self.users = self._load_users()

    # ------------------------------------------------------------- mapping
    def table(self, name: str) -> Table:
        if name not in self._tables:
            self._tables[name] = Table(name, self.md, autoload_with=self.engine, schema=self.schema)
        return self._tables[name]

    def lmap(self, list_name: str) -> dict:
        m = self.mapping["lists"].get(list_name)
        if not m:
            raise KeyError(f"List {list_name} has no table in mapping.json")
        return m

    def fields(self, list_name: str) -> dict[str, dict]:
        return {f["name"]: f for f in self.specs.lists.get(list_name, {}).get("fields", [])}

    @staticmethod
    def fspec(m: dict, field: str) -> Optional[dict]:
        v = m["fields"].get(field)
        if v is None:
            return None
        return {"column": v} if isinstance(v, str) else v

    def col(self, list_name: str, field: str):
        m = self.lmap(list_name)
        t = self.table(m["table"])
        if field in ("ID", "Id"):
            return t.c[m["key"]]
        sysmap = m.get("system", {})
        if field in sysmap:
            return t.c[sysmap[field]]
        fs = self.fspec(m, field)
        if not fs:
            raise ODataError(f"Field {field} is not mapped for {list_name}")
        return t.c[fs["column"]]

    # --------------------------------------------------------------- users
    def _load_users(self) -> list[dict]:
        um = self.mapping.get("users")
        out: list[dict] = []
        if um:
            t = self.table(um["table"])
            with self.engine.connect() as c:
                rows = c.execute(select(t)).mappings().all()
                groups: dict[Any, list[str]] = {}
                gm = um.get("groups")
                if gm:
                    gt = self.table(gm["table"])
                    for g in c.execute(select(gt.c[gm["user"]], gt.c[gm["group"]])).all():
                        groups.setdefault(g[0], []).append(g[1])
            for r in rows:
                login = r[um["login"]]
                out.append({"id": r[um["id"]], "login": login, "title": r.get(um.get("title", um["login"])) or login,
                            "email": r.get(um["email"]) if um.get("email") else None,
                            "groups": groups.get(r[um["id"]], []) + [g for g, members in self.roles.items() if str(login).lower() in [m.lower() for m in members]]})
        return out

    def user(self, ref: Any) -> Optional[dict]:
        if ref in (None, ""):
            return None
        if isinstance(ref, dict):
            ref = ref.get("id")
        u = next((u for u in self.users if u["id"] == ref or str(u["login"]).lower() == str(ref).lower()), None)
        if u:
            return {"id": u["id"], "login": u["login"], "title": u["title"], "email": u.get("email")}
        return {"id": ref, "login": str(ref), "title": str(ref)}

    def user_by_login(self, login: str) -> Optional[dict]:
        login = (login or "").lower()
        u = next((u for u in self.users if str(u["login"]).lower() == login or str(u.get("email") or "").lower() == login), None)
        if u:
            return u
        if not self.mapping.get("users") and login:
            return {"id": login, "login": login, "title": login, "email": None,
                    "groups": [g for g, members in self.roles.items() if login in [m.lower() for m in members]]}
        return None

    # ------------------------------------------------------- row <-> item
    def _titles(self, list_name: str) -> dict[Any, Any]:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        title = self.fspec(m, "Title")
        with self.engine.connect() as c:
            rows = c.execute(select(t.c[m["key"]], t.c[title["column"]] if title else t.c[m["key"]])).all()
        return {r[0]: r[1] for r in rows}

    def _to_item(self, list_name: str, row: dict, title_cache: dict) -> dict:
        m = self.lmap(list_name)
        item: dict = {"ID": row[m["key"]]}
        for name, f in self.fields(list_name).items():
            fs = self.fspec(m, name)
            if not fs:
                item[name] = None
                continue
            v = row.get(fs["column"])
            if fs.get("delimiter") and isinstance(v, str):
                v = [x for x in v.split(fs["delimiter"]) if x != ""]
            if f["type"] == "lookup":
                target = f["lookup"]["list"]
                if target not in title_cache:
                    title_cache[target] = self._titles(target) if target in self.mapping["lists"] else {}
                conv = lambda x: {"id": x, "title": title_cache[target].get(x)} if x not in (None, "") else None
                item[name] = [conv(int(x) if str(x).isdigit() else x) for x in v] if isinstance(v, list) else conv(v)
            elif f["type"] == "user":
                item[name] = [self.user(x) for x in v] if isinstance(v, list) else self.user(v)
            elif f["type"] == "boolean":
                item[name] = None if v is None else bool(v)
            elif f["type"] in ("number", "currency") and v is not None:
                item[name] = float(v)
            else:
                item[name] = _iso(v)
        sysmap = m.get("system", {})
        item["Created"] = _iso(row.get(sysmap["Created"])) if "Created" in sysmap else None
        item["Modified"] = _iso(row.get(sysmap["Modified"])) if "Modified" in sysmap else None
        item["Author"] = self.user(row.get(sysmap["Author"])) if "Author" in sysmap else None
        item["Editor"] = self.user(row.get(sysmap["Editor"])) if "Editor" in sysmap else None
        ver = row.get(sysmap["version"]) if "version" in sysmap else None
        item["_version"] = f"{ver}.0" if ver is not None else None
        item["_etag"] = f'"{ver}"' if ver is not None else f'"{item["Modified"] or ""}"'
        item["Attachments"] = self._attachment_names(list_name, item["ID"])
        return item

    def _to_row(self, list_name: str, values: dict) -> dict:
        m = self.lmap(list_name)
        flds = self.fields(list_name)
        out: dict = {}
        for name, v in values.items():
            fs, f = self.fspec(m, name), flds.get(name)
            if not fs or not f:
                continue
            ref = fs.get("ref", "id")
            if f["type"] in ("lookup", "user"):
                conv = lambda x: (x.get("login") if ref == "login" and f["type"] == "user" else x.get("id")) if isinstance(x, dict) else x
                v = [conv(x) for x in v] if isinstance(v, list) else conv(v)
            if isinstance(v, list):
                v = fs.get("delimiter", ";").join(str(x) for x in v)
            if f["type"] == "date" and isinstance(v, str) and v:
                v = date.fromisoformat(v[:10])
            out[fs["column"]] = v
        return out

    # --------------------------------------------------------- attachments
    def _attachment_names(self, list_name: str, iid: Any) -> list[str]:
        am = self.lmap(list_name).get("attachments")
        if not am:
            return []
        t = self.table(am["table"])
        with self.engine.connect() as c:
            return sorted(r[0] for r in c.execute(select(t.c[am["name"]]).where(t.c[am["item"]] == iid)).all())

    def attachment(self, list_name: str, iid: Any, name: str) -> Optional[bytes]:
        am = self.lmap(list_name).get("attachments")
        if not am:
            return None
        t = self.table(am["table"])
        with self.engine.connect() as c:
            r = c.execute(select(t.c[am["content"]]).where(and_(t.c[am["item"]] == iid, t.c[am["name"]] == name))).first()
        return bytes(r[0]) if r else None

    def add_attachment(self, list_name: str, iid: Any, name: str, content_b64: str) -> None:
        import base64
        am = self.lmap(list_name).get("attachments")
        if not am:
            raise KeyError("attachments are not mapped for this list")
        t = self.table(am["table"])
        with self.engine.begin() as c:
            c.execute(t.delete().where(and_(t.c[am["item"]] == iid, t.c[am["name"]] == name)))
            c.execute(t.insert().values({am["item"]: iid, am["name"]: name, am["content"]: base64.b64decode(content_b64)}))

    def delete_attachment(self, list_name: str, iid: Any, name: str) -> None:
        am = self.lmap(list_name).get("attachments")
        if am:
            t = self.table(am["table"])
            with self.engine.begin() as c:
                c.execute(t.delete().where(and_(t.c[am["item"]] == iid, t.c[am["name"]] == name)))

    # ------------------------------------------------------------- queries
    def _where(self, list_name: str, expr: Optional[str]):
        """OData $filter subset -> SQL clause."""
        if not expr:
            return None
        toks = tokenize(expr)
        pos = [0]
        peek = lambda: toks[pos[0]] if pos[0] < len(toks) else (None, None)

        def take(kind=None):
            t = peek()
            if kind and t[0] != kind:
                raise ODataError(f"expected {kind}, got {t}")
            pos[0] += 1
            return t

        def value():
            kind, v = take()
            if kind == "str":
                return v
            if kind == "num":
                return float(v) if "." in v else int(v)
            return {"true": True, "false": False, "null": None}.get(v, v)

        def column_for(path: str):
            if "/" in path:                       # Lookup/Title -> key IN (select key from target where title ...)
                head, prop = path.split("/", 1)
                f = self.fields(list_name).get(head)
                if f and f["type"] == "lookup":
                    target = f["lookup"]["list"]
                    tm = self.lmap(target)
                    tt = self.table(tm["table"])
                    tcol = tt.c[tm["key"]] if prop.lower() == "id" else self.col(target, prop)
                    return ("sub", self.col(list_name, head), tt.c[tm["key"]], tcol)
                if f and f["type"] == "user" and self.mapping.get("users"):
                    um = self.mapping["users"]
                    ut = self.table(um["table"])
                    ucol = {"title": um.get("title", um["login"]), "name": um["login"], "id": um["id"]}.get(prop.lower(), um["login"])
                    return ("sub", self.col(list_name, head), ut.c[um["id"]], ut.c[ucol])
                raise ODataError(f"cannot filter on {path}")
            m = re.fullmatch(r"(\w+)Id", path)
            if m and (m.group(1) in self.fields(list_name) or m.group(1) in ("Author", "Editor")):
                return ("col", self.col(list_name, m.group(1)))
            return ("col", self.col(list_name, path))

        def cmp(c, op, v):
            if isinstance(v, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}(T[\d:.]+Z?)?", v):
                v = datetime.fromisoformat(v.rstrip("Z")) if "T" in v else date.fromisoformat(v)
            return {"eq": lambda: c.is_(None) if v is None else c == v, "ne": lambda: c.is_not(None) if v is None else c != v,
                    "gt": lambda: c > v, "ge": lambda: c >= v, "lt": lambda: c < v, "le": lambda: c <= v}[op]()

        def term():
            kind, v = peek()
            if kind == "(":
                take()
                e = or_expr()
                take(")")
                return e
            if v == "not":
                take()
                return not_(term())
            if v in ("startswith", "substringof", "endswith"):
                take()
                take("(")
                if v == "substringof":
                    needle = value(); take(","); path = take("id")[1]; take(")")
                    ref = column_for(path)
                    pat = f"%{needle}%"
                else:
                    path = take("id")[1]; take(","); needle = value(); take(")")
                    ref = column_for(path)
                    pat = f"{needle}%" if v == "startswith" else f"%{needle}"
                if ref[0] == "sub":
                    return ref[1].in_(select(ref[2]).where(ref[3].like(pat)))
                return ref[1].like(pat)
            path = take("id")[1]
            op = take("id")[1]
            if op not in ("eq", "ne", "gt", "ge", "lt", "le"):
                raise ODataError(f"unsupported operator {op}")
            val = value()
            ref = column_for(path)
            if ref[0] == "sub":
                return ref[1].in_(select(ref[2]).where(cmp(ref[3], op, val)))
            return cmp(ref[1], op, val)

        def and_expr():
            left = term()
            while peek() == ("id", "and"):
                take()
                left = and_(left, term())
            return left

        def or_expr():
            left = and_expr()
            while peek() == ("id", "or"):
                take()
                left = or_(left, and_expr())
            return left

        clause = or_expr()
        if pos[0] != len(toks):
            raise ODataError(f"unexpected trailing tokens in $filter: {toks[pos[0]:]}")
        return clause

    def query(self, list_name: str, filter: Optional[str] = None, orderby: Optional[str] = None,
              top: Optional[int] = None, skip: Optional[int] = None, select_: Optional[str] = None) -> tuple[list[dict], int]:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        where = self._where(list_name, filter)
        q = select(t)
        cq = select(func.count()).select_from(t)
        if where is not None:
            q, cq = q.where(where), cq.where(where)
        for part in [p.strip() for p in (orderby or "").split(",") if p.strip()]:
            name, _, direction = part.partition(" ")
            c = self.col(list_name, name.split("/")[0])
            q = q.order_by(c.desc() if direction.lower() == "desc" else c.asc())
        if not orderby:
            q = q.order_by(t.c[m["key"]])
        if skip:
            q = q.offset(skip)
        if top is not None:
            q = q.limit(top)
        with self.engine.connect() as c:
            rows = c.execute(q).mappings().all()
            total = c.execute(cq).scalar_one()
        cache: dict = {}
        items = [self._to_item(list_name, dict(r), cache) for r in rows]
        if select_:
            keep = {s.strip().split("/")[0] for s in select_.split(",")} | {"ID", "_etag"}
            items = [{k: v for k, v in it.items() if k in keep} for it in items]
        return items, total

    # ---------------------------------------------------------------- CRUD
    def all(self, list_name: str) -> list[dict]:
        return self.query(list_name)[0]

    def get(self, list_name: str, iid: Any) -> Optional[dict]:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        with self.engine.connect() as c:
            r = c.execute(select(t).where(t.c[m["key"]] == iid)).mappings().first()
        return self._to_item(list_name, dict(r), {}) if r else None

    def create(self, list_name: str, values: dict, user: dict) -> dict:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        row = self._to_row(list_name, values)
        sysmap = m.get("system", {})
        if "Created" in sysmap:
            row[sysmap["Created"]] = _now()
        if "Modified" in sysmap:
            row[sysmap["Modified"]] = _now()
        for k in ("Author", "Editor"):
            if k in sysmap:
                row[sysmap[k]] = user.get("login") if m.get("user_ref", "id") == "login" else user.get("id")
        if "version" in sysmap:
            row[sysmap["version"]] = 1
        with self.engine.begin() as c:
            res = c.execute(t.insert().values(row))
            new_id = res.inserted_primary_key[0] if res.inserted_primary_key else row.get(m["key"])
        return self.get(list_name, new_id)

    def update(self, list_name: str, iid: Any, values: dict, user: dict, etag: Optional[str] = None) -> dict:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        current = self.get(list_name, iid)
        if not current:
            raise KeyError(iid)
        if etag not in (None, "", "*") and etag.strip('"') != current["_etag"].strip('"'):
            raise Conflict()
        row = self._to_row(list_name, values)
        sysmap = m.get("system", {})
        if "Modified" in sysmap:
            row[sysmap["Modified"]] = _now()
        if "Editor" in sysmap:
            row[sysmap["Editor"]] = user.get("login") if m.get("user_ref", "id") == "login" else user.get("id")
        cond = t.c[m["key"]] == iid
        if "version" in sysmap:
            vcol = t.c[sysmap["version"]]
            row[sysmap["version"]] = vcol + 1
            if etag not in (None, "", "*"):
                cond = and_(cond, vcol == int(etag.strip('"')))
        with self.engine.begin() as c:
            res = c.execute(t.update().where(cond).values(row))
            if res.rowcount == 0:
                raise Conflict()
        return self.get(list_name, iid)

    def delete(self, list_name: str, iid: Any) -> None:
        m = self.lmap(list_name)
        t = self.table(m["table"])
        with self.engine.begin() as c:
            c.execute(t.delete().where(t.c[m["key"]] == iid))
