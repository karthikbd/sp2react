"""Regression tests for the defects fixed in 0.1.3 (security S1-S7, data D1, D5, D6, D10, D11, D12).

Each test failed on 0.1.2. They run the real pipeline against the mock site where that is how the defect showed.
"""
from __future__ import annotations

import base64
import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import NODE_OK, TEMPLATES, load_app, make, run_ts
from mock_sharepoint import MockSharePoint
from scripted_agents import scripted
from sp2react.config import SharePointConfig
from sp2react.pipeline import Pipeline

VENDOR_LIST = "6f1c2a10-4b7e-4d59-9a3e-0c1f7d2e8b41"


# ------------------------------------------------------------------ S1
def test_s1_spa_route_serves_only_files_of_the_built_frontend(built, monkeypatch):
    c = TestClient(load_app(built, monkeypatch))
    for path in ("/..%2fsecret.env", "/%2e%2e/secret.env", "/..%2f..%2f" + "etc%2fhostname", "/%2Fetc%2Fhostname"):
        r = c.get(path)
        assert r.text == "<html>app shell</html>", (path, r.text[:80])
    assert "hunter2" not in c.get("/assets/..%2f..%2fsecret.env").text
    assert c.get("/favicon.ico").text == "icon"
    assert c.get("/pages/dashboard").text == "<html>app shell</html>"


# ------------------------------------------------------------------ S2, S3
def test_s2_default_auth_refuses_requests_without_identity(built, monkeypatch):
    c = TestClient(load_app(built, monkeypatch))                     # no AUTH_MODE set
    assert c.get("/api/me").status_code == 401
    assert c.get("/api/me", headers={"X-User": "corp\\alice"}).status_code == 401
    assert c.get("/api/me", headers={"X-MS-CLIENT-PRINCIPAL-NAME": "corp\\bob"}).json()["login"] == "corp\\bob"


def test_s2_dev_mode_is_local_only_and_ignores_query_identity(built, monkeypatch):
    app = load_app(built, monkeypatch, AUTH_MODE="dev")
    remote = TestClient(app, client=("10.20.30.40", 50000))
    assert remote.get("/api/me", headers={"X-User": "corp\\alice"}).status_code == 403
    local = TestClient(app)
    assert local.get("/api/me", headers={"X-User": "corp\\bob"}).json()["login"] == "corp\\bob"
    first = local.get("/api/me").json()["login"]
    assert local.get("/api/me", params={"as": "corp\\bob"}).json()["login"] == first != "corp\\bob"


def test_s3_screen_and_spec_endpoints_need_a_signed_in_user(built, monkeypatch):
    c = TestClient(load_app(built, monkeypatch))
    assert c.get("/api/screens").status_code == 401
    assert c.get("/api/specs/VendorRequests-form").status_code == 401
    signed_in = {"X-MS-CLIENT-PRINCIPAL-NAME": "corp\\alice"}
    assert c.get("/api/screens", headers=signed_in).status_code == 200
    assert c.get("/api/specs/VendorRequests-form", headers=signed_in).status_code == 200


# ------------------------------------------------------------------ S4
def test_s4_lock_rules_cover_delete_and_attachments(built, monkeypatch):
    c = TestClient(load_app(built, monkeypatch, AUTH_MODE="dev"), headers={"X-User": "corp\\alice"})
    assert c.get("/api/lists/VendorRequests/items/1/state").json()["locked"] is True   # Approved: alice may not change it
    body = {"name": "x.txt", "content_base64": base64.b64encode(b"x").decode()}
    assert c.delete("/api/lists/VendorRequests/items/1").status_code == 423
    assert c.post("/api/lists/VendorRequests/items/1/attachments", json=body).status_code == 423
    assert c.get("/api/lists/VendorRequests/items/1").status_code == 200                # still there
    assert c.post("/api/lists/VendorRequests/items/999/attachments", json=body).status_code == 404
    for bad in ("../x.txt", "a/b.txt", "con\\x.txt", ".hidden", "x.txt "):
        r = c.post("/api/lists/VendorRequests/items/3/attachments", json={**body, "name": bad})
        assert r.status_code == 400, bad
    assert c.post("/api/lists/VendorRequests/items/3/attachments", json=body).status_code == 200
    assert c.get("/api/lists/VendorRequests/items/3/attachments/x.txt").content == b"x"
    assert c.delete("/api/lists/VendorRequests/items/3/attachments/x.txt").status_code == 204
    reviewer = TestClient(c.app, headers={"X-User": "corp\\bob"})                        # Compliance Reviewers may
    assert reviewer.post("/api/lists/VendorRequests/items/1/attachments", json=body).status_code == 200


# ------------------------------------------------------------------ S5
def test_s5_agent_paths_cannot_leave_the_screen_folder(tmp_path):
    from sp2react.agents.tasks import page_file_problems, path_problem, safe_target
    prefix = "frontend/src/screens/Dashboard/"
    page = "export default function Page({ spec }: { spec: Spec }) { return null; }"
    for bad in (prefix + "../../../vite.config.ts", prefix + "..\\x.ts", "/etc/passwd.ts", "C:/x.ts", prefix + ".x.ts"):
        probs = page_file_problems({prefix + "Page.tsx": page, bad: "export const x = 1;"}, prefix, [])
        assert any(bad in p for p in probs), (bad, probs)
        with pytest.raises(ValueError):
            safe_target(tmp_path, bad, prefix)
    assert page_file_problems({prefix + "Page.tsx": page, prefix + "parts/Header.tsx": "export const x = 1;"}, prefix, []) == []
    assert safe_target(tmp_path, prefix + "Page.tsx", prefix) == (tmp_path / prefix / "Page.tsx").resolve()
    assert path_problem("backend/app/custom/check_tax_id.py") is None


def test_s5_custom_handler_names_must_be_identifiers():
    from sp2react.spec.coverage import HANDLER_NAME
    assert HANDLER_NAME.match("check_tax_id") and not HANDLER_NAME.match("../../app/main") and not HANDLER_NAME.match("a-b")


# ------------------------------------------------------------------ S6, D6 (TypeScript, run by Node)
ATTACKS = [
    "<svg/onload=alert(1)>", "<img src=x onerror=alert(1)>", "<a href=javascript:alert(1)>x</a>",
    '<a href="&#106;avascript:alert(1)">x</a>', '<a href="java&#x09;script:alert(1)">x</a>', '<a href="&#x6A&#x61vascript:alert(1)">x</a>',
    '<a href="jav&Tab;ascript:alert(1)">x</a>', "<a href='  JAVASCRIPT:alert(1)'>x</a>", '<a href="javascript&colon;alert(1)">x</a>',
    "<iframe src=//evil></iframe>", "<script>alert(1)</script>", "<scr<script>ipt>alert(1)</script>",
    '<div style="background:url(javascript:alert(1))">x</div>', '<div style="width:expression(alert(1))">x</div>',
    "<math><mi xlink:href=javascript:alert(1)>x</mi></math>", '<p title="x" onclick="alert(1)">x</p>',
    "<details open ontoggle=alert(1)>", '<img src="x" onerror  =  "alert(1)">', "<a href=\"data:text/html,<script>alert(1)</script>\">x</a>",
    "<form action=javascript:alert(1)><button>x</button></form>", "<object data=javascript:alert(1)>", "<!--><img src=x onerror=alert(1)>-->",
    '<a href="x" style="x" onmouseover=alert(1)//>y</a>', "<IMG SRC=JaVaScRiPt:alert(1)>", '<base href="javascript:alert(1)//">',
]


@pytest.mark.skipif(not NODE_OK, reason="needs Node 22.6+ (TypeScript type stripping)")
def test_s6_legacy_html_cannot_carry_script(tmp_path):
    script = ('import { sanitizeHtml } from "./rt/sanitize.ts";\n'
              f"const attacks = {json.dumps(ATTACKS)};\n"
              "const keep = ['<p class=\"note\">Read the <a href=\"https://intranet/policy.aspx\" target=\"_blank\">policy</a> &amp; sign.</p>',"
              " '<table border=\"1\"><tr><td colspan=\"2\" style=\"color:red\">A</td></tr></table>', '<img src=\"/sites/SEA/SiteAssets/logo.png\" alt=\"Logo\">'];\n"
              "console.log(JSON.stringify({attacks: attacks.map(sanitizeHtml), keep: keep.map(sanitizeHtml)}));\n")
    out = run_ts(tmp_path, script)
    for src, got in zip(ATTACKS, out["attacks"]):
        low = got.lower()
        assert not any(x in low for x in ("javascript", "<svg", "<script", "onerror", "onload", "onclick", "ontoggle", "onmouseover",
                                         "<iframe", "expression(", "data:text", "<form", "<object", "<base", "<math")), (src, got)
    assert out["keep"][0] == ('<p class="note">Read the <a href="https://intranet/policy.aspx" target="_blank" rel="noopener noreferrer">'
                              "policy</a> &amp; sign.</p>")
    assert out["keep"][1] == '<table border="1"><tr><td colspan="2" style="color:red">A</td></tr></table>'
    assert out["keep"][2] == '<img src="/sites/SEA/SiteAssets/logo.png" alt="Logo">'


@pytest.mark.skipif(not NODE_OK, reason="needs Node 22.6+ (TypeScript type stripping)")
def test_d6_list_page_uses_the_legacy_view(tmp_path):
    views = {
        "AllItems": {"fields": ["LinkTitle", "Category", "DueDate"], "query": '<OrderBy><FieldRef Name="Title" /></OrderBy>', "rowLimit": 30, "default": True},
        "MyOpen": {"fields": ["LinkTitleNoMenu", "DueDate"], "query": '<OrderBy><FieldRef Name="DueDate" Ascending="FALSE" /></OrderBy>', "rowLimit": 10},
    }
    script = ('import { listPageView, orderbyFromCaml } from "./rt/views.ts";\n'
              f"const views = {json.dumps(views)};\n"
              "console.log(JSON.stringify({main: listPageView(views, ['Title']), other: listPageView({MyOpen: views.MyOpen}, []),"
              " none: listPageView({}, ['Title', 'Status']), caml: orderbyFromCaml('<View><Query><OrderBy><FieldRef Name=\"LinkTitle\" Ascending=\"FALSE\"/><FieldRef Name=\"ID\"/></OrderBy></Query></View>')}));\n")
    out = run_ts(tmp_path, script)
    assert out["main"] == {"fields": ["Title", "Category", "DueDate"], "orderby": "Title", "top": 30, "where": views["AllItems"]["query"]}
    assert out["other"] == {"fields": ["Title", "DueDate"], "orderby": "DueDate desc", "top": 10, "where": views["MyOpen"]["query"]}
    assert out["none"] == {"fields": ["Title", "Status"], "orderby": "ID", "top": 30, "where": None}
    assert out["caml"] == "Title desc,ID"


# ------------------------------------------------------------------ S7
def test_s7_sharepoint_user_lookup_needs_an_exact_login(built, monkeypatch):
    monkeypatch.setenv("SP_SITE_URL", "https://sp.example.com/sites/SEA")
    be = built / "app" / "backend"
    monkeypatch.syspath_prepend(str(be))
    for m in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[m]
    sp_repo = importlib.import_module("app.sp_repo")

    class Resp:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return {"d": {"results": self.data}}

    class Session:
        def get(self, url, params=None):
            if url.endswith("/groups"):
                return Resp([{"Title": "Approvers"}])
            return Resp([{"Id": 7, "LoginName": "i:0#.w|corp\\alice2", "Title": "Alice Two"},
                         {"Id": 8, "LoginName": "i:0#.w|corp\\alice", "Title": "Alice"}])

    repo = object.__new__(sp_repo.SharePointRepo)
    repo.site, repo.s = "https://sp.example.com/sites/SEA", Session()
    assert repo.user_by_login("corp\\alice")["title"] == "Alice"
    assert repo.user_by_login("i:0#.w|corp\\alice")["title"] == "Alice"
    assert repo.user_by_login("corp\\al") is None
    assert repo.user_by_login("") is None


# ------------------------------------------------------------------ D1
def test_d1_columns_whose_rest_name_differs_are_migrated_and_checked():
    from sp2react.analysis.fields import map_field
    from sp2react.migrate import transform

    raw = {"InternalName": "_x0032_nd_x0020_Approver", "Title": "2nd Approver", "TypeAsString": "User", "AllowMultipleValues": False,
           "EntityPropertyName": "OData__x0032_nd_x0020_Approver"}
    f = map_field(raw, {})
    assert f["rest_name"] == "OData__x0032_nd_x0020_Approver"
    old_spec = {k: v for k, v in f.items() if k != "rest_name"}                    # specs written by 0.1.2
    num = map_field({"InternalName": "_x0031_stScore", "Title": "1st Score", "TypeAsString": "Number"}, {})   # SharePoint 2010: no EntityPropertyName
    assert num["rest_name"] == "OData__x0031_stScore"
    items = [{"ID": i, "OData__x0032_nd_x0020_ApproverId": 9, "OData__x0031_stScore": 4.5} for i in (1, 2)]
    for fields in ([f, num], [old_spec, num]):
        rows = transform(items, fields)
        assert [r["_x0032_nd_x0020_Approver"] for r in rows] == [9, 9] and rows[0]["_x0031_stScore"] == 4.5


def test_d1_reconcile_reports_fields_missing_from_the_export(tmp_path):
    from sp2react.migrate import reconcile, report_markdown
    (tmp_path / "X.jsonl").write_text(json.dumps({"ID": 1, "Title": "a", "Created": None, "Modified": None}) + "\n")
    fields = [{"name": "Title", "type": "text"}, {"name": "Renamed", "type": "text"}]
    rep = reconcile(tmp_path, {"X": [{"ID": 1, "Title": "a", "Renamed": None}]}, {"X": {"fields": fields}})
    assert not rep["ok"] and rep["lists"]["X"]["fields_not_in_export"] == ["Renamed"]
    assert "Not found in any exported item" in report_markdown(rep, {})


# ------------------------------------------------------------------ D5
def test_d5_throttled_requests_are_retried(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        m.faults[f"lists(guid'{VENDOR_LIST}')/fields"] = [429, 503]
        p = Pipeline(make(tmp_path, m.site_url, run_builds=False), llm=scripted(), progress=lambda s: None)
        p.run(until="inventory")
    assert p.status(None, "extract") == "done"
    assert json.loads((tmp_path / "ws" / "legacy" / "lists" / "VendorRequests" / "fields.json").read_text())["d"]["results"]
    assert sum(1 for _, path in m.requests if f"lists(guid'{VENDOR_LIST}')/fields" in path) == 3


def test_d5_extract_fails_when_a_list_schema_cannot_be_read(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        m.faults[f"lists(guid'{VENDOR_LIST}')/fields"] = [500] * 20
        p = Pipeline(make(tmp_path, m.site_url, run_builds=False), llm=scripted(), progress=lambda s: None)
        p.run()
    assert p.status(None, "extract") == "failed"
    assert "fields of Vendor" in p.state["global"]["extract"]["detail"]
    assert p.status(None, "inventory") is None


def test_d5_retry_after_is_honoured_and_capped():
    from sp2react.sharepoint.client import SharePointClient

    class R:
        def __init__(self, ra):
            self.headers = {"Retry-After": ra} if ra is not None else {}

    c = SharePointClient(SharePointConfig(site_url="https://sp.example.com/sites/SEA", auth="none", max_retry_wait=30))
    assert c._wait(0, R("7")) == 7 and c._wait(0, R("9999")) == 30 and c._wait(3, R(None)) == 8


# ------------------------------------------------------------------ D10
def test_d10_pages_with_the_same_file_name_get_their_own_screens(tmp_path):
    from sp2react.analysis.inventory import Legacy, screens
    root = tmp_path / "legacy"
    shutil.copytree(Path(__file__).parent / "fixtures" / "legacy-site", root)
    (root / "pages" / "Pages").mkdir()
    for f in ("Dashboard.aspx", "Dashboard.aspx.webparts.json"):
        shutil.copyfile(root / "pages" / "SitePages" / f, root / "pages" / "Pages" / f)
    ids = [s["id"] for s in screens(Legacy(root))]
    assert len(ids) == len(set(ids))
    assert {"Pages-Dashboard", "SitePages-Dashboard", "VendorRequests-form"} <= set(ids)


# ------------------------------------------------------------------ D11
def test_d11_regeneration_keeps_changed_files(tmp_path):
    from sp2react.scaffold.generate import NEW_SUFFIX, copy_templates, read_manifest, write_manifest
    out = tmp_path / "app"
    first = copy_templates(out)
    write_manifest(out, first, {})
    auth = out / "backend" / "app" / "auth.py"
    auth.write_text(auth.read_text() + "\n# Entra ID validation added by the team\n")
    (out / "backend" / "app" / "api.py").write_text("stale but unchanged since generation")
    write_manifest(out, ["backend/app/api.py"], read_manifest(out))                 # as if sp2react wrote it
    kept: list[str] = []
    second = copy_templates(out, kept)
    assert kept == ["backend/app/auth.py"] and "backend/app/auth.py" not in second
    assert "Entra ID validation added by the team" in auth.read_text()
    assert (auth.parent / ("auth.py" + NEW_SUFFIX)).read_text() == (TEMPLATES / "backend" / "app" / "auth.py").read_text()
    assert (out / "backend" / "app" / "api.py").read_text() == (TEMPLATES / "backend" / "app" / "api.py").read_text()


def test_d11_apps_from_earlier_releases_are_upgraded_unless_edited(tmp_path, monkeypatch):
    from sp2react.scaffold import generate as g
    out = tmp_path / "app"
    g.copy_templates(out)
    old = out / "backend" / "app" / "odata.py"
    old.write_text("# odata.py exactly as 0.1.x wrote it\n")
    edited = out / "backend" / "app" / "store.py"
    edited.write_text("# changed by the team\n")
    (out / g.MANIFEST).unlink(missing_ok=True)                                         # 0.1.2 wrote no manifest
    monkeypatch.setattr(g, "_released", lambda: {"backend/app/odata.py": [g._sha(old.read_bytes())]})
    kept: list[str] = []
    g.copy_templates(out, kept)
    assert old.read_text() == (TEMPLATES / "backend" / "app" / "odata.py").read_text()
    assert "backend/app/store.py" in kept and edited.read_text() == "# changed by the team\n"


def test_d11_released_hashes_cover_every_published_template():
    data = json.loads((TEMPLATES.parent / "released_templates.json").read_text())
    assert {"backend/app/main.py", "backend/app/auth.py", "frontend/index.html"} <= set(data)


# ------------------------------------------------------------------ D12
def test_d12_list_names_with_spaces_pass_the_gate():
    from sp2react.spec.coverage import ENDPOINT_PATH
    assert ENDPOINT_PATH.match("/api/lists/Change Requests/items/{id}")
    assert ENDPOINT_PATH.match("/api/lists/Vendor's (EMEA)/items")
    for bad in ("/api/lists/../x", "/api/lists/a?b", "/api/lists/a#b", "/api/lists/a%2e%2e", "/other"):
        assert not ENDPOINT_PATH.match(bad), bad


# ------------------------------------------------------------------ review follow-ups
def test_ids_that_collide_after_cleaning_stay_apart(tmp_path):
    from sp2react.analysis.inventory import Legacy, safe_id, screens
    assert safe_id("-Dashboard") == "Dashboard" and safe_id("A B") == "A_B"
    root = tmp_path / "legacy"
    shutil.copytree(Path(__file__).parent / "fixtures" / "legacy-site", root)
    for name in ("A B.aspx", "A_B.aspx"):
        shutil.copyfile(root / "pages" / "SitePages" / "Dashboard.aspx", root / "pages" / "SitePages" / name)
    ids = [s["id"] for s in screens(Legacy(root))]
    assert len(ids) == len({i.lower() for i in ids}) and sum(i.startswith("A_B-") for i in ids) == 2


def test_d11_a_recorded_hash_decides_even_for_placeholder_files(tmp_path):
    from sp2react.scaffold.generate import copy_templates, write_manifest
    out = tmp_path / "app"
    write_manifest(out, copy_templates(out), {})
    html = out / "frontend" / "index.html"
    html.write_text(html.read_text().replace("__SITE_TITLE__", "Sanctions Dashboard (edited by hand)"))
    kept: list[str] = []
    copy_templates(out, kept)
    assert "frontend/index.html" in kept and "edited by hand" in html.read_text()


def test_extract_treats_a_failed_page_listing_as_critical():
    from sp2react.pipeline import critical_extract_error
    assert critical_extract_error({"what": "SitePages library", "error": "GET ... -> HTTP 429 after 5 tries"})
    assert not critical_extract_error({"what": "SitePages library", "error": "GET ... -> HTTP 404: not found"})
    assert critical_extract_error({"what": "web parts of SitePages/Home.aspx", "error": "HTTP 500"})
    assert not critical_extract_error({"what": "site groups (needs permission to enumerate groups)", "error": "HTTP 403"})
