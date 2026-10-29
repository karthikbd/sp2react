"""Stages 2-4 without any model: extraction from a (mock) server, inventory, base spec and the coverage gate."""
import json
from pathlib import Path

import pytest

from mock_sharepoint import MockSharePoint
from sp2react.analysis.behaviors import classify_script
from sp2react.analysis.fields import translate_formula
from sp2react.analysis.inventory import Legacy, build_inventory, screens
from sp2react.config import SharePointConfig
from sp2react.sharepoint.client import SharePointClient, SharePointError
from sp2react.sharepoint.extract import Extractor
from sp2react.spec.base import base_spec
from sp2react.spec.coverage import check

FIXTURE = Path(__file__).parent / "fixtures" / "legacy-site"


@pytest.fixture()
def extracted(tmp_path, monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        client = SharePointClient(SharePointConfig(site_url=m.site_url, auth="cookie"))
        manifest = Extractor(client, tmp_path, progress=lambda s: None).run()
        yield tmp_path / "legacy", manifest, m


def test_extraction_is_read_only_and_complete(extracted):
    root, manifest, mock = extracted
    assert {verb for verb, _ in mock.requests} == {"GET"}
    assert manifest["summary"] == {"lists": 5, "pages": 4, "files": 7, "errors": 0}
    assert (root / "pages" / "SitePages" / "Dashboard.aspx.webparts.json").exists()
    assert (root / "files" / "SiteAssets" / "html" / "review-instructions.html").exists()   # pulled via a CEWP ContentLink
    site = json.loads((root / "site.json").read_text())
    assert site["groups"][1] == {"name": "Compliance Reviewers", "members": ["corp\\bob"]}
    assert [q["title"] for q in site["quickLaunch"]][:2] == ["Home", "Vendor Requests"]


def test_auth_failure_is_reported(monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "wrong")
    with MockSharePoint() as m:
        with pytest.raises(SharePointError) as e:
            SharePointClient(SharePointConfig(site_url=m.site_url, auth="cookie")).web()
        assert e.value.status == 401


def test_screens_group_list_forms():
    lg = Legacy(FIXTURE)
    scr = {s["id"]: s for s in screens(lg)}
    assert scr["VendorRequests-form"]["pages"] == ["Lists/VendorRequests/NewForm.aspx", "Lists/VendorRequests/EditForm.aspx", "Lists/VendorRequests/DispForm.aspx"]
    assert scr["Dashboard"]["kind"] == "page"
    only = screens(lg, ["/sites/procurement/Lists/VendorRequests/EditForm.aspx"])
    assert [s["id"] for s in only] == ["VendorRequests-form"]


def test_inventory_finds_the_jquery_behaviour():
    lg = Legacy(FIXTURE)
    inv = build_inventory(lg, screens(lg, ["Lists/VendorRequests/NewForm.aspx"])[0])
    kinds = {}
    for b in inv["behaviors"]:
        kinds.setdefault(b["kind"], []).append(b)
    assert len(kinds["save_validation"]) == 6
    assert "High Risk Justification is required for vendors in high-risk countries." in {b["message"] for b in kinds["save_validation"]}
    lock = next(b for b in kinds["message"] if "no longer be edited" in (b.get("message") or ""))
    assert lock["message"] == "This request has been {status.toLowerCase()} and can no longer be edited."
    cascade = kinds["cascade"][0]
    assert {f["name"] for f in cascade["fields"]} == {"Department", "CostCenter"}
    assert kinds["role_check"][0]["detail"]["group"] == "Compliance Reviewers"
    post = next(c for c in inv["calls"] if c.get("method") == "POST")
    assert post["list"] == "Compliance Alerts" and post["body_fields"] == ["Title", "VendorRequestId", "Country"]
    assert post["proposed"]["path"] == "/api/lists/ComplianceAlerts/items"
    assert inv["scripts"]["library"] == [{"path": "SiteAssets/js/jquery-1.12.4.min.js"}, {"path": "SiteAssets/js/jquery.SPServices-2014.02.min.js"}]
    assert any(f["web_part"] == "Reviewer Instructions" for f in inv["html_fragments"])


def test_dashboard_inventory_and_rendered_scripts():
    lg = Legacy(FIXTURE)
    inv = build_inventory(lg, screens(lg, ["SitePages/Dashboard.aspx"])[0])
    merge = next(c for c in inv["calls"] if c.get("method") == "MERGE")
    assert merge["proposed"] == {"method": "PATCH", "path": "/api/lists/VendorRequests/items/{id}", "body": ["Status"], "if_match": True, "purpose": "update item"}
    assert inv["stats"]["rendered_scripts"]["sharepoint"] == 7          # init.js, sp.js ... filtered out
    msg = next(b for b in inv["behaviors"] if b["kind"] == "message")
    assert msg["detail"]["messages"] == ["This request was changed by someone else. Refresh and try again.", "The request could not be approved."]


@pytest.mark.parametrize("url,expected", [
    ("/_layouts/15/sp.js", "sharepoint"), ("/sites/x/SiteAssets/js/jquery-1.12.4.min.js", "library"),
    ("/sites/x/SiteAssets/js/vendor.js", "custom"), ("https://cdn.example.com/x.js", "external"), ("/ScriptResource.axd?d=1", "sharepoint"),
])
def test_script_classification(url, expected):
    assert classify_script(url) == expected


def test_formula_translation():
    names = {"Tax ID": "TaxID", "TaxID": "TaxID", "Start": "StartDate", "Request": "RequestDate", "SanctionsScreened": "SanctionsScreened", "ScreeningResult": "ScreeningResult"}
    assert translate_formula("=LEN([TaxID])=9", names) == {"kind": "length", "field": "TaxID", "params": {"op": "eq", "value": 9}}
    assert translate_formula("=[Start]>=[Request]", names)["params"] == {"op": "gte", "other": "RequestDate"}
    assert translate_formula("=OR([SanctionsScreened]=FALSE,NOT(ISBLANK([ScreeningResult])))", names) == {
        "kind": "required", "field": "ScreeningResult", "when": {"field": "SanctionsScreened", "eq": True}}
    assert translate_formula("=IF(AND([A]>1,[B]<2),TRUE,FALSE)", names) is None


def test_gate_blocks_until_every_behaviour_is_covered():
    lg = Legacy(FIXTURE)
    inv = build_inventory(lg, screens(lg, ["Lists/VendorRequests/NewForm.aspx"])[0])
    base = base_spec(inv)
    rep = check(base, inv)
    assert not rep.ok
    assert any(p.startswith("Not covered: SiteAssets/js/vendor-request-form.js#L183:save_validation") for p in rep.problems)
    assert [r.kind for r in base.rules] == ["length", "required"]        # column + list validation ported mechanically
