"""Shared fixtures: the mock site, one converted app, and running the generated TypeScript runtime with Node."""
import importlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from mock_sharepoint import MockSharePoint
from scripted_agents import scripted
from sp2react.config import Config, LLMConfig, PipelineConfig, SharePointConfig
from sp2react.pipeline import Pipeline

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "sp2react" / "scaffold" / "templates"


def make(tmp, url, **pipeline):
    pipeline.setdefault("data_source", "sqlite")
    pipeline.setdefault("sandbox", "guard")         # the container path has its own CI job (sandbox-container)
    return Config(sharepoint=SharePointConfig(site_url=url, auth="cookie"), llm=LLMConfig(provider="scripted"),
                  pipeline=PipelineConfig(workspace=str(tmp / "ws"), output=str(tmp / "app"), **pipeline))


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    """One converted app (sqlite data source) shared by the API tests."""
    tmp = tmp_path_factory.mktemp("hardening")
    os.environ["SP_COOKIE"] = "FedAuth=test-cookie"
    with MockSharePoint() as m:
        Pipeline(make(tmp, m.site_url, auto_approve=True, run_builds=False), llm=scripted(), progress=lambda s: None).run()
    dist = tmp / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app shell</html>")
    (dist / "favicon.ico").write_text("icon")
    (tmp / "secret.env").write_text("DB_PASSWORD=hunter2")
    return tmp


def load_app(built: Path, monkeypatch, **env):
    be = built / "app" / "backend"
    monkeypatch.setenv("DB_PATH", str(built / f"app-{os.getpid()}.db"))
    monkeypatch.setenv("FRONTEND_DIST", str(built / "dist"))
    monkeypatch.delenv("AUTH_MODE", raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.syspath_prepend(str(be))
    for m in [k for k in sys.modules if k == "app" or k.startswith("app.")]:
        del sys.modules[m]
    return importlib.import_module("app.main").create_app()


def _node_version() -> tuple[int, ...]:
    if not shutil.which("node"):
        return (0,)
    out = subprocess.run(["node", "--version"], capture_output=True, text=True).stdout.strip().lstrip("v")
    return tuple(int(x) for x in out.split(".")[:2] if x.isdigit())


NODE_OK = _node_version() >= (22, 6)


def run_ts(tmp_path: Path, script: str) -> dict:
    rt = tmp_path / "rt"
    shutil.copytree(TEMPLATES / "frontend" / "src" / "runtime", rt)
    (tmp_path / "run.mts").write_text(script)
    r = subprocess.run(["node", "--experimental-strip-types", "--no-warnings", str(tmp_path / "run.mts")],
                       capture_output=True, text=True, cwd=tmp_path, timeout=60)
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout)


