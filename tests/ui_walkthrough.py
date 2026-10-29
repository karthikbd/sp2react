"""Drive the generated app in a browser and check the legacy behaviours end to end.

Usage: python tests/ui_walkthrough.py http://localhost:8000 <screenshot dir>
(backend serving the built frontend, seeded with the replica site's data)
"""
from __future__ import annotations

import sys
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
SHOTS = Path(sys.argv[2] if len(sys.argv) > 2 else "shots")
SHOTS.mkdir(parents=True, exist_ok=True)
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL ") + name + (f" - {detail}" if detail else ""), flush=True)


def as_user(page, login: str) -> None:
    page.goto(BASE + "/pages/dashboard")
    page.evaluate(f"localStorage.setItem('sp2react.devUser', {login!r})")


with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page(viewport={"width": 1280, "height": 900})
    dialogs: list[str] = []
    page.on("dialog", lambda d: (dialogs.append(d.message), d.accept()))

    # ---------------------------------------------------------- requester
    as_user(page, "corp\\alice")
    page.goto(BASE + "/pages/dashboard")
    page.wait_for_selector("#db-tile-2 .db-count:text-matches('\\\\d')")
    check("dashboard tiles count by status", page.inner_text("#db-tile-2 .db-count") == "1" and page.inner_text("#db-tile-1 .db-count") == "1")
    check("open high-risk tile flagged", "db-alert" in (page.get_attribute("#db-highrisk", "class") or ""))
    page.wait_for_selector("#db-my tbody tr td a")
    check("my requests shows only Alice's items", page.locator("#db-my tbody tr").count() == 2)
    check("review queue hidden from non-reviewers", page.locator("#db-queue-panel").count() == 0)
    page.screenshot(path=str(SHOTS / "1-dashboard-requester.png"), full_page=True)

    page.goto(BASE + "/lists/vendor-requests/new")
    page.wait_for_selector("#row-Title")
    check("Status hidden on the new form", page.locator("#row-Status").count() == 0)
    check("Reviewer Comments hidden on the new form", page.locator("#row-ReviewerComments").count() == 0)
    check("Requester defaults to current user and is locked",
          "Alice Romero" in page.inner_text("#row-Requester") and page.locator("#row-Requester input").count() == 0)
    check("High Risk Justification hidden until a high-risk country", page.locator("#row-HighRiskJustification").count() == 0)
    page.fill("#fld-Title", "Kestrel Logistics FZE")
    page.select_option("#fld-Department", label="Operations")
    page.wait_for_function("document.querySelectorAll('#fld-CostCenter option').length > 1")
    cc = page.locator("#fld-CostCenter option").all_inner_texts()
    check("cost centers cascade from department", set(c for c in cc if c) == {"OPS-310 Facilities", "OPS-320 Logistics"}, str(cc))
    page.select_option("#fld-CostCenter", label="OPS-320 Logistics")
    page.select_option("#fld-Country", label="Iran")
    page.wait_for_function("document.querySelector('#fld-RiskRating') && document.querySelector('#fld-RiskRating').value === 'High'")
    check("risk rating derived from country and read-only", page.is_disabled("#fld-RiskRating"))
    check("justification appears for high-risk country", page.locator("#row-HighRiskJustification").count() == 1)
    page.fill("#fld-ContractValue", "240,000")
    page.fill("#fld-TaxID", "741852963")
    page.locator("#fld-TaxID").blur()
    page.wait_for_selector("#row-TaxID .ms-formvalidation")
    check("duplicate Tax ID flagged inline on blur", "already exists (ID 1)" in page.inner_text("#row-TaxID .ms-formvalidation"))
    page.click("text=Save")
    page.wait_for_timeout(300)
    check("save blocked by duplicate Tax ID alert", bool(dialogs) and dialogs[-1] == "A vendor request with this Tax ID already exists (ID 1).", dialogs[-1:] and dialogs[-1])
    page.fill("#fld-TaxID", "555666777")
    page.locator("#fld-TaxID").blur()
    page.wait_for_timeout(200)
    page.click("text=Save")
    page.wait_for_timeout(300)
    check("PreSaveAction alert: justification", dialogs[-1] == "High Risk Justification is required for vendors in high-risk countries.", dialogs[-1])
    page.fill("#fld-HighRiskJustification", "Sole licensed carrier for the Bandar Abbas route.")
    page.click("text=Save")
    page.wait_for_timeout(300)
    check("PreSaveAction alert: second approver", dialogs[-1] == "A Second Approver is required for contracts over $100,000.", dialogs[-1])
    page.fill("#row-SecondApprover input", "Dave")
    page.click(".sp-picker-hits li >> text=Dave Fischer")
    page.fill("#fld-StartDate", "2020-01-01")
    page.click("text=Save")
    page.wait_for_timeout(300)
    check("PreSaveAction alert: start date", dialogs[-1] == "Expected Start Date cannot be before the Request Date.", dialogs[-1])
    page.screenshot(path=str(SHOTS / "2-new-form-validation.png"), full_page=True)
    page.fill("#fld-StartDate", "2030-01-15")
    page.click("text=Save")
    page.wait_for_url("**/lists/vendor-requests")
    page.wait_for_selector("text=Kestrel Logistics FZE")
    check("item saved and back to the list", True)
    new_id = page.evaluate("fetch('/api/lists/VendorRequests/items?$filter=' + encodeURIComponent(\"Title eq 'Kestrel Logistics FZE'\"), {headers: {'X-User': 'corp\\\\alice'}}).then(r => r.json()).then(j => j.value[0])")
    check("server set Status=Submitted and kept derived risk", new_id["Status"] == "Submitted" and new_id["RiskRating"] == "High", f"{new_id['Status']}/{new_id['RiskRating']}")

    dialogs.clear()
    page.goto(BASE + "/lists/vendor-requests/edit/1")
    page.wait_for_url("**/display/1**")
    check("approved item locked for requester (alert + redirect to display)",
          dialogs and dialogs[0] == "This request has been approved and can no longer be edited.", dialogs[:1] and dialogs[0])

    page.goto(BASE + "/sites/procurement/Lists/VendorRequests/EditForm.aspx?ID=3&Source=%2Fpages%2Fdashboard")
    page.wait_for_url("**/lists/vendor-requests/edit/3?Source=*")
    check("legacy EditForm.aspx URL redirects to the new route", True)
    page.wait_for_selector("#row-Status")
    check("Status read-only for requester on edit", page.is_disabled("#fld-Status"))
    check("Reviewer Comments hidden from requester on edit", page.locator("#row-ReviewerComments").count() == 0)

    # ----------------------------------------------------------- reviewer
    as_user(page, "corp\\bob")
    page.goto(BASE + "/lists/vendor-requests/edit/3")
    page.wait_for_selector("#row-Status")
    check("reviewer can change Status", not page.is_disabled("#fld-Status"))
    check("reviewer sees Reviewer Comments", page.locator("#row-ReviewerComments").count() == 1)
    page.check("#fld-SanctionsScreened")
    page.select_option("#fld-ScreeningResult", "Confirmed Match")
    page.select_option("#fld-Status", "Rejected")
    dialogs.clear()
    page.click("text=Save")
    page.wait_for_timeout(300)
    check("rejection requires reviewer comments", dialogs and dialogs[-1] == "Please enter reviewer comments when rejecting a request.", dialogs[-1:] and dialogs[-1])
    page.fill("#fld-ReviewerComments", "Confirmed match on the consolidated list.")
    page.click("text=Save")
    page.wait_for_url("**/lists/vendor-requests")
    page.goto(BASE + "/lists/vendor-requests/display/3")
    page.wait_for_selector(".sp-banner-error")
    check("confirmed-match banner on the display form", page.inner_text(".sp-banner-error") == "This vendor has a confirmed sanctions match. Do not issue a purchase order.")
    page.screenshot(path=str(SHOTS / "3-display-banner.png"), full_page=True)

    page.goto(BASE + "/pages/dashboard")
    page.wait_for_selector("#db-queue-panel")
    page.wait_for_selector("#db-alerts li >> text=Confirmed sanctions match")
    check("compliance alert created on save (on_save rule)", "Confirmed sanctions match: Brightline Analytics GmbH (Germany)" in page.inner_text("#db-alerts"))
    check("review queue visible to reviewers", page.locator("#db-queue tbody tr").count() >= 1)
    page.screenshot(path=str(SHOTS / "4-dashboard-reviewer.png"), full_page=True)

    # direct API call cannot bypass the rules (server enforces the same spec)
    r = page.evaluate("""fetch('/api/lists/VendorRequests/items', {method: 'POST', headers: {'Content-Type': 'application/json', 'X-User': 'corp\\\\alice'},
        body: JSON.stringify({values: {Title: 'API bypass', VendorType: 'Supplier', Department: 1, CostCenter: 1, Country: 5, ContractValue: 500000, RequestDate: '2026-10-28', Requester: 7}})})
        .then(async r => ({status: r.status, body: await r.json()}))""")
    msgs = [e["message"] for e in r["body"].get("errors", [])]
    check("API enforces the same rules (422 with legacy messages)", r["status"] == 422 and "A Second Approver is required for contracts over $100,000." in msgs, str(msgs))
    browser.close()

failed = [r for r in results if not r[1]]
print(f"\n{len(results) - len(failed)}/{len(results)} UI checks passed")
sys.exit(1 if failed else 0)
