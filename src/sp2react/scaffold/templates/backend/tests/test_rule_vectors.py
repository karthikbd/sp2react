"""The server rule engine must agree with the browser engine on every shared vector."""
import json
from datetime import date
from pathlib import Path

import pytest

from app import rules as R

VECTORS = json.loads((Path(__file__).resolve().parents[2] / "shared" / "rule_vectors.json").read_text())


@pytest.mark.parametrize("v", VECTORS, ids=[v["name"] for v in VECTORS])
def test_vector(v):
    t = v["type"]
    if t == "evaluate":
        got = R.evaluate(v["cond"], v["ctx"])
    elif t == "validate":
        got = [[e["field"], e["message"], e["rule"]] for e in R.validate(v["fields"], v["rules"], v["ctx"])]
    elif t == "field_state":
        s = R.field_state(v["field"], v["rules"], v["ctx"])
        got = {"visible": s["visible"], "readonly": s["readonly"], "required": s["required"]}
    elif t == "lock":
        r = R.lock(v["rules"], v["ctx"])
        got = r["id"] if r else None
        if r and v.get("message"):
            assert R.fill_template(r["message"], v["ctx"]["values"]) == v["message"]
    elif t == "set_on_save":
        got = R.set_on_save(v["rules"], v["ctx"])
    elif t == "banners":
        got = [R.fill_template(b["message"], v["ctx"]["values"]) for b in R.banners(v["rules"], v["ctx"])]
    elif t == "defaults":
        got = R.defaults(v["fields"], v["rules"], v["user"], date.fromisoformat(v["today"]))
    elif t == "fill":
        got = R.fill_template(v["text"], v["values"])
    elif t == "clear_hidden":
        got = R.clear_hidden(v["fields"], v["rules"], v["ctx"])
    assert got == v["expected"]
