"""The ten stages, in order, with gating: a stage runs only when the stage before it finished.

  1 inputs        config + connectivity                      (code)
  2 extract       pull pages, web parts, scripts, lists      (code, read-only)
  3 inventory     behaviours + data calls per screen         (code)
  4 spec          base spec + spec agent + coverage gate     (AI agent, verified)
  5 approve_spec  human gate                                 (you)
  6 convert       scaffold + page/handler agents in parallel (code + AI agents, verified)
  7 review        independent review agent                   (AI agent)
  8 test          pytest, tsc/vite build, rule vectors       (code)
  9 fix           fix agent on failures, max N iterations    (AI agent, verified)
 10 approve       human gate                                 (you)
"""
from __future__ import annotations

import concurrent.futures as cf
import hashlib
import json
import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from .agents.core import Agent, AgentFailed
from .agents.tasks import run_fix_agent, run_handler_agent, run_page_agent, run_review_agent, run_spec_agent
from .analysis.inventory import Legacy, build_inventory, screens as find_screens
from .checks import failures_by_screen, run_all
from .config import Config
from .llm.providers import LLM, make_llm
from .net import policy_for
from .scaffold.generate import generate, refresh_registries
from .spec.base import base_spec
from .spec.coverage import check
from .spec.model import Spec

log = logging.getLogger(__name__)
STAGES = ["inputs", "extract", "inventory", "spec", "approve_spec", "convert", "review", "test", "fix", "approve"]


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class StageBlocked(RuntimeError):
    pass


class Pipeline:
    def __init__(self, cfg: Config, llm: Optional[LLM] = None, progress: Callable[[str], None] = print, sp_client=None):
        self.cfg = cfg
        self._print_lock = threading.Lock()
        self._state_lock = threading.RLock()     # stages run screens in parallel threads
        self.ws = cfg.workspace
        self.out = cfg.output
        self.progress = lambda msg: self._say(progress, msg)
        self._llm = llm
        self._sp = sp_client
        self.ws.mkdir(parents=True, exist_ok=True)
        self.state_file = self.ws / "state.json"
        self.state = json.loads(self.state_file.read_text()) if self.state_file.exists() else {"global": {}, "screens": {}, "usage": {}}

    def _say(self, sink, msg: str) -> None:
        with self._print_lock:   # agents report from worker threads
            sink(msg)

    # ----------------------------------------------------------- plumbing
    @property
    def llm(self) -> LLM:
        if self._llm is None:
            self._llm = make_llm(self.cfg.llm, policy_for(self.cfg))
        return self._llm

    @property
    def sp(self):
        if self._sp is None:
            from .sharepoint.client import SharePointClient
            self._sp = SharePointClient(self.cfg.sharepoint, policy=policy_for(self.cfg), item_reads=self.cfg.item_reads_allowed)
        return self._sp

    @staticmethod
    def _write_atomic(path: Path, text: str) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)

    def save(self) -> None:
        with self._state_lock:
            self._write_atomic(self.state_file, json.dumps(self.state, indent=2))

    def mark(self, sid: Optional[str], stage: str, status: str, detail: str = "", **extra) -> None:
        with self._state_lock:
            bucket = self.state["global"] if sid is None else self.state["screens"].setdefault(sid, {})
            bucket[stage] = {"status": status, "at": _now(), "detail": detail, **extra}
            self.save()
        self.progress(f"[{stage}] {sid or 'site'}: {status}{' - ' + detail if detail else ''}")

    def status(self, sid: Optional[str], stage: str) -> Optional[str]:
        bucket = self.state["global"] if sid is None else self.state["screens"].get(sid, {})
        return (bucket.get(stage) or {}).get("status")

    def require(self, sid: Optional[str], stage: str) -> None:
        """Gate: the previous stage must be done (fixes 'review started while convert was still running')."""
        idx = STAGES.index(stage)
        prev = STAGES[idx - 1] if idx else None
        if prev is None:
            return
        scope = None if prev in ("inputs", "extract") else sid
        st = self.status(scope, prev)
        if prev == "fix" and st in ("done", "skipped"):
            return
        if st != "done":
            raise StageBlocked(f"{stage} for {sid or 'site'} needs '{prev}' to be done (it is {st or 'not started'})")

    def agent(self, name: str, output: str) -> Agent:
        return Agent(name, self.llm, self.ws, output=output, retries=self.cfg.pipeline.agent_retries, progress=self.progress)

    def _usage(self, sid: str, stage: str, res) -> None:
        with self._state_lock:
            self._usage_locked(sid, stage, res)

    def _usage_locked(self, sid: str, stage: str, res) -> None:
        u = self.state["usage"].setdefault(sid, {})
        cur = u.setdefault(stage, {"input_tokens": 0, "output_tokens": 0, "attempts": 0, "seconds": 0})
        cur["input_tokens"] += res.input_tokens
        cur["output_tokens"] += res.output_tokens
        cur["attempts"] += res.attempts
        cur["seconds"] += round(res.seconds, 1)
        self.save()

    @property
    def legacy(self) -> Legacy:
        return Legacy(self.ws / "legacy")

    def screens(self, pages: Optional[list[str]] = None) -> list[dict]:
        f = self.ws / "screens.json"
        if pages is None and f.exists():
            return json.loads(f.read_text())
        return find_screens(self.legacy, pages)

    def load_spec(self, sid: str) -> Spec:
        return Spec.model_validate_json((self.ws / "specs" / f"{sid}.json").read_text(encoding="utf-8"))

    def load_inventory(self, sid: str) -> dict:
        return json.loads((self.ws / "inventory" / f"{sid}.json").read_text(encoding="utf-8"))

    def approvals(self) -> dict:
        f = self.ws / "approvals.json"
        return json.loads(f.read_text()) if f.exists() else {}

    def approve(self, sid: str, gate: str = "spec", by: str = "") -> None:
        with self._state_lock:
            a = self.approvals()
            a.setdefault(sid, {})[gate] = {"at": _now(), "by": by}
            self._write_atomic(self.ws / "approvals.json", json.dumps(a, indent=2))
        stage = "approve_spec" if gate == "spec" else "approve"
        self.mark(sid, stage, "done", f"approved {by}".strip())

    # -------------------------------------------------------------- stages
    def stage_inputs(self, offline: bool) -> None:
        self.mark(None, "inputs", "running")
        if offline:
            if not (self.ws / "legacy" / "site.json").exists():
                self.mark(None, "inputs", "failed", "offline run needs an existing extraction in the workspace")
                raise StageBlocked("no extracted site in the workspace")
            self.mark(None, "inputs", "done", "offline: using the existing extraction")
            return
        web = self.sp.web()
        self.mark(None, "inputs", "done", f"connected to '{web.get('Title')}'")

    def stage_extract(self, pages: Optional[list[str]], offline: bool) -> None:
        self.require(None, "extract")
        if offline:
            self.mark(None, "extract", "done", "offline: skipped")
            return
        from .sharepoint.extract import Extractor
        self.mark(None, "extract", "running")
        man = Extractor(self.sp, self.ws, self.progress).run(pages, self.cfg.sharepoint.sample_items)
        s = man["summary"]
        self.mark(None, "extract", "done", f"{s['lists']} lists, {s['pages']} pages, {s['files']} custom files, {s['errors']} errors", summary=s)

    def stage_inventory(self, pages: Optional[list[str]]) -> list[dict]:
        self.require(None, "inventory")
        legacy = self.legacy
        scrs = find_screens(legacy, pages)
        (self.ws / "screens.json").write_text(json.dumps(scrs, indent=2), encoding="utf-8")
        (self.ws / "inventory").mkdir(exist_ok=True)
        for sc in scrs:
            self.mark(sc["id"], "inventory", "running")
            inv = build_inventory(legacy, sc)
            (self.ws / "inventory" / f"{sc['id']}.json").write_text(json.dumps(inv, indent=2), encoding="utf-8")
            st = inv["stats"]
            self.mark(sc["id"], "inventory", "done",
                      f"{st['custom_scripts']} custom scripts, {st['behaviors_must']} behaviours to carry, {st['data_calls']} data calls, {st['unresolved']} unresolved",
                      stats=st)
        return scrs

    def _spec_one(self, sid: str) -> None:
        self.require(sid, "spec")
        inv = self.load_inventory(sid)
        inv_hash = hashlib.sha256(json.dumps(inv, sort_keys=True).encode()).hexdigest()[:16]
        prev = self.state["screens"].get(sid, {}).get("spec") or {}
        if prev.get("status") == "done" and prev.get("inventory_hash") == inv_hash and (self.ws / "specs" / f"{sid}.json").exists():
            self.progress(f"[spec] {sid}: unchanged since the last run (legacy source identical), keeping the spec")
            if self.approvals().get(sid, {}).get("spec") or self.cfg.pipeline.auto_approve:
                if self.status(sid, "approve_spec") != "done":
                    self.approve(sid, "spec", "auto_approve" if self.cfg.pipeline.auto_approve else "")
            return
        if prev.get("inventory_hash") and prev.get("inventory_hash") != inv_hash:
            a = self.approvals()
            if a.get(sid, {}).pop("spec", None):
                (self.ws / "approvals.json").write_text(json.dumps(a, indent=2), encoding="utf-8")
                self.progress(f"[spec] {sid}: legacy source changed, previous spec approval withdrawn")
        self.mark(sid, "spec", "running")
        base = base_spec(inv)
        (self.ws / "specs").mkdir(exist_ok=True)
        rep0 = check(base, inv)
        if rep0.ok:
            spec, note = base, "base spec already covers everything (no agent needed)"
        else:
            spec, res = run_spec_agent(self.agent("spec", "json"), self.legacy, inv, base)
            self._usage(sid, "spec", res)
            note = f"spec agent accepted on attempt {res.attempts}"
        rep = check(spec, inv)
        (self.ws / "specs" / f"{sid}.json").write_text(spec.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
        (self.ws / "specs" / f"{sid}.coverage.md").write_text(coverage_markdown(spec, inv, rep), encoding="utf-8")
        self.mark(sid, "spec", "done", f"{rep.summary()}; {note}", rules=len(spec.rules), open_questions=len(spec.open_questions), inventory_hash=inv_hash)
        if self.cfg.pipeline.auto_approve:
            self.approve(sid, "spec", "auto_approve")
        elif self.approvals().get(sid, {}).get("spec"):
            self.mark(sid, "approve_spec", "done", "approved earlier")
        else:
            self.mark(sid, "approve_spec", "waiting", f"review workspace/specs/{sid}.coverage.md, then run: sp2react approve {sid}")

    def stage_spec(self, sids: list[str]) -> None:
        self._parallel("spec", sids, self._spec_one)

    def _parallel(self, stage: str, sids: list[str], fn) -> None:
        with cf.ThreadPoolExecutor(max_workers=max(1, self.cfg.pipeline.max_concurrency)) as pool:
            futs = {pool.submit(fn, sid): sid for sid in sids}
            for f, sid in futs.items():
                try:
                    f.result(timeout=self.cfg.pipeline.agent_timeout * (self.cfg.pipeline.agent_retries + 1))
                except StageBlocked as e:
                    self.progress(f"[{stage}] {sid}: blocked - {e}")
                except AgentFailed as e:
                    self.mark(sid, stage, "failed", f"agent output kept failing validation; see {e.transcript}", problems=e.problems[:20])
                except cf.TimeoutError:
                    self.mark(sid, stage, "failed", f"timed out after {self.cfg.pipeline.agent_timeout}s per attempt")
                except Exception as e:  # keep other screens going
                    log.exception("%s %s", stage, sid)
                    self.mark(sid, stage, "failed", f"{type(e).__name__}: {e}")

    def approved_sids(self) -> list[str]:
        return [sid for sid in self.state["screens"] if self.status(sid, "approve_spec") == "done" and (self.ws / "specs" / f"{sid}.json").exists()]

    def stage_convert(self, sids: list[str]) -> None:
        ready = [s for s in sids if self.status(s, "approve_spec") == "done"]
        for s in set(sids) - set(ready):
            self.progress(f"[convert] {s}: waiting for spec approval")
        if not ready:
            return
        all_specs = [self.load_spec(s) for s in self.approved_sids()]
        for s in ready:
            self.mark(s, "convert", "running", "scaffold")
        t0 = time.time()
        export_dir = self.stage_migrate(all_specs)
        if self.cfg.pipeline.data_source == "database":
            mf = Path(self.cfg.database.mapping)
            if not mf.exists() or self.status(None, "map_db") == "failed":
                for s in ready:
                    self.mark(s, "convert", "failed", "data_source=database needs a reviewed list->table mapping: run `sp2react map-db` first")
                return
        info = generate(self.out, all_specs, self.legacy, export_dir, self.cfg.pipeline.data_source,
                        Path(self.cfg.database.mapping) if self.cfg.pipeline.data_source == "database" else None)
        self.progress(f"[convert] scaffold written in {time.time() - t0:.1f}s ({info['files']} files)")
        routes = [{"screen": sp.screen.id, "kind": sp.screen.kind, "route": sp.screen.route, "list": sp.screen.list,
                   "legacy_urls": sp.screen.legacy_urls} for sp in all_specs]

        tasks = []
        for sid in ready:
            spec = self.load_spec(sid)
            inv = self.load_inventory(sid)
            if spec.screen.kind == "page":
                tasks.append((sid, "page", lambda spec=spec, inv=inv: run_page_agent(self.agent("page", "files"), self.legacy, inv, spec, routes, self.out)))
            for r in spec.rules:
                if r.kind == "custom":
                    tasks.append((sid, f"handler:{r.params['handler']}", lambda spec=spec, inv=inv, r=r: run_handler_agent(self.agent("handler", "files"), self.legacy, inv, spec, r, self.out)))
        failed: dict[str, str] = {}
        if tasks:
            self.progress(f"[convert] {len(tasks)} agent task(s) in parallel (max {self.cfg.pipeline.max_concurrency})")
            with cf.ThreadPoolExecutor(max_workers=max(1, self.cfg.pipeline.max_concurrency)) as pool:
                futs = [(sid, name, pool.submit(fn)) for sid, name, fn in tasks]
                for sid, name, fut in futs:
                    try:
                        res = fut.result(timeout=self.cfg.pipeline.agent_timeout * (self.cfg.pipeline.agent_retries + 1))
                        self._usage(sid, "convert", res)
                        self.progress(f"[convert] {sid} {name}: accepted on attempt {res.attempts}")
                    except AgentFailed as e:
                        failed[sid] = f"{name}: output kept failing validation ({e.problems[:3]}); transcript {e.transcript}"
                    except cf.TimeoutError:
                        failed[sid] = f"{name}: timed out"
                    except Exception as e:
                        failed[sid] = f"{name}: {type(e).__name__}: {e}"
        refresh_registries(self.out, all_specs)
        for sid in ready:
            if sid in failed:
                self.mark(sid, "convert", "failed", failed[sid])
            else:
                n = sum(1 for t in tasks if t[0] == sid)
                self.mark(sid, "convert", "done", f"scaffold + {n} agent file task(s)" if n else "scaffold only (form engine renders this screen from the spec)")

    def _review_one(self, sid: str) -> None:
        self.require(sid, "review")
        self.mark(sid, "review", "running")
        res = run_review_agent(self.agent("review", "json"), self.legacy, self.load_inventory(sid), self.load_spec(sid), self.out)
        self._usage(sid, "review", res)
        (self.ws / "reviews").mkdir(exist_ok=True)
        (self.ws / "reviews" / f"{sid}.json").write_text(json.dumps(res.output, indent=2), encoding="utf-8")
        blockers = [f for f in res.output["findings"] if f["severity"] in ("blocker", "major")]
        self.mark(sid, "review", "done", f"verdict {res.output['verdict']}, {len(blockers)} blocking finding(s), {len(res.output['findings'])} total",
                  verdict=res.output["verdict"], blocking=len(blockers))

    def stage_review(self, sids: list[str]) -> None:
        self._parallel("review", [s for s in sids if self.status(s, "convert") == "done"], self._review_one)

    # ------------------------------------------------------------ data
    @property
    def export_dir(self) -> Path:
        return self.ws / "data-export"

    def stage_migrate(self, specs: list[Spec]) -> Optional[Path]:
        """Export every item of every list the approved screens use (part of convert)."""
        if self.cfg.pipeline.data_source == "sharepoint":
            self.mark(None, "migrate", "skipped", "data_source=sharepoint: the app reads and writes the live lists")
            return None
        if self.cfg.pipeline.data_source == "database":
            self.mark(None, "migrate", "skipped", "data_source=database: the app uses your existing tables through the mapping")
            return None
        lists = sorted({name for sp in specs for name in sp.lists})
        if getattr(self, "_offline", False):
            if all((self.export_dir / f"{k}.jsonl").exists() for k in lists):
                self.mark(None, "migrate", "done", "offline: reusing the existing full export")
                return self.export_dir
            self.mark(None, "migrate", "warning", "offline and no full export: the app is seeded from the extraction sample only (not a migration)")
            return None
        from .migrate import export_lists
        self.mark(None, "migrate", "running", f"exporting {len(lists)} list(s)")
        summary = export_lists(self.sp, self.legacy.site, lists, self.export_dir, progress=self.progress)
        total = sum(v["items"] for v in summary.values())
        self.mark(None, "migrate", "done", f"{total} items and {sum(v['attachments'] for v in summary.values())} attachments from {len(lists)} lists", lists=summary)
        return self.export_dir

    def mapping_lists(self, specs: list[Spec]) -> dict:
        out: dict = {}
        for sp in specs:
            for name, l in sp.lists.items():
                cur = out.setdefault(name, {"title": l.title, "fields": []})
                known = {f["name"] for f in cur["fields"]}
                cur["fields"] += [f for f in l.fields if f["name"] not in known]
        return out

    def stage_map_db(self, specs: list[Spec]) -> bool:
        """data_source=database: map lists onto the existing tables (schema only) -> db-mapping.json + .md."""
        from .config import secret
        from .dbmap import draft, reflect, report, validate
        from .agents.tasks import run_dbmap_agent
        lists = self.mapping_lists(specs)
        self.mark(None, "map_db", "running", f"{len(lists)} list(s)")
        db = reflect(secret(self.cfg.database.url_env, "database URL"), self.cfg.database.schema_name)
        (self.ws / "db-schema.json").write_text(json.dumps(db, indent=1), encoding="utf-8")
        mapping_file = Path(self.cfg.database.mapping)
        if mapping_file.exists():                      # keep a mapping you already reviewed; only extend it
            mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
            missing = {k: v for k, v in lists.items() if k not in mapping.get("lists", {})}
            if missing:
                extra, _ = draft(missing, db)
                mapping.setdefault("lists", {}).update(extra["lists"])
            notes: list[str] = []
        else:
            mapping, notes = draft(lists, db)
        problems, warnings = validate(mapping, lists, db)
        agent_notes: list[str] = []
        if problems:
            mapping, agent_notes, res = run_dbmap_agent(self.agent("dbmap", "json"), lists, db, mapping, notes + problems)
            self._usage("database", "map_db", res)
            problems, warnings = validate(mapping, lists, db)
        mapping_file.write_text(json.dumps(mapping, indent=2), encoding="utf-8")
        md = report(mapping, lists, db, problems, warnings + agent_notes)
        (self.ws / "db-mapping.md").write_text(md, encoding="utf-8")
        ok = not problems
        self.mark(None, "map_db", "done" if ok else "failed",
                  f"{len(mapping.get('lists', {}))} list(s) mapped, {len(warnings)} warning(s); review {mapping_file.name} and db-mapping.md" if ok
                  else f"{len(problems)} problem(s); see db-mapping.md")
        return ok

    def stage_reconcile(self, specs: list[Spec]) -> dict:
        """Read everything back through the app's repository and compare with the SharePoint export."""
        from .migrate import read_through_app, reconcile, report_markdown
        if self.cfg.pipeline.data_source == "sharepoint":
            self.mark(None, "reconcile", "skipped", "data_source=sharepoint")
            return {"ok": True, "lists": {}, "skipped": True}
        if self.cfg.pipeline.data_source == "database" and not self.cfg.item_reads_allowed:
            self.mark(None, "reconcile", "skipped", "no list items are read in database mode; set security.sharepoint_item_reads: true to compare the lists with your tables")
            return {"ok": True, "lists": {}, "skipped": True}
        database = self.cfg.pipeline.data_source == "database"
        if database and not getattr(self, "_offline", False):
            from .migrate import export_lists        # read-only comparison copy of the lists, kept in the workspace
            export_lists(self.sp, self.legacy.site, sorted({n for sp in specs for n in sp.lists}), self.export_dir, progress=self.progress)
        if not (self.export_dir / "export.json").exists():
            self.mark(None, "reconcile", "warning", "no full export to reconcile against (seeded from the sample)")
            return {"ok": True, "lists": {}, "skipped": True}
        lists = {}
        for sp in specs:
            for name, l in sp.lists.items():
                lists.setdefault(name, {"fields": l.fields})
        app_items = read_through_app(self.out, self.ws / "reconcile.db", load=not database, env=self._app_env())
        rep = reconcile(self.export_dir, app_items, lists)
        meta = json.loads((self.export_dir / "export.json").read_text())
        (self.ws / "reconciliation.md").write_text(report_markdown(rep, meta), encoding="utf-8")
        (self.ws / "reconciliation.json").write_text(json.dumps(rep, indent=1, default=str), encoding="utf-8")
        n = sum(l["source_items"] for l in rep["lists"].values())
        bad = [k for k, l in rep["lists"].items() if not l["ok"]]
        self.mark(None, "reconcile", "done" if rep["ok"] else "failed",
                  f"{n} items in {len(rep['lists'])} lists match field by field" if rep["ok"] else f"mismatches in {', '.join(bad)}; see reconciliation.md")
        return rep

    def stage_test_and_fix(self, sids: list[str]) -> None:
        sids = [s for s in sids if self.status(s, "review") == "done"]
        if not sids:
            return
        handlers = {}
        for sid in sids:
            for r in self.load_spec(sid).rules:
                if r.kind == "custom":
                    handlers[r.params["handler"]] = sid
        max_iter = self.cfg.pipeline.max_fix_iterations
        specs_now = [self.load_spec(s) for s in self.approved_sids()]
        rec = self.stage_reconcile(specs_now)
        if not rec["ok"]:
            bad = {k for k, l in rec["lists"].items() if not l["ok"]}
            for sid in sids:
                if bad & set(self.load_spec(sid).lists):
                    self.mark(sid, "test", "failed", f"data reconciliation failed for {', '.join(sorted(bad))}; see reconciliation.md")
                    self.mark(sid, "fix", "failed", "data mismatches are fixed in the migration mapping or the source data, not by an agent")
            sids = [s for s in sids if not (bad & set(self.load_spec(s).lists))]
            if not sids:
                return
        for it in range(0, max_iter + 1):
            for sid in sids:
                self.mark(sid, "test", "running", f"iteration {it}")
            checks = run_all(self.out, self.cfg.pipeline.run_builds, self._app_env())
            (self.ws / "tests").mkdir(exist_ok=True)
            (self.ws / "tests" / f"iteration-{it}.md").write_text(
                "\n\n".join(f"## {c.name}: {'skipped' if c.skipped else 'ok' if c.ok else 'FAILED'}\n```\n{c.tail(20000)}\n```" for c in checks), encoding="utf-8")
            routed = failures_by_screen(checks, sids, handlers)
            reviews = {sid: json.loads((self.ws / "reviews" / f"{sid}.json").read_text()) for sid in sids if (self.ws / "reviews" / f"{sid}.json").exists()}
            blocking = {sid: [f for f in r["findings"] if f["severity"] in ("blocker", "major")] for sid, r in reviews.items()}
            summary = "; ".join(f"{c.name}: {'skipped' if c.skipped else 'ok' if c.ok else 'failed'}" for c in checks)
            todo = {sid for sid in sids if routed.get(sid) or blocking.get(sid)}
            infra = routed.get("")
            for sid in sids:
                st = "failed" if (sid in todo or infra) else "done"
                self.mark(sid, "test", st, summary, iteration=it)
            if not todo and not infra:
                for sid in sids:
                    self.mark(sid, "fix", "done" if it else "skipped", f"{it} fix iteration(s)")
                    self._screen_gate(sid)
                return
            if it == max_iter:
                break
            if infra and not todo:
                for sid in sids:
                    self.mark(sid, "fix", "failed", "failures are in shared scaffold code or the environment, not in agent-written files; see workspace/tests")
                return
            for sid in sorted(todo):
                self.mark(sid, "fix", "running", f"iteration {it + 1}")
                failures = routed.get(sid, "")
                if blocking.get(sid):
                    failures += "\n\n## Review findings to fix\n" + json.dumps(blocking[sid], indent=1)
                try:
                    res, new_spec = run_fix_agent(self.agent("fix", "files"), self.load_inventory(sid), self.load_spec(sid), failures, self.out, f"{sid}-iter{it + 1}")
                    self._usage(sid, "fix", res)
                    if new_spec is not None:
                        (self.ws / "specs" / f"{sid}.json").write_text(new_spec.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
                        js = new_spec.model_dump_json(indent=2, exclude_none=True)
                        (self.out / "backend" / "specs" / f"{sid}.json").write_text(js, encoding="utf-8")
                        (self.out / "frontend" / "src" / "specs" / f"{sid}.json").write_text(js, encoding="utf-8")
                    if blocking.get(sid):  # re-review after a fix for review findings
                        self._review_one(sid)
                except AgentFailed as e:
                    self.mark(sid, "fix", "failed", f"fix agent output kept failing validation; see {e.transcript}")
        for sid in sids:
            if self.status(sid, "test") != "done":
                self.mark(sid, "fix", "failed", f"still failing after {max_iter} iteration(s); see workspace/tests")

    def _app_env(self) -> dict:
        if self.cfg.pipeline.data_source != "database":
            return {}
        import os
        url = os.environ.get(self.cfg.database.url_env)
        return {"DATA_SOURCE": "database", "MAPPING_FILE": str(self.out / "backend" / "mapping.json"), **({"DB_URL": url} if url else {})}

    def _screen_gate(self, sid: str) -> None:
        if self.cfg.pipeline.auto_approve:
            self.approve(sid, "screen", "auto_approve")
        elif self.approvals().get(sid, {}).get("screen"):
            self.mark(sid, "approve", "done", "approved earlier")
        else:
            self.mark(sid, "approve", "waiting", f"run the app, compare with the original, then: sp2react approve {sid} --screen")

    # ----------------------------------------------------------------- run
    def run(self, pages: Optional[list[str]] = None, offline: bool = False, until: str = "approve") -> dict:
        self._offline = offline
        stop = STAGES.index(until)
        self.stage_inputs(offline)
        if stop >= 1:
            self.stage_extract(pages, offline)
        sids: list[str] = []
        if stop >= 2:
            sids = [s["id"] for s in self.stage_inventory(pages)]
        if stop >= 3:
            self.stage_spec(sids)
        if stop >= 5 and self.cfg.pipeline.data_source == "database" and self.approved_sids():
            try:
                self.stage_map_db([self.load_spec(s) for s in self.approved_sids()])
            except Exception as e:      # missing DB_URL, driver, network...
                self.mark(None, "map_db", "failed", f"{type(e).__name__}: {e}")
        if stop >= 5:
            self.stage_convert(sids)
        if stop >= 6:
            self.stage_review(sids)
        if stop >= 7:
            self.stage_test_and_fix(sids)
        write_report(self)
        return self.state


def coverage_markdown(spec: Spec, inv: dict, rep) -> str:
    beh = {b["id"]: b for b in inv["behaviors"]}
    lines = [f"# {spec.screen.title} ({spec.screen.id})", "", rep.summary(), "",
             "| Legacy behaviour | Kind | Code | Carried by |", "|---|---|---|---|"]
    for m in rep.matrix:
        b = beh[m["behavior"]]
        code = (b.get("code") or "").replace("|", "\\|")[:80]
        lines.append(f"| `{m['behavior']}` | {m['kind']} | `{code}` | {', '.join(m['covered_by']) or '**missing**'} |")
    lines += ["", "## Rules", ""]
    for r in spec.rules:
        lines.append(f"- **{r.id}** {r.kind} {r.field or ''} {('modes=' + ','.join(r.modes)) if r.modes else ''} "
                     f"{('when=' + json.dumps(r.when)) if r.when else ''} {('“' + r.message + '”') if r.message else ''}")
    if spec.not_carried:
        lines += ["", "## Not carried (with reasons)", ""] + [f"- {', '.join(n.covers)}: {n.reason}" for n in spec.not_carried]
    if spec.open_questions:
        lines += ["", "## Open questions", ""] + [f"- {q}" for q in spec.open_questions]
    if rep.problems:
        lines += ["", "## Problems", ""] + [f"- {p}" for p in rep.problems]
    return "\n".join(lines) + "\n"


def write_report(p: Pipeline) -> Path:
    lines = ["# sp2react run report", "", f"Updated {_now()}", "", "| Screen | " + " | ".join(STAGES[2:]) + " |", "|---|" + "---|" * len(STAGES[2:])]
    for sid, st in p.state["screens"].items():
        lines.append(f"| {sid} | " + " | ".join((st.get(s) or {}).get("status", "") for s in STAGES[2:]) + " |")
    for k in ("migrate", "reconcile"):
        g = p.state["global"].get(k)
        if g:
            lines.append(f"\n**Data {k}:** {g['status']} - {g.get('detail', '')}")
    lines += ["", "## Details", ""]
    for sid, st in p.state["screens"].items():
        lines.append(f"### {sid}")
        for s in STAGES[2:]:
            if st.get(s):
                lines.append(f"- **{s}**: {st[s]['status']} - {st[s].get('detail', '')}")
        u = p.state["usage"].get(sid)
        if u:
            tot_in = sum(v["input_tokens"] for v in u.values())
            tot_out = sum(v["output_tokens"] for v in u.values())
            lines.append(f"- model usage: {tot_in:,} input / {tot_out:,} output tokens across " + ", ".join(f"{k} ({v['attempts']} call(s))" for k, v in u.items()))
        lines.append("")
    f = p.ws / "report.md"
    f.write_text("\n".join(lines), encoding="utf-8")
    return f
