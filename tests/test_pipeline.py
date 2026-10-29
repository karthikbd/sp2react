"""All ten stages against the mock server with scripted agents; gates and the generated app's own tests."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from mock_sharepoint import MockSharePoint
from scripted_agents import scripted
from sp2react.cli import main as cli
from sp2react.config import Config, LLMConfig, PipelineConfig, SharePointConfig
from sp2react.pipeline import Pipeline, StageBlocked


def make(tmp_path, url, **pipeline):
    pipeline.setdefault("data_source", "sqlite")
    return Config(sharepoint=SharePointConfig(site_url=url, auth="cookie"), llm=LLMConfig(provider="scripted"),
                  pipeline=PipelineConfig(workspace=str(tmp_path / "ws"), output=str(tmp_path / "app"), **pipeline))


@pytest.fixture()
def mock(monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        yield m


def test_spec_gate_stops_before_convert(tmp_path, mock):
    p = Pipeline(make(tmp_path, mock.site_url, run_builds=False), llm=scripted(), progress=lambda s: None)
    p.run()
    for sid in ("VendorRequests-form", "Dashboard"):
        assert p.status(sid, "spec") == "done"
        assert p.status(sid, "approve_spec") == "waiting"
        assert p.status(sid, "convert") is None
    assert "33/33 required behaviours covered" in (tmp_path / "ws" / "specs" / "VendorRequests-form.coverage.md").read_text()
    with pytest.raises(StageBlocked):
        p.require("Dashboard", "review")


def test_full_run_with_approvals(tmp_path, mock):
    cfg = make(tmp_path, mock.site_url, run_builds=False)
    p = Pipeline(cfg, llm=scripted(), progress=lambda s: None)
    p.run()
    p.approve("VendorRequests-form", "spec", "tester")
    p.approve("Dashboard", "spec", "tester")
    p = Pipeline(cfg, llm=scripted(), progress=lambda s: None)
    p.run(offline=True)
    for sid in ("VendorRequests-form", "Dashboard"):
        assert [p.status(sid, s) for s in ("convert", "review", "test", "fix", "approve")] == ["done", "done", "done", "skipped", "waiting"], p.state["screens"][sid]
    app = tmp_path / "app"
    assert (app / "frontend" / "src" / "screens" / "Dashboard" / "Page.tsx").exists()
    assert 'import Page1 from "./screens/Dashboard/Page";' in (app / "frontend" / "src" / "App.tsx").read_text()
    seed = json.loads((app / "backend" / "data" / "seed" / "VendorRequests.json").read_text())
    assert seed[0]["RequestDate"] == "2026-09-14" and seed[0]["Department"] == 2
    report = (tmp_path / "ws" / "report.md").read_text()
    assert "| VendorRequests-form | done | done | done | done | done | done | skipped | waiting |" in report
    assert p.state["usage"]["Dashboard"]["spec"]["attempts"] == 1        # unchanged legacy source: spec not regenerated


@pytest.mark.skipif(not shutil.which("npm") or os.environ.get("SP2REACT_SKIP_NPM"), reason="needs npm and network access to the npm registry")
def test_generated_frontend_builds(tmp_path, mock):
    p = Pipeline(make(tmp_path, mock.site_url, auto_approve=True, run_builds=True), llm=scripted(), progress=lambda s: None)
    p.run()
    assert p.status("Dashboard", "test") == "done", (tmp_path / "ws" / "tests" / "iteration-0.md").read_text()[-3000:]
    assert (tmp_path / "app" / "frontend" / "dist" / "index.html").exists()


def test_cli_init_and_status(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert cli(["init"]) == 0
    assert "site_url" in (tmp_path / "sp2react.yaml").read_text()
    assert cli(["init"]) == 1
    assert cli(["status"]) == 0


@pytest.mark.skipif(not shutil.which("npm") or os.environ.get("SP2REACT_SKIP_NPM"), reason="needs npm and network access to the npm registry")
def test_fix_loop_repairs_a_build_failure(tmp_path, mock):
    from scripted_agents import RESP, responder
    from sp2react.llm.providers import ScriptedLLM
    good = (RESP / "page" / "Dashboard.txt").read_text()
    broken = good.replace("const reviewer = inGroup(user, \"Compliance Reviewers\");",
                          "const reviewer = inGroup(user, \"Compliance Reviewers\");\n  const total: number = \"five\";")
    calls = []

    def scripted_with_fix(agent, system, messages):
        calls.append(agent)
        if agent == "page":
            return broken
        if agent == "fix":
            assert "TS2322" in messages[0]["content"]                     # the fix agent sees the real compiler error
            return good.split("<notes>")[0]
        return responder(agent, system, messages)

    p = Pipeline(make(tmp_path, mock.site_url, auto_approve=True, run_builds=True), llm=ScriptedLLM(scripted_with_fix), progress=lambda s: None)
    p.run()
    assert calls.count("fix") == 1
    assert p.status("Dashboard", "fix") == "done" and p.status("Dashboard", "test") == "done"
    assert (tmp_path / "ws" / "tests" / "iteration-1.md").exists()


def test_migration_moves_every_item_and_reconciles(tmp_path, mock):
    from sp2react.migrate import export_lists, read_through_app, reconcile
    p = Pipeline(make(tmp_path, mock.site_url, auto_approve=True, run_builds=False), llm=scripted(), progress=lambda s: None)
    p.run()
    assert p.state["global"]["migrate"]["status"] == "done"
    assert p.state["global"]["reconcile"]["status"] == "done", p.state["global"]["reconcile"]
    md = (tmp_path / "ws" / "reconciliation.md").read_text()
    assert "all lists match" in md and "| VendorRequests | 3 | 3 | 0 | 0 | 0 | 0 | ok |" in md
    assert (tmp_path / "app" / "backend" / "data" / "attachments" / "VendorRequests" / "2" / "customs-bond.pdf").exists()

    # paging: a 2-item page size still exports all 13 countries
    out = tmp_path / "paged"
    summary = export_lists(p.sp, p.legacy.site, ["Countries"], out, page_size=2)
    assert summary["Countries"]["items"] == 13
    assert sum(1 for verb, path in mock.requests if "skiptoken" in path) == 6

    # a damaged database is caught field by field
    specs = {n: {"fields": l.fields} for sp in [p.load_spec("VendorRequests-form")] for n, l in sp.lists.items()}
    items = read_through_app(tmp_path / "app", tmp_path / "check.db", load=True)
    items["VendorRequests"][1]["ContractValue"] = 1.0
    items["VendorRequests"][1]["Country"] = {"id": 99, "title": None}
    items["VendorRequests"].pop(0)
    rep = reconcile(tmp_path / "ws" / "data-export", items, specs)
    vr = rep["lists"]["VendorRequests"]
    assert not rep["ok"] and vr["missing_in_app"] == [1]
    assert {(m["id"], m["field"]) for m in vr["field_mismatches"]} >= {(2, "ContractValue"), (2, "Country")}
    assert vr["orphan_lookups"] == [{"id": 2, "field": "Country", "points_to": 99, "list": "Countries"}]


def test_existing_database_mode_reads_no_list_items(tmp_path, mock, monkeypatch):
    """data_source=database: SharePoint gives code + schema only; the app runs on the team's migrated tables."""
    import migrated_db
    from fastapi.testclient import TestClient
    url = migrated_db.build(tmp_path / "sea.db")
    monkeypatch.setenv("SP2REACT_DB_URL", url)
    cfg = make(tmp_path, mock.site_url, auto_approve=True, run_builds=False, data_source="database")
    cfg.database.mapping = str(tmp_path / "db-mapping.json")
    p = Pipeline(cfg, llm=scripted(), progress=lambda s: None)
    p.run()
    # no business data crossed HTTP: no item, attachment, user or rendered-page requests
    paths = [path.split("?")[0] for _, path in mock.requests]
    assert not [x for x in paths if "/items" in x or "siteusers" in x or "Attachments" in x or "/_api/" not in x], paths
    assert p.state["global"]["map_db"]["status"] == "done", p.state["global"]["map_db"]
    assert p.state["usage"]["database"]["map_db"]["attempts"] == 1          # the agent resolved countries.country_name
    assert "country_name" in (tmp_path / "ws" / "db-mapping.md").read_text()
    for sid in ("VendorRequests-form", "Dashboard"):
        assert p.status(sid, "test") == "done", (p.state["screens"][sid], (tmp_path / "ws" / "tests" / "iteration-0.md").read_text()[-2000:])

    # the generated API on the migrated tables: SQL filters, lookups, people, rules, etags, attachments
    import importlib, sys
    be = tmp_path / "app" / "backend"
    monkeypatch.setenv("DB_URL", url)
    monkeypatch.setenv("MAPPING_FILE", str(be / "mapping.json"))
    monkeypatch.setenv("DATA_SOURCE", "database")
    sys.path.insert(0, str(be))
    for m in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[m]
    app = importlib.import_module("app.main").create_app()
    c = TestClient(app, headers={"X-User": "corp\\alice"})
    r = c.get("/api/lists/VendorRequests/items", params={"$filter": "Country/Title eq 'Nigeria' or Status eq 'Approved'", "$orderby": "ID"}).json()
    assert [i["ID"] for i in r["value"]] == [1, 2] and r["count"] == 2
    item = c.get("/api/lists/VendorRequests/items/2").json()
    assert item["Country"] == {"id": 8, "title": "Nigeria"} and item["Requester"]["title"] == "Carol Nguyen"
    assert item["RequestDate"] == "2026-10-06" and item["Attachments"] == ["customs-bond.pdf"] and item["_etag"] == '"2"'
    bad = c.post("/api/lists/VendorRequests/items", json={"values": {"Title": "X", "VendorType": "Supplier", "Department": 2, "CostCenter": 3,
                                                                       "Country": 8, "ContractValue": "500000", "TaxID": "123456789"}})
    msgs = {e["message"] for e in bad.json()["errors"]}
    assert bad.status_code == 422 and "A Second Approver is required for contracts over $100,000." in msgs
    ok = c.post("/api/lists/VendorRequests/items", json={"values": {"Title": "Kestrel", "VendorType": "Supplier", "Department": 2, "CostCenter": 3,
                                                                      "Country": 3, "ContractValue": "1000", "TaxID": "555666777", "RequestDate": "2026-10-28"}})
    assert ok.status_code == 201, ok.text
    new = ok.json()
    assert new["Status"] == "Submitted" and new["RiskRating"] == "Low" and new["Requester"]["login"] == "corp\\alice"
    assert c.patch(f"/api/lists/VendorRequests/items/{new['ID']}", json={"values": {"Title": "Kestrel 2"}}, headers={"If-Match": '"9"'}).status_code == 412
    upd = c.patch(f"/api/lists/VendorRequests/items/{new['ID']}", json={"values": {"Title": "Kestrel 2"}}, headers={"If-Match": new["_etag"]})
    assert upd.status_code == 200 and upd.json()["_etag"] == '"2"'
    locked = c.patch("/api/lists/VendorRequests/items/1", json={"values": {"Title": "nope"}})
    assert locked.status_code == 423 and locked.json()["message"] == "This request has been approved and can no longer be edited."
    reviewer = TestClient(app, headers={"X-User": "corp\\bob"})
    assert reviewer.get("/api/me").json()["groups"] == ["Compliance Reviewers"]
    sys.path.remove(str(be))


def test_database_mode_reconciles_lists_with_existing_tables_when_allowed(tmp_path, mock, monkeypatch):
    """Opt-in check of the team's earlier migration: SharePoint list items vs the mapped tables, field by field."""
    import migrated_db
    from sqlalchemy import create_engine, text
    url = migrated_db.build(tmp_path / "sea.db")
    with create_engine(url).begin() as c:      # simulate a migration defect
        c.execute(text("update tbl_vendor_requests set contract_value = 72.0 where request_id = 3"))
    monkeypatch.setenv("SP2REACT_DB_URL", url)
    cfg = make(tmp_path, mock.site_url, auto_approve=True, run_builds=False, data_source="database")
    cfg.database.mapping = str(tmp_path / "db-mapping.json")
    cfg.security.sharepoint_item_reads = True
    p = Pipeline(cfg, llm=scripted(), progress=lambda s: None)
    p.run()
    assert p.state["global"]["reconcile"]["status"] == "failed"
    md = (tmp_path / "ws" / "reconciliation.md").read_text()
    assert "ID 3 `ContractValue`: SharePoint `72000.0` vs app `72.0`" in md
    assert p.status("VendorRequests-form", "test") == "failed"
