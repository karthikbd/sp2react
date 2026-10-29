"""Builds a database the way a team might have migrated the replica site: renamed tables and columns,
foreign keys, a users table. Used to test data_source=database without a MySQL server (same SQLAlchemy code)."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import (Boolean, Column, Date, DateTime, ForeignKey, Integer, LargeBinary, MetaData, Numeric, String, Table,
                        Text, create_engine)

FX = Path(__file__).parent / "fixtures" / "legacy-site"


def _items(name):
    return json.loads((FX / "lists" / name / "items.json").read_text())["d"]["results"]


def _dt(v):
    return datetime.strptime(v[:19], "%Y-%m-%dT%H:%M:%S") if v else None


def _d(v):
    from sp2react.migrate import date_only
    return date.fromisoformat(date_only(v)) if v else None


def build(path: Path) -> str:
    url = f"sqlite:///{path}"
    eng = create_engine(url)
    md = MetaData()
    users = Table("app_users", md, Column("user_id", Integer, primary_key=True), Column("login", String(100), nullable=False),
                  Column("display_name", String(200)), Column("email", String(200)))
    ug = Table("user_groups", md, Column("user_id", Integer, ForeignKey("app_users.user_id")), Column("group_name", String(100)))
    dep = Table("departments", md, Column("dept_id", Integer, primary_key=True), Column("title", String(255)))
    cc = Table("cost_centers", md, Column("id", Integer, primary_key=True), Column("title", String(255)),
               Column("department_id", Integer, ForeignKey("departments.dept_id")))
    ctry = Table("countries", md, Column("id", Integer, primary_key=True), Column("country_name", String(255)), Column("risk_level", String(20)))
    vr = Table("tbl_vendor_requests", md,
               Column("request_id", Integer, primary_key=True, autoincrement=True), Column("vendor_name", String(255), nullable=False),
               Column("vendor_type", String(50)), Column("department_id", Integer, ForeignKey("departments.dept_id")),
               Column("cost_center_id", Integer, ForeignKey("cost_centers.id")), Column("country_id", Integer, ForeignKey("countries.id")),
               Column("risk_rating", String(20)), Column("high_risk_justification", Text), Column("tax_id", String(9)),
               Column("contract_value", Numeric(18, 2)), Column("second_approver_id", Integer, ForeignKey("app_users.user_id")),
               Column("requester_id", Integer, ForeignKey("app_users.user_id")), Column("request_date", Date), Column("expected_start_date", Date),
               Column("sanctions_screened", Boolean), Column("screening_result", String(50)), Column("status", String(30)),
               Column("reviewer_comments", Text), Column("created_at", DateTime), Column("modified_at", DateTime),
               Column("created_by", Integer), Column("modified_by", Integer), Column("row_version", Integer, nullable=False, default=1))
    alerts = Table("compliance_alerts", md, Column("id", Integer, primary_key=True, autoincrement=True), Column("title", String(255)),
                   Column("vendor_request_id", Integer, ForeignKey("tbl_vendor_requests.request_id")), Column("country", String(255)))
    files = Table("vendor_request_files", md, Column("request_id", Integer), Column("file_name", String(255)), Column("content", LargeBinary))
    md.create_all(eng)
    site = json.loads((FX / "site.json").read_text())
    su = json.loads((FX / "siteusers.json").read_text())["d"]["results"]
    with eng.begin() as c:
        for u in su:
            login = u["LoginName"].split("|")[-1]
            c.execute(users.insert().values(user_id=u["Id"], login=login, display_name=u["Title"], email=u["Email"]))
            for g in site["groups"]:
                if login in g["members"]:
                    c.execute(ug.insert().values(user_id=u["Id"], group_name=g["name"]))
        for r in _items("Departments"):
            c.execute(dep.insert().values(dept_id=r["ID"], title=r["Title"]))
        for r in _items("CostCenters"):
            c.execute(cc.insert().values(id=r["ID"], title=r["Title"], department_id=r["DepartmentId"]))
        for r in _items("Countries"):
            c.execute(ctry.insert().values(id=r["ID"], country_name=r["Title"], risk_level=r["RiskLevel"]))
        for r in _items("VendorRequests"):
            c.execute(vr.insert().values(
                request_id=r["ID"], vendor_name=r["Title"], vendor_type=r["VendorType"], department_id=r["DepartmentId"],
                cost_center_id=r["CostCenterId"], country_id=r["CountryId"], risk_rating=r["RiskRating"],
                high_risk_justification=r["HighRiskJustification"], tax_id=r["TaxID"], contract_value=r["ContractValue"],
                second_approver_id=r["SecondApproverId"], requester_id=r["RequesterId"], request_date=_d(r["RequestDate"]),
                expected_start_date=_d(r["StartDate"]), sanctions_screened=r["SanctionsScreened"], screening_result=r["ScreeningResult"],
                status=r["Status"], reviewer_comments=r["ReviewerComments"], created_at=_dt(r["Created"]), modified_at=_dt(r["Modified"]),
                created_by=r["AuthorId"], modified_by=r["EditorId"], row_version=int(r["_UIVersionString"].split(".")[0])))
        c.execute(files.insert().values(request_id=2, file_name="customs-bond.pdf",
                                        content=(FX / "files/Lists/VendorRequests/Attachments/2/customs-bond.pdf").read_bytes()))
    eng.dispose()
    return url
