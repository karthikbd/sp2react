"""Fail when statement coverage drops below the floor (OpenSSF Best Practices: test_statement_coverage80).

coverage's own fail_under counts branches too; this checks statements, which is what the criterion asks.
Usage: python -m coverage json -o coverage.json && python ci/check_coverage.py coverage.json 80
"""
import json
import sys

totals = json.load(open(sys.argv[1]))["totals"]
floor = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0
stmts, missing = totals["num_statements"], totals["missing_lines"]
pct = 100.0 * (stmts - missing) / stmts if stmts else 100.0
branches = totals.get("num_branches") or 0
bpct = 100.0 * totals.get("covered_branches", 0) / branches if branches else 100.0
print(f"statement coverage {pct:.1f}% ({stmts - missing}/{stmts}), branch coverage {bpct:.1f}% (floor {floor:.0f}% statements)")
sys.exit(0 if pct >= floor else 1)
