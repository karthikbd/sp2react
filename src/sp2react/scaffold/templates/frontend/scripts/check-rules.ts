// Runs shared/rule_vectors.json against the browser rule engine (node >= 22.18 strips the types).
// The backend runs the same vectors in backend/tests/test_rule_vectors.py.
import { readFileSync } from "node:fs";
import * as R from "../src/runtime/rules.ts";

const vectors = JSON.parse(readFileSync(new URL("../../shared/rule_vectors.json", import.meta.url), "utf8"));
let failed = 0;
const eq = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);
for (const v of vectors) {
  let got: unknown;
  if (v.type === "evaluate") got = R.evaluate(v.cond, v.ctx);
  else if (v.type === "validate") got = R.validate(v.fields, v.rules, v.ctx).map((e) => [e.field, e.message, e.rule]);
  else if (v.type === "field_state") { const s = R.fieldState(v.field, v.rules, v.ctx); got = { visible: s.visible, readonly: s.readonly, required: s.required }; }
  else if (v.type === "lock") { const r = R.lock(v.rules, v.ctx); got = r ? r.id : null; if (r && v.message && R.fillTemplate(r.message ?? "", v.ctx.values) !== v.message) got = "bad message"; }
  else if (v.type === "set_on_save") got = R.setOnSave(v.rules, v.ctx);
  else if (v.type === "banners") got = R.banners(v.rules, v.ctx).map((b) => R.fillTemplate(b.message ?? "", v.ctx.values));
  else if (v.type === "defaults") got = R.defaults(v.fields, v.rules, v.user, v.today);
  else if (v.type === "fill") got = R.fillTemplate(v.text, v.values);
  else if (v.type === "clear_hidden") got = R.clearHidden(v.fields, v.rules, v.ctx);
  if (!eq(got, v.expected)) { failed++; console.error(`FAIL ${v.name}: expected ${JSON.stringify(v.expected)} got ${JSON.stringify(got)}`); }
}
console.log(`${vectors.length - failed}/${vectors.length} rule vectors pass (TypeScript engine)`);
process.exit(failed ? 1 : 0);
