"""sp2react command line."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from . import __version__
from .config import TEMPLATE, ConfigError, load_config

DEFAULT_CONFIG = "sp2react.yaml"


def _pipeline(args):
    from .pipeline import Pipeline
    cfg = load_config(args.config)
    if getattr(args, "auto_approve", False):
        cfg.pipeline.auto_approve = True
    if getattr(args, "no_builds", False):
        cfg.pipeline.run_builds = False
    return Pipeline(cfg, progress=lambda m: print(m, flush=True))


def cmd_init(args) -> int:
    p = Path(args.config)
    if p.exists() and not args.force:
        print(f"{p} already exists (use --force to overwrite)")
        return 1
    p.write_text(TEMPLATE, encoding="utf-8")
    print(f"Wrote {p}. Fill in sharepoint.site_url and the llm section, set the secret environment variables, then run: sp2react doctor")
    return 0


def cmd_doctor(args) -> int:
    from .llm.providers import make_llm
    from .sharepoint.client import SharePointClient
    cfg = load_config(args.config)
    ok = True
    try:
        web = SharePointClient(cfg.sharepoint).web()
        print(f"SharePoint: OK - '{web.get('Title')}' ({web.get('ServerRelativeUrl')})")
    except Exception as e:
        ok = False
        print(f"SharePoint: FAILED - {e}")
    try:
        llm = make_llm(cfg.llm)
        try:
            models = llm.models()
            claude = [m for m in models if "claude" in (m or "").lower()]
            print(f"Model provider ({cfg.llm.provider}): OK - {len(models)} model(s){'; Claude: ' + ', '.join(claude) if claude else ''}")
            if cfg.llm.model and models and cfg.llm.model not in models:
                print(f"  warning: configured model '{cfg.llm.model}' is not in the provider's list")
        except Exception as e:
            print(f"Model provider ({cfg.llm.provider}): could not list models ({e}); trying a one-line completion")
        c = llm.complete("Reply with the single word: ready", [{"role": "user", "content": "ping"}], max_tokens=10)
        print(f"Model call: OK - {cfg.llm.model or cfg.llm.deployment} replied '{c.text.strip()[:40]}'")
    except Exception as e:
        ok = False
        print(f"Model provider: FAILED - {e}")
    return 0 if ok else 2


def cmd_run(args) -> int:
    p = _pipeline(args)
    p.run(pages=args.page or None, offline=args.offline, until=args.until)
    print(f"\nReport: {p.ws / 'report.md'}\nApp:    {p.out}")
    return 0


def cmd_stage(args) -> int:
    from .pipeline import write_report
    p = _pipeline(args)
    scrs = p.screens(args.page or None)
    sids = [s["id"] for s in scrs] if not args.screen else args.screen
    if args.stage == "extract":
        p.stage_inputs(False)
        p.stage_extract(args.page or None, False)
    elif args.stage == "inventory":
        p.stage_inventory(args.page or None)
    elif args.stage == "spec":
        p.stage_spec(sids)
    elif args.stage == "convert":
        p.stage_convert(sids)
    elif args.stage == "review":
        p.stage_review(sids)
    elif args.stage == "test":
        p.stage_test_and_fix(sids)
    elif args.stage == "migrate":
        specs = [p.load_spec(s) for s in p.approved_sids()]
        p._offline = False
        from .scaffold.generate import generate
        generate(p.out, specs, p.legacy, p.stage_migrate(specs))
    elif args.stage == "map-db":
        specs = [p.load_spec(s) for s in p.approved_sids()] or [p.load_spec(sc["id"]) for sc in p.screens() if (p.ws / "specs" / f"{sc['id']}.json").exists()]
        ok = p.stage_map_db(specs)
        print(f"{'Mapping ready' if ok else 'Mapping needs attention'}: {p.cfg.database.mapping} and {p.ws / 'db-mapping.md'}")
    elif args.stage == "reconcile":
        rep = p.stage_reconcile([p.load_spec(s) for s in p.approved_sids()])
        print(f"{'All lists match' if rep['ok'] else 'Mismatches found'} - see {p.ws / 'reconciliation.md'}")
    write_report(p)
    return 0


def cmd_approve(args) -> int:
    from .pipeline import write_report
    p = _pipeline(args)
    gate = "screen" if args.screen_gate else "spec"
    if gate == "spec" and p.status(args.screen_id, "spec") != "done":
        print(f"The spec for {args.screen_id} is not done yet")
        return 1
    if gate == "screen" and p.status(args.screen_id, "test") != "done":
        print(f"{args.screen_id} has not passed testing yet")
        return 1
    p.approve(args.screen_id, gate, args.by or "")
    write_report(p)
    return 0


def cmd_status(args) -> int:
    from .pipeline import STAGES
    p = _pipeline(args)
    if args.json:
        print(json.dumps(p.state, indent=2))
        return 0
    for k in ("inputs", "extract"):
        s = p.state["global"].get(k)
        if s:
            print(f"{k:<10} {s['status']:<9} {s.get('detail', '')}")
    for sid, st in p.state["screens"].items():
        print(f"\n{sid}")
        for s in STAGES[2:]:
            if st.get(s):
                print(f"  {s:<13} {st[s]['status']:<9} {st[s].get('detail', '')[:110]}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="sp2react", description="Convert classic SharePoint ASPX/jQuery forms and pages to React + FastAPI with AI agents.")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-c", "--config", default=DEFAULT_CONFIG)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="write a starter sp2react.yaml")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("doctor", help="check the SharePoint connection and the model provider (lists Bridger's Claude models)")
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("run", help="run every stage up to the next approval gate")
    s.add_argument("--page", action="append", help="site-relative or server-relative page URL (repeatable); default: all list forms + SitePages")
    s.add_argument("--offline", action="store_true", help="reuse the extraction already in the workspace")
    s.add_argument("--until", default="approve", choices=["inputs", "extract", "inventory", "spec", "approve_spec", "convert", "review", "test", "fix", "approve"])
    s.add_argument("--auto-approve", action="store_true", help="skip the human gates (CI / demos)")
    s.add_argument("--no-builds", action="store_true", help="skip npm install/build")
    s.set_defaults(fn=cmd_run)

    for name in ("extract", "inventory", "spec", "map-db", "convert", "review", "test", "migrate", "reconcile"):
        s = sub.add_parser(name, help=f"run only the {name} stage")
        s.add_argument("--page", action="append")
        s.add_argument("--screen", action="append")
        s.add_argument("--no-builds", action="store_true")
        s.set_defaults(fn=cmd_stage, stage=name)

    s = sub.add_parser("approve", help="approve a screen's spec (default) or the finished screen (--screen)")
    s.add_argument("screen_id")
    s.add_argument("--screen", dest="screen_gate", action="store_true")
    s.add_argument("--by", help="name to record with the approval")
    s.set_defaults(fn=cmd_approve)

    s = sub.add_parser("status", help="show every screen's stage status")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_status)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    try:
        return args.fn(args)
    except ConfigError as e:
        print(f"Configuration problem: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
