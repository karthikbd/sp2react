"""Stage 8 (test against the original): build and test the generated app. Plain processes, no model."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Check:
    name: str
    ok: bool
    output: str
    skipped: bool = False

    def tail(self, n: int = 6000) -> str:
        return self.output[-n:]


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env={**os.environ, **(env or {})})
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired as e:
        return 124, f"timed out after {timeout}s: {' '.join(cmd)}\n{(e.stdout or '')}"
    except FileNotFoundError as e:
        return 127, str(e)


def backend_tests(out: Path, timeout: int = 900, env: dict | None = None) -> Check:
    be = out / "backend"
    db = be / "data" / "test.db"
    if db.exists():
        db.unlink()
    code, txt = _run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], be, timeout,
                     {"PYTHONPATH": str(be), "DB_PATH": str(db), **(env or {})})
    return Check("backend tests (generated API tests + rule vectors)", code == 0, txt)


def frontend_install(out: Path, timeout: int = 1200) -> Check:
    fe = out / "frontend"
    if (fe / "node_modules" / ".bin" / "tsc").exists():
        return Check("npm install", True, "node_modules present", skipped=True)
    npm = shutil.which("npm")
    if not npm:
        return Check("npm install", False, "npm not found on PATH; install Node.js 20+ or set pipeline.run_builds: false", skipped=True)
    code, txt = _run([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], fe, timeout)
    return Check("npm install", code == 0, txt)


def frontend_build(out: Path, timeout: int = 900) -> Check:
    fe = out / "frontend"
    npm = shutil.which("npm")
    if not npm or not (fe / "node_modules").exists():
        return Check("frontend build (tsc + vite)", False, "dependencies not installed", skipped=True)
    code, txt = _run([npm, "run", "build", "--silent"], fe, timeout)
    return Check("frontend build (tsc + vite)", code == 0, txt)


def frontend_rule_vectors(out: Path, timeout: int = 120) -> Check:
    node = shutil.which("node")
    fe = out / "frontend"
    if not node:
        return Check("rule vectors (TypeScript engine)", False, "node not found", skipped=True)
    code, txt = _run([node, "scripts/check-rules.ts"], fe, timeout)
    if code != 0 and ("Unknown file extension" in txt or "ERR_UNKNOWN_FILE_EXTENSION" in txt):
        code, txt = _run([node, "--experimental-strip-types", "scripts/check-rules.ts"], fe, timeout)
        if code != 0 and "bad option" in txt:
            return Check("rule vectors (TypeScript engine)", False, "Node.js >= 22.6 is needed to run the TypeScript vectors directly", skipped=True)
    return Check("rule vectors (TypeScript engine)", code == 0, txt)


def run_all(out: Path, run_builds: bool = True, env: dict | None = None) -> list[Check]:
    checks = [backend_tests(out, env=env)]
    if run_builds:
        inst = frontend_install(out)
        checks.append(inst)
        if inst.ok:
            checks.append(frontend_build(out))
        checks.append(frontend_rule_vectors(out))
    return checks


def failures_by_screen(checks: list[Check], screen_ids: list[str], handlers: dict[str, str]) -> dict[str, str]:
    """Route failure output to the screen whose files are named in it; '' key = infrastructure."""
    out: dict[str, list[str]] = {}
    for c in checks:
        if c.ok or c.skipped:
            continue
        hit = False
        for sid in screen_ids:
            if re.search(rf"screens/{re.escape(sid)}/", c.output) or re.search(rf"test_{re.escape(sid.lower().replace('-', '_'))}", c.output):
                out.setdefault(sid, []).append(f"## {c.name}\n{c.tail()}")
                hit = True
        for handler, sid in handlers.items():
            if re.search(rf"custom/{re.escape(handler)}\.", c.output):
                out.setdefault(sid, []).append(f"## {c.name}\n{c.tail()}")
                hit = True
        if not hit:
            out.setdefault("", []).append(f"## {c.name}\n{c.tail()}")
    return {k: "\n\n".join(v) for k, v in out.items()}
