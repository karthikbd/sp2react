"""Values and views that 0.1.2 got wrong: multi-value lookups (D2), date-time zones (D3), hyperlinks and managed
metadata (D4), view filters and paging (D7), the default page size (D8) and wiki page bodies (D9)."""
from __future__ import annotations

import importlib
import json
import shutil
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from test_hardening import NODE_OK, built, load_app, run_ts  # noqa: F401  (fixture re-used)


def app_module(built: Path, monkeypatch, name: str):
    load_app(built, monkeypatch, AUTH_MODE="dev")
    return importlib.import_module(f"app.{name}")


# ------------------------------------------------------------------ D2
@pytest.mark.skipif(not NODE_OK, reason="needs Node 22.6+")
def test_d2_multi_value_lookup_keeps_every_value(tmp_path, built, monkeypatch):
    out = run_ts(tmp_path, 'import { lookupValue, selectedIds } from "./rt/values.ts";\n'
                           'const opts = [{id: 1, title: "SAP"}, {id: 2, title: "CRM"}, {id: 3, title: "Data Lake"}];\n'
                           'console.log(JSON.stringify({multi: lookupValue(opts, ["1", "3"], true), one: lookupValue(opts, ["2"], false),'
                           ' ids: selectedIds([{id: 1}, {id: 3}]), none: lookupValue(opts, [], false)}));\n')
    assert out == {"multi": [{"id": 1, "title": "SAP"}, {"id": 3, "title": "Data Lake"}], "one": {"id": 2, "title": "CRM"},
                   "ids": ["1", "3"], "none": None}
    api = app_module(built, monkeypatch, "api")
    assert api._coerce({"type": "lookup", "multi": True}, ["1", 3, {"id": 4}]) == [1, 3, {"id": 4}]


# ------------------------------------------------------------------ D3
@pytest.mark.skipif(not NODE_OK, reason="needs Node 22.6+")
def test_d3_date_time_is_edited_in_local_time_and_stored_in_utc(tmp_path, built, monkeypatch):
    monkeypatch.setenv("TZ", "America/New_York")
    out = run_ts(tmp_path, 'import { fromLocalInput, toLocalInput } from "./rt/values.ts";\n'
                           'console.log(JSON.stringify({shown: toLocalInput("2026-10-06T18:30:00Z"), saved: fromLocalInput("2026-10-06T14:30"),'
                           ' winter: toLocalInput("2026-01-15T18:30:00Z"), naive: toLocalInput("2026-10-06T18:30:00"), empty: fromLocalInput("")}));\n')
    assert out == {"shown": "2026-10-06T14:30", "saved": "2026-10-06T18:30:00Z", "winter": "2026-01-15T13:30", "naive": "2026-10-06T18:30", "empty": None}
    api = app_module(built, monkeypatch, "api")
    assert api._coerce({"type": "datetime"}, "2026-10-06T14:30:00-04:00") == "2026-10-06T18:30:00Z"
    assert api._coerce({"type": "datetime"}, "2026-10-06T18:30:00.000Z") == "2026-10-06T18:30:00Z"


# ------------------------------------------------------------------ D4
def test_d4_hyperlink_keeps_its_description_and_terms_their_label():
    from sp2react.analysis.fields import map_fields
    from sp2react.migrate import reconcile, transform
    raw = {"d": {"results": [
        {"InternalName": "Reference", "Title": "Reference", "TypeAsString": "URL", "Id": "a1"},
        {"InternalName": "Classification", "Title": "Classification", "TypeAsString": "TaxonomyFieldType", "Id": "b1", "TextField": "{c1}"},
        {"InternalName": "f9e8d7c6b5a4", "Title": "Classification_0", "TypeAsString": "Note", "Id": "c1", "Hidden": True},
    ]}}
    fields, _ = map_fields(raw, {})
    assert [f["name"] for f in fields] == ["Reference", "Classification"]
    tax = fields[1]
    assert tax["read_only"] and tax["label_field"] == "f9e8d7c6b5a4"
    item = {"ID": 1, "Reference": {"__metadata": {"type": "SP.FieldUrlValue"}, "Description": "Runbook", "Url": "https://intranet/rb/42"},
            "Classification": {"__metadata": {"type": "SP.Taxonomy.TaxonomyFieldValue"}, "Label": "3", "TermGuid": "9D3C-1", "WssId": 3},
            "f9e8d7c6b5a4": "Confidential|9d3c-1"}
    row = transform([item], fields)[0]
    assert row["Reference"] == {"url": "https://intranet/rb/42", "description": "Runbook"}
    assert row["Classification"] == {"label": "Confidential", "term_id": "9D3C-1"}


def test_d4_reconcile_notices_a_lost_link_description(tmp_path):
    from sp2react.migrate import reconcile
    item = {"ID": 1, "Reference": {"Description": "Runbook", "Url": "https://intranet/rb/42"}, "Created": None, "Modified": None}
    (tmp_path / "X.jsonl").write_text(json.dumps(item) + "\n")
    fields = [{"name": "Reference", "type": "url"}]
    ok = reconcile(tmp_path, {"X": [{"ID": 1, "Reference": {"url": "https://intranet/rb/42", "description": "Runbook"}}]}, {"X": {"fields": fields}})
    lost = reconcile(tmp_path, {"X": [{"ID": 1, "Reference": {"url": "https://intranet/rb/42", "description": None}}]}, {"X": {"fields": fields}})
    assert ok["ok"] and not lost["ok"] and lost["lists"]["X"]["field_mismatches"][0]["field"] == "Reference"


def test_d4_hyperlink_round_trips_through_the_api(built, monkeypatch):
    api = app_module(built, monkeypatch, "api")
    assert api._coerce({"type": "url"}, "https://x/y") == {"url": "https://x/y", "description": None}
    assert api._coerce({"type": "url"}, {"Url": "https://x", "Description": "X"}) == {"url": "https://x", "description": "X"}
    assert api._coerce({"type": "url"}, {"url": ""}) is None


# ------------------------------------------------------------------ D7
CAML_CASES = {
    "eq_text": ('<Where><Eq><FieldRef Name="Status" /><Value Type="Text">Approved</Value></Eq></Where>', "Status eq 'Approved'"),
    "and_or": ('<Where><And><Or><Eq><FieldRef Name="Status"/><Value Type="Choice">Submitted</Value></Eq><Eq><FieldRef Name="Status"/>'
               '<Value Type="Choice">Under Review</Value></Eq></Or><Geq><FieldRef Name="ContractValue"/><Value Type="Currency">100000</Value></Geq></And></Where>',
               "(Status eq 'Submitted' or Status eq 'Under Review') and ContractValue ge 100000"),
    "me": ('<Where><Eq><FieldRef Name="Requester" /><Value Type="Integer"><UserID /></Value></Eq></Where>', "Requester/Id eq 6"),
    "lookup_id": ('<Where><Eq><FieldRef Name="Country" LookupId="TRUE" /><Value Type="Lookup">8</Value></Eq></Where>', "Country/Id eq 8"),
    "lookup_text": ('<Where><Eq><FieldRef Name="Country" /><Value Type="Lookup">Nigeria</Value></Eq></Where>', "Country/Title eq 'Nigeria'"),
    "today": ('<Where><Lt><FieldRef Name="DueDate" /><Value Type="DateTime"><Today OffsetDays="-7" /></Value></Lt></Where>', "DueDate lt datetime'2026-11-12'"),
    "null": ('<Where><IsNull><FieldRef Name="SecondApprover" /></IsNull></Where>', "SecondApprover eq null"),
    "contains": ('<Where><Contains><FieldRef Name="LinkTitle" /><Value Type="Text">O\'Brien</Value></Contains></Where>', "substringof('O''Brien', Title)"),
    "begins": ('<Where><BeginsWith><FieldRef Name="Title" /><Value Type="Text">K</Value></BeginsWith></Where>', "startswith(Title, 'K')"),
    "in": ('<Where><In><FieldRef Name="Status" /><Values><Value Type="Text">A</Value><Value Type="Text">B</Value></Values></In></Where>',
           "(Status eq 'A' or Status eq 'B')"),
    "bool": ('<Query><Where><Eq><FieldRef Name="Approved" /><Value Type="Boolean">0</Value></Eq></Where><OrderBy><FieldRef Name="ID"/></OrderBy></Query>',
             "Approved eq false"),
}


@pytest.mark.skipif(not NODE_OK, reason="needs Node 22.6+")
def test_d7_view_filters_become_api_filters(tmp_path, built, monkeypatch):
    script = ('import { camlWhereToOData } from "./rt/caml.ts";\n'
              f"const cases = {json.dumps({k: v[0] for k, v in CAML_CASES.items()})};\n"
              "const out = Object.fromEntries(Object.entries(cases).map(([k, x]) => [k, camlWhereToOData(x, {userId: 6, today: '2026-11-19'})]));\n"
              "out.unknown = camlWhereToOData('<Where><Membership Type=\"CurrentUserGroups\"><FieldRef Name=\"AssignedTo\"/></Membership></Where>', {});\n"
              "out.userless = camlWhereToOData(cases.me, {});\n"
              "out.none = camlWhereToOData('<OrderBy><FieldRef Name=\"ID\"/></OrderBy>', {});\n"
              "console.log(JSON.stringify(out));\n")
    out = run_ts(tmp_path, script)
    for k, (_, want) in CAML_CASES.items():
        assert out[k] == {"filter": want, "unsupported": []}, (k, out[k])
    assert "filter" not in out["unknown"] and out["unknown"]["unsupported"] == ["<Membership>"]
    assert "filter" not in out["userless"] and out["userless"]["unsupported"]
    assert out["none"] == {"unsupported": []}
    odata = app_module(built, monkeypatch, "odata")             # every filter is one the generated API accepts
    for k, (_, want) in CAML_CASES.items():
        odata.compile_filter(want)


# ------------------------------------------------------------------ D8
def test_d8_api_pages_like_sharepoint_when_no_top_is_given(built, monkeypatch):
    app = load_app(built, monkeypatch, AUTH_MODE="dev")
    c = TestClient(app)
    repo = app.state.repo
    have = c.get("/api/lists/Countries/items", params={"$top": 5000}).json()["count"]
    for i in range(120 - have):
        repo.create("Countries", {"Title": f"Country {i}"}, {"id": 1})
    r = c.get("/api/lists/Countries/items").json()
    assert len(r["value"]) == 100 and r["count"] == 120
    assert len(c.get("/api/lists/Countries/items", params={"$top": 999999}).json()["value"]) == 120
    assert len(c.get("/api/lists/Countries/items", params={"$top": 7, "$skip": 115}).json()["value"]) == 5


# ------------------------------------------------------------------ D9
def test_d9_wiki_page_text_is_extracted_and_analysed(tmp_path):
    from sp2react.analysis.aspx import load_page
    from sp2react.sharepoint.extract import Extractor

    class Client:
        site_url, item_reads = "https://sp.corp.local/sites/SEA", False

        def server_relative_url(self, p):
            return "/sites/SEA/" + p

        def site_relative(self, p):
            return p.replace("/sites/SEA/", "", 1)

        def file_text(self, rel):
            return '<%@ Page %><SharePoint:EmbeddedFormField FieldName="WikiField" runat="server" />'

        def web_parts(self, rel):
            return []

        def wiki_content(self, rel):
            return ('<div class="ExternalClass"><h2>How to request a vendor</h2><p>Fill in the <b>request form</b>.</p>'
                    '<script>alert(1)</script><div class="ms-rtestate-read ms-rte-wpbox" contenteditable="false">'
                    '<div class="ms-rtestate-notify ms-rtestate-read 1a2b" id="div_1a2b"></div></div></div>')

    ex = Extractor(Client(), tmp_path)
    assert ex.page("SitePages/Help.aspx") == "SitePages/Help.aspx"
    assert (tmp_path / "legacy" / "pages" / "SitePages" / "Help.aspx.wiki.html").exists()
    page = load_page(tmp_path / "legacy", "SitePages/Help.aspx")
    frag = page.html_fragments[0]
    assert frag["web_part"] == "Page content" and "How to request a vendor" in frag["html"] and "request form" in frag["html"]
    assert "<script" not in frag["html"] and "ms-rte-wpbox" not in frag["html"]
    assert any("alert(1)" in s["code"] for s in page.inline_scripts)       # the script is inventoried, not shown
