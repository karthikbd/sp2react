"""Generic list API driven by the screen specs (replaces the legacy /_api and SPServices calls)."""
from __future__ import annotations

import base64
import re
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, Response

from . import rules as R
from .auth import current_user
from .custom import HANDLERS
from .odata import ODataError, apply_query
from .store import Conflict

router = APIRouter(prefix="/api")
SAVE_CONFLICT = "Save Conflict. Your changes conflict with those made concurrently by another user. Refresh the page and resubmit your changes."


def _specs(request: Request):
    return request.app.state.specs


def _repo(request: Request):
    return request.app.state.repo


def _list(request: Request, list_name: str) -> list[dict]:
    try:
        return _specs(request).fields(list_name)
    except KeyError:
        raise HTTPException(404, f"List '{list_name}' is not part of the converted screens")


def _authorize(request: Request, user: dict, method: str, path: str) -> None:
    roles = _specs(request).roles_for(method, path)
    if roles and not set(roles) & set(user["groups"]):
        raise HTTPException(403, "Sorry, you don't have access to this page.")


# ----------------------------------------------------------------- meta
@router.get("/me")
def me(user: dict = Depends(current_user)):
    return user


@router.get("/users")
def users(request: Request, search: str = "", user: dict = Depends(current_user)):
    s = search.lower()
    pool = getattr(_repo(request), "users", []) or []
    return [{"id": u["id"], "login": u["login"], "title": u["title"], "email": u.get("email")}
            for u in pool if s in u["title"].lower() or s in u["login"].lower() or s in (u.get("email") or "").lower()][:20]


@router.get("/screens")
def screens(request: Request):
    return [{"id": sid, "title": s["screen"]["title"], "route": s["screen"]["route"], "kind": s["screen"]["kind"],
             "legacy_urls": s["screen"].get("legacy_urls", [])} for sid, s in _specs(request).screens.items()]


@router.get("/specs/{screen_id}")
def spec(request: Request, screen_id: str):
    s = _specs(request).screens.get(screen_id)
    if not s:
        raise HTTPException(404, "Unknown screen")
    return s


# ---------------------------------------------------------------- items
@router.get("/lists/{list_name}/items")
def query_items(request: Request, list_name: str, user: dict = Depends(current_user),
                filter_: Optional[str] = Query(None, alias="$filter"), orderby: Optional[str] = Query(None, alias="$orderby"),
                top: Optional[int] = Query(None, alias="$top"), skip: Optional[int] = Query(None, alias="$skip"),
                select: Optional[str] = Query(None, alias="$select")):
    _list(request, list_name)
    _authorize(request, user, "GET", f"/api/lists/{list_name}/items")
    repo = _repo(request)
    try:
        if hasattr(repo, "query"):                 # database: filter/sort/page run as SQL
            page, total = repo.query(list_name, filter_, orderby, top, skip, select)
            return {"value": page, "count": total}
        items = repo.all(list_name)
        filtered = apply_query(items, filter_)
        page = apply_query(filtered, None, orderby, top, skip, select)
    except ODataError as e:
        raise HTTPException(400, str(e))
    return {"value": page, "count": len(filtered)}


@router.get("/lists/{list_name}/items/{iid}")
def get_item(request: Request, list_name: str, iid: int, user: dict = Depends(current_user)):
    _list(request, list_name)
    _authorize(request, user, "GET", f"/api/lists/{list_name}/items/{{id}}")
    item = _repo(request).get(list_name, iid)
    if not item:
        raise HTTPException(404, "Item does not exist. It may have been deleted by another user.")
    return item


@router.get("/lists/{list_name}/items/{iid}/state")
def item_state(request: Request, list_name: str, iid: int, mode: str = "edit", user: dict = Depends(current_user)):
    """Server-side answer to 'can this user edit this item' (lock_item) and which banners apply."""
    _list(request, list_name)
    item = get_item(request, list_name, iid, user)
    rules = _specs(request).list_rules(list_name)
    ctx = {"mode": mode, "values": item, "original": item, "user": user}
    locked = R.lock(rules, ctx)
    return {"locked": bool(locked), "message": R.fill_template(locked.get("message", ""), item) if locked else None,
            "redirect": (locked.get("params") or {}).get("redirect", "display") if locked else None,
            "banners": [R.fill_template(b.get("message", ""), item) for b in R.banners(rules, ctx)]}


def _find_duplicate(repo, list_name: str, field: str, value: Any, exclude: Any) -> Optional[dict]:
    if hasattr(repo, "query"):
        lit = str(value).replace("'", "''")
        rows, _ = repo.query(list_name, f"{field} eq '{lit}'", None, 5, None, None)
        return next((it for it in rows if it["ID"] != exclude), None)
    return next((it for it in repo.all(list_name) if str(it.get(field) or "") == str(value) and it["ID"] != exclude), None)


def _coerce(field: Optional[dict], v: Any) -> Any:
    if field and field["type"] in ("lookup", "user") and isinstance(v, str) and v.isdigit():
        return int(v)
    if field and field["type"] in ("number", "currency") and isinstance(v, str) and re.fullmatch(r"\s*\$?-?[\d,]+(\.\d+)?\s*", v):
        return float(v.replace(",", "").replace("$", ""))
    return v


def _derive(request: Request, list_name: str, rules: list[dict], values: dict, mode: str) -> None:
    specs, repo = _specs(request), _repo(request)
    for r in R.rules_for(rules, "derive", None, mode):
        src = specs.field(list_name, r["params"]["from_field"])
        ref = values.get(r["params"]["from_field"])
        if not src or not src.get("lookup"):
            continue
        rid = ref.get("id") if isinstance(ref, dict) else ref
        target = repo.get(src["lookup"]["list"], int(rid)) if rid else None
        v = target.get(r["params"]["column"]) if target else None
        values[r["field"]] = v.get("title") if isinstance(v, dict) else v


def _save(request: Request, list_name: str, mode: str, payload: dict, user: dict, iid: Optional[int] = None, etag: Optional[str] = None):
    fields = _list(request, list_name)
    specs, repo = _specs(request), _repo(request)
    rules = specs.list_rules(list_name)
    by_name = {f["name"]: f for f in fields}
    original = repo.get(list_name, iid) if iid else {}
    if iid and not original:
        raise HTTPException(404, "Item does not exist. It may have been deleted by another user.")
    if mode == "edit":
        locked = R.lock(rules, {"mode": mode, "values": original, "original": original, "user": user})
        if locked:
            msg = R.fill_template(locked.get("message", ""), original)
            return JSONResponse(status_code=423, content={"message": msg, "redirect": (locked.get("params") or {}).get("redirect", "display")})

    values: dict = dict(original) if mode == "edit" else R.defaults(fields, rules, user)
    incoming = {k: _coerce(by_name.get(k), v) for k, v in (payload or {}).items() if k in by_name}
    probe = {**values, **incoming}
    ctx = {"mode": mode, "values": probe, "original": original, "user": user}
    for name, v in incoming.items():
        st = R.field_state(by_name[name], rules, ctx)
        if st["visible"] and not st["readonly"]:
            values[name] = v
        elif not st["visible"] and mode == "new":
            values.pop(name, None) if name not in R.defaults(fields, rules, user) else None
    _derive(request, list_name, rules, values, mode)
    values.update(R.clear_hidden(fields, rules, {"mode": mode, "values": values, "original": original, "user": user}))
    ctx = {"mode": mode, "values": values, "original": original, "user": user}
    values.update(R.set_on_save(rules, ctx))
    errors = R.validate(fields, rules, ctx)

    for r in R.rules_for(rules, "unique", None, mode):
        v = values.get(r["field"])
        if R.is_empty(v) or not R.evaluate(r.get("when"), ctx):
            continue
        dup = _find_duplicate(repo, list_name, r["field"], v, iid)
        if dup:
            errors.append({"field": r["field"], "message": R.fill_template(r.get("message", ""), {**values, "duplicate_id": dup["ID"], "id": dup["ID"]}),
                           "presentation": r.get("presentation", "inline"), "rule": r["id"]})
    for r in R.rules_for(rules, "custom", None, mode):
        mod = HANDLERS.get(r["params"]["handler"])
        if mod and hasattr(mod, "validate") and R.evaluate(r.get("when"), ctx):
            errors += mod.validate(ctx) or []
    if errors:
        return JSONResponse(status_code=422, content={"errors": errors})

    to_store = {k: values.get(k) for k in by_name if k in values}
    try:
        item = repo.create(list_name, to_store, user) if mode == "new" else repo.update(list_name, iid, to_store, user, etag)
    except Conflict:
        return JSONResponse(status_code=412, content={"message": SAVE_CONFLICT})

    saved_ctx = {"mode": mode, "values": item, "original": original, "user": user}
    for r in R.rules_for(rules, "on_save", None, mode):
        if not R.evaluate(r.get("when"), saved_ctx):
            continue
        act = r["params"]["action"]
        if act.get("type") == "create_item":
            tfields = {f["name"]: f for f in specs.fields(act["list"])}
            vals = {k: _coerce(tfields.get(k), R.fill_template(v, item) if isinstance(v, str) else v) for k, v in act.get("values", {}).items()}
            repo.create(act["list"], vals, user)
        elif act.get("type") == "custom":
            mod = HANDLERS.get(act.get("handler", ""))
            if mod and hasattr(mod, "on_save"):
                mod.on_save(saved_ctx, item, repo)
    for r in R.rules_for(rules, "custom", None, mode):
        mod = HANDLERS.get(r["params"]["handler"])
        if mod and hasattr(mod, "on_save") and R.evaluate(r.get("when"), saved_ctx):
            mod.on_save(saved_ctx, item, repo)
    return JSONResponse(status_code=201 if mode == "new" else 200, content=item)


@router.post("/lists/{list_name}/items")
def create_item(request: Request, list_name: str, body: dict = Body(...), user: dict = Depends(current_user)):
    _list(request, list_name)
    _authorize(request, user, "POST", f"/api/lists/{list_name}/items")
    return _save(request, list_name, "new", body.get("values", body), user)


@router.patch("/lists/{list_name}/items/{iid}")
def update_item(request: Request, list_name: str, iid: int, body: dict = Body(...), user: dict = Depends(current_user),
                if_match: Optional[str] = Header(None)):
    _list(request, list_name)
    _authorize(request, user, "PATCH", f"/api/lists/{list_name}/items/{{id}}")
    return _save(request, list_name, "edit", body.get("values", body), user, iid, if_match)


@router.delete("/lists/{list_name}/items/{iid}", status_code=204)
def delete_item(request: Request, list_name: str, iid: int, user: dict = Depends(current_user)):
    _list(request, list_name)
    _authorize(request, user, "DELETE", f"/api/lists/{list_name}/items/{{id}}")
    _repo(request).delete(list_name, iid)
    return Response(status_code=204)


# -------------------------------------------------------- lookups etc.
@router.get("/lists/{list_name}/lookup/{field}")
def lookup_options(request: Request, list_name: str, field: str, parent: Optional[int] = None, q: str = "",
                   user: dict = Depends(current_user)):
    specs, repo = _specs(request), _repo(request)
    _list(request, list_name)
    f = specs.field(list_name, field)
    if not f or not f.get("lookup"):
        raise HTTPException(404, "Not a lookup field")
    target, col = f["lookup"]["list"], f["lookup"].get("field", "Title")
    items = repo.all(target) if target in specs.lists else []
    cascade = next((r for r in specs.list_rules(list_name) if r["kind"] == "cascade" and r.get("field") == field), None)
    if cascade and parent is not None:
        via = cascade["params"]["via"]
        items = [it for it in items if (it.get(via) or {}).get("id") == parent]
    elif cascade:
        items = []
    extra = sorted({r["params"]["column"] for r in specs.list_rules(list_name)
                    if r["kind"] == "derive" and r["params"]["from_field"] == field})
    out = []
    for it in items:
        title = it.get(col)
        title = title.get("title") if isinstance(title, dict) else title
        if q and q.lower() not in str(title or "").lower():
            continue
        out.append({"id": it["ID"], "title": title, **{c: (it.get(c).get("title") if isinstance(it.get(c), dict) else it.get(c)) for c in extra}})
    return sorted(out, key=lambda o: str(o["title"] or "").lower())


@router.get("/lists/{list_name}/unique/{field}")
def unique_check(request: Request, list_name: str, field: str, value: str, exclude: int = 0, user: dict = Depends(current_user)):
    _list(request, list_name)
    dup = _find_duplicate(_repo(request), list_name, field, value, exclude)
    return {"duplicate_id": dup["ID"] if dup else None}


@router.get("/lists/{list_name}/items/{iid}/attachments/{name}")
def get_attachment(request: Request, list_name: str, iid: int, name: str, user: dict = Depends(current_user)):
    data = _repo(request).attachment(list_name, iid, name)
    if data is None:
        raise HTTPException(404, "Attachment not found")
    return Response(content=data, media_type="application/octet-stream", headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.post("/lists/{list_name}/items/{iid}/attachments")
def add_attachment(request: Request, list_name: str, iid: int, body: dict = Body(...), user: dict = Depends(current_user)):
    if not _specs(request).lists.get(list_name, {}).get("attachments"):
        raise HTTPException(400, "Attachments are disabled for this list")
    base64.b64decode(body["content_base64"], validate=True)
    _repo(request).add_attachment(list_name, iid, body["name"], body["content_base64"])
    return {"ok": True}


@router.delete("/lists/{list_name}/items/{iid}/attachments/{name}", status_code=204)
def delete_attachment(request: Request, list_name: str, iid: int, name: str, user: dict = Depends(current_user)):
    _repo(request).delete_attachment(list_name, iid, name)
    return Response(status_code=204)
