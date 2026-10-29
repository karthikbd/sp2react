"""Map SharePoint field definitions (REST /fields) to spec fields, and port simple validation formulas."""
from __future__ import annotations

import re
from typing import Optional

from ..sharepoint.client import unwrap

SYSTEM_FIELDS = {
    "ID", "ContentType", "ContentTypeId", "Modified", "Created", "Author", "Editor", "_UIVersionString", "_UIVersion",
    "_ModerationStatus", "_ModerationComments", "FileLeafRef", "FileRef", "FileDirRef", "LinkTitle", "LinkTitleNoMenu",
    "Edit", "DocIcon", "ItemChildCount", "FolderChildCount", "AppAuthor", "AppEditor", "ComplianceAssetId",
    "_ComplianceFlags", "_ComplianceTag", "_ComplianceTagWrittenTime", "_ComplianceTagUserId", "_IsRecord",
    "SelectTitle", "GUID", "WorkflowVersion", "WorkflowInstanceID", "Order", "owshiddenversion", "_HasCopyDestinations",
    "_CopySource", "_Level", "_IsCurrentVersion", "InstanceID", "MetaInfo", "ProgId", "ScopeId", "HTML_x0020_File_x0020_Type",
    "_EditMenuTableStart", "_EditMenuTableStart2", "_EditMenuTableEnd", "LinkFilenameNoMenu", "LinkFilename", "LinkFilename2",
    "BaseName", "UniqueId", "FSObjType", "SortBehavior", "PermMask", "FileSizeDisplay", "SMTotalSize", "SMLastModifiedDate",
    "SMTotalFileStreamSize", "SMTotalFileCount", "_VirusStatus", "_VirusVendorID", "_VirusInfo", "Restricted", "OriginatorId",
    "NoExecute", "ContentVersion", "_CommentFlags", "_CommentCount", "Attachments", "AccessPolicy", "_ColorTag",
}

TYPE_MAP = {
    "Text": "text", "Note": "note", "Choice": "choice", "MultiChoice": "multichoice", "Lookup": "lookup",
    "LookupMulti": "lookup", "User": "user", "UserMulti": "user", "DateTime": "date", "Number": "number",
    "Currency": "currency", "Boolean": "boolean", "URL": "url", "Calculated": "calculated", "Integer": "number",
    "Counter": "number", "TaxonomyFieldType": "taxonomy", "TaxonomyFieldTypeMulti": "taxonomy",
}


def _choices(f: dict) -> list[str]:
    c = f.get("Choices")
    return list(unwrap(c) or []) if c else []


def map_field(f: dict, list_by_id: dict[str, str]) -> Optional[dict]:
    name = f["InternalName"]
    if f.get("Hidden") or name in SYSTEM_FIELDS:
        return None
    if f.get("ReadOnlyField") and f.get("TypeAsString") not in ("Calculated",):
        return None
    t = f.get("TypeAsString", "Text")
    spec: dict = {"name": name, "label": f.get("Title", name), "type": TYPE_MAP.get(t, "text"), "sp_type": t,
                  "required": bool(f.get("Required"))}
    if f.get("Description"):
        spec["description"] = f["Description"]
    if t == "Text" and f.get("MaxLength"):
        spec["max_length"] = f["MaxLength"]
    if t in ("Choice", "MultiChoice"):
        spec["choices"] = _choices(f)
        spec["format"] = {0: "dropdown", 1: "radio"}.get(f.get("EditFormat", 0), "dropdown") if t == "Choice" else "checkboxes"
        if f.get("FillInChoice"):
            spec["fill_in"] = True
    if t.startswith("Lookup"):
        lid = (f.get("LookupList") or "").strip("{}").lower()
        spec["lookup"] = {"list": list_by_id.get(lid, lid), "field": f.get("LookupField") or "Title"}
        spec["multi"] = bool(f.get("AllowMultipleValues")) or t == "LookupMulti"
    if t.startswith("User"):
        spec["multi"] = bool(f.get("AllowMultipleValues")) or t == "UserMulti"
        spec["groups_allowed"] = f.get("SelectionMode", 0) == 1
    if t == "DateTime":
        spec["type"] = "date" if f.get("DisplayFormat", 0) == 0 else "datetime"
    if t in ("Number", "Currency"):
        for k, sk in (("MinimumValue", "min"), ("MaximumValue", "max")):
            v = f.get(k)
            if v is not None and abs(float(v)) < 1e300:
                spec[sk] = v
        if t == "Number" and f.get("ShowAsPercentage"):
            spec["percent"] = True
    if t == "Note":
        spec["rich_text"] = bool(f.get("RichText"))
        spec["lines"] = f.get("NumberOfLines", 6)
    if t == "Calculated":
        spec["read_only"] = True
        spec["formula"] = f.get("Formula")
    if f.get("EnforceUniqueValues"):
        spec["unique"] = True
    d = f.get("DefaultValue")
    if d not in (None, ""):
        spec["default"] = {"[today]": "@today", "[me]": "@me"}.get(str(d).lower(), _coerce_default(d, spec["type"]))
    return spec


def _coerce_default(v, typ):
    if typ == "boolean":
        return str(v) in ("1", "true", "True")
    if typ in ("number", "currency"):
        try:
            return float(v)
        except ValueError:
            return v
    return v


def map_fields(fields_json: dict, list_by_id: dict[str, str]) -> tuple[list[dict], list[dict]]:
    """-> (spec fields in schema order, column validation formulas)."""
    out, formulas = [], []
    for f in unwrap(fields_json):
        sf = map_field(f, list_by_id)
        if not sf:
            continue
        out.append(sf)
        if f.get("ValidationFormula"):
            formulas.append({"field": sf["name"], "formula": f["ValidationFormula"], "message": f.get("ValidationMessage") or ""})
    # Title first as SharePoint renders it (it is first in the default content type)
    out.sort(key=lambda x: 0 if x["name"] == "Title" else 1)
    return out, formulas


# --------------------------------------------------------------- formulas
FIELD = r"\[([^\]]+)\]"


def translate_formula(formula: str, field_names: dict[str, str]) -> Optional[dict]:
    """Port the common SharePoint validation formula shapes to a spec rule body; None when not recognised.

    field_names maps display name / internal name -> internal name (formulas use display names).
    """
    f = re.sub(r"\s+", "", formula.lstrip("="))

    def fld(token: str) -> Optional[str]:
        return field_names.get(token) or field_names.get(token.lower())

    m = re.fullmatch(rf"LEN\({FIELD}\)(=|<=|>=|<|>)(\d+)", f, re.I)
    if m and fld(m.group(1)):
        op = {"=": "eq", "<=": "lte", ">=": "gte", "<": "lt", ">": "gt"}[m.group(2)]
        return {"kind": "length", "field": fld(m.group(1)), "params": {"op": op, "value": int(m.group(3))}}
    m = re.fullmatch(rf"OR\(ISBLANK\({FIELD}\),LEN\(\1\)(=|<=|>=)(\d+)\)", f, re.I)
    if m and fld(m.group(1)):
        op = {"=": "eq", "<=": "lte", ">=": "gte"}[m.group(2)]
        return {"kind": "length", "field": fld(m.group(1)), "params": {"op": op, "value": int(m.group(3)), "allow_empty": True}}
    m = re.fullmatch(rf"{FIELD}(>=|<=|>|<){FIELD}", f)
    if m and fld(m.group(1)) and fld(m.group(3)):
        op = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt"}[m.group(2)]
        return {"kind": "compare", "field": fld(m.group(1)), "params": {"op": op, "other": fld(m.group(3))}}
    m = re.fullmatch(rf"OR\(ISBLANK\({FIELD}\),(?:ISBLANK\({FIELD}\),)?\1(>=|<=|>|<){FIELD}\)", f)
    if m and fld(m.group(1)) and fld(m.group(4)):
        op = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt"}[m.group(3)]
        return {"kind": "compare", "field": fld(m.group(1)), "params": {"op": op, "other": fld(m.group(4)), "allow_empty": True}}
    m = re.fullmatch(rf"{FIELD}(>=|<=|>|<)(-?\d+(?:\.\d+)?)", f)
    if m and fld(m.group(1)):
        op = {">=": "gte", "<=": "lte", ">": "gt", "<": "lt"}[m.group(2)]
        return {"kind": "range", "field": fld(m.group(1)), "params": {"op": op, "value": float(m.group(3))}}
    # required B when A is true:  OR([A]=FALSE,NOT(ISBLANK([B])))  /  IF([A]=TRUE,NOT(ISBLANK([B])),TRUE)
    m = re.fullmatch(rf"OR\({FIELD}=FALSE,NOT\(ISBLANK\({FIELD}\)\)\)", f, re.I) or \
        re.fullmatch(rf"IF\({FIELD}=TRUE,NOT\(ISBLANK\({FIELD}\)\),TRUE\)", f, re.I)
    if m and fld(m.group(1)) and fld(m.group(2)):
        return {"kind": "required", "field": fld(m.group(2)), "when": {"field": fld(m.group(1)), "eq": True}}
    # required B when A = "x":  OR([A]<>"x",NOT(ISBLANK([B])))
    m = re.fullmatch(rf'OR\({FIELD}<>"([^"]*)",NOT\(ISBLANK\({FIELD}\)\)\)', f, re.I)
    if m and fld(m.group(1)) and fld(m.group(3)):
        return {"kind": "required", "field": fld(m.group(3)), "when": {"field": fld(m.group(1)), "eq": m.group(2)}}
    return None
