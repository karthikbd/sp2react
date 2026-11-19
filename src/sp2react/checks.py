"""Stage 8 (test against the original): build and test the generated app. Plain processes, no model."""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .sandbox import HIDDEN_ENV, Sandbox, app_env, run_process

__all__ = ["HIDDEN_ENV", "Check", "app_env", "backend_tests", "run_all"]


@dataclass
class Check:
    name: str
    ok: bool
    output: str
    skipped: bool = False

    def tail(self, n: int = 6000) -> str:
        return self.output[-n:]


def _run(cmd: list[str], cwd: Path, timeout: int, env: dict[str, Any] | None = None) -> tuple[int, str]:
    r = run_process(cmd, cwd, timeout, app_env(env))
    return r.code, r.output


def backend_tests(out: Path, timeout: int = 900, env: dict[str, Any] | None = None, sandbox: Sandbox | None = None) -> Check:
    """The generated back end's tests. They import agent-written handlers, so they run in the sandbox."""
    be = out / "backend"
    db = be / "data" / "test.db"
    if db.exists():
        db.unlink()
    box = sandbox or Sandbox()
    r = box.python(["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"], be,
                   {"PYTHONPATH": str(be), "DB_PATH": str(db), **(env or {})}, write=[be], read=[out], timeout=timeout)
    return Check(f"backend tests (generated API tests + rule vectors; {box.describe()})", r.code == 0, r.output)


NODE_MIN = "20.19 or 22.12"  # Vite 8 and @vitejs/plugin-react 6 (package.json engines)


def node_too_old(version: str) -> bool:
    """True when `node --version` output is below what the generated front end's build tools need."""
    m = re.match(r"v?(\d+)\.(\d+)", version.strip())
    if not m:
        return False
    major, minor = int(m.group(1)), int(m.group(2))
    return major < 20 or major == 21 or (major == 20 and minor < 19) or (major == 22 and minor < 12)


def frontend_install(out: Path, timeout: int = 1200) -> Check:
    fe = out / "frontend"
    node = shutil.which("node")
    if node:
        code, version = _run([node, "--version"], fe if fe.is_dir() else out, 60)
        if code == 0 and node_too_old(version):
            return Check("npm install", False, f"Node.js {version.strip()} is too old for the generated front end "
                         f"(Vite needs {NODE_MIN} or later); upgrade Node.js or set pipeline.run_builds: false", skipped=True)
    if (fe / "node_modules" / ".bin" / "tsc").exists():
        return Check("npm install", True, "node_modules present", skipped=True)
    npm = shutil.which("npm")
    if not npm:
        return Check("npm install", False, "npm not found on PATH; install Node.js 22.12+ (or 20.19+) or set pipeline.run_builds: false", skipped=True)
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


def run_all(out: Path, run_builds: bool = True, env: dict[str, Any] | None = None, sandbox: Sandbox | None = None) -> list[Check]:
    checks = [backend_tests(out, env=env, sandbox=sandbox)]
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
