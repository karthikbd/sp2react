"""Regression tests for the issues found by the threat model (docs/development/security-assurance.md).

Each test failed on 0.1.3: names and URLs that come from the site (page source, server answers) could write
files outside the workspace or the export folder.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from sp2react.config import SharePointConfig
from sp2react.migrate import _attachment_path, export_lists
from sp2react.model import ValidationError
from sp2react.sharepoint.client import SharePointClient, SharePointError
from sp2react.sharepoint.extract import Extractor, inside
from sp2react.spec.model import Screen

SITE = "https://sp.example.com/sites/SEA"


class StubClient(SharePointClient):
    """A client that answers from a dict instead of the network; records what was asked for."""

    def __init__(self, files: dict[str, str] | None = None) -> None:
        super().__init__(SharePointConfig(site_url=SITE, auth="none"))
        self.files = files or {}
        self.asked: list[str] = []

    def file_text(self, server_relative_url: str) -> str:
        self.asked.append(server_relative_url)
        return self.files.get(server_relative_url, "/* asset */")


@pytest.mark.parametrize("rel", ["../x.js", "SiteAssets/../../x.js", "a/../../../etc/passwd", "/etc/passwd",
                                 "C:/Windows/x.js", "SiteAssets/./x.js", "..", "", "a\\..\\..\\x"])
def test_inside_refuses_paths_that_leave_the_folder(tmp_path, rel):
    with pytest.raises(SharePointError):
        inside(tmp_path, rel)


def test_inside_accepts_ordinary_site_paths(tmp_path):
    assert inside(tmp_path, "SiteAssets/js/app.js") == (tmp_path / "SiteAssets" / "js" / "app.js").resolve()
    assert inside(tmp_path, "Lists/Vendor Requests/NewForm.aspx").name == "NewForm.aspx"


def test_assets_with_dot_dot_urls_are_not_written_outside_the_workspace(tmp_path):
    ws = tmp_path / "ws"
    page = ws / "legacy" / "pages" / "SitePages" / "Home.aspx"
    page.parent.mkdir(parents=True)
    page.write_text('<html><script src="/sites/SEA/SiteAssets/../../../../../escape.js"></script>'
                    '<script src="/sites/SEA/SiteAssets/ok.js"></script></html>', encoding="utf-8")
    sp = StubClient()
    ex = Extractor(sp, ws, progress=lambda s: None)
    ex.assets(["SitePages/Home.aspx"])
    assert not list(tmp_path.rglob("escape.js"))
    assert (ws / "legacy" / "files" / "SiteAssets" / "ok.js").exists()
    assert ex.manifest["files"] == ["SiteAssets/ok.js"]
    assert any("escape.js" in e["what"] for e in ex.manifest["errors"])
    assert all("escape" not in u for u in sp.asked)          # refused before it is even downloaded


def test_a_page_url_with_dot_dot_is_recorded_as_an_error(tmp_path):
    ex = Extractor(StubClient(), tmp_path / "ws", progress=lambda s: None)
    assert ex.page("/sites/SEA/SitePages/../../../../outside.aspx") is None
    assert not list(tmp_path.rglob("outside.aspx"))
    assert ex.manifest["errors"] and not ex.manifest["pages"]


@pytest.mark.parametrize("name", ["../../x.txt", "..", "", "a/b.txt", "a\\b.txt", "C:x.txt"])
def test_attachment_names_from_the_server_stay_in_the_export(tmp_path, name):
    with pytest.raises(ValueError):
        _attachment_path(tmp_path, "Vendors", 7, name)


def test_export_refuses_an_attachment_that_would_escape(tmp_path):
    class Lists(StubClient):
        def all_items(self, list_id, page_size=1000):
            yield {"ID": 1, "AttachmentFiles": {"results": [{"FileName": "../../../escape.txt", "ServerRelativeUrl": "/x"}]}}

        def file_bytes(self, server_relative_url):
            raise AssertionError("must not download an attachment it will not store")

    site = {"lists": [{"url": "/sites/SEA/Lists/Vendors", "id": "1"}]}
    with pytest.raises(ValueError, match="refused attachment"):
        export_lists(Lists(), site, ["Vendors"], tmp_path / "export")
    assert not list(tmp_path.rglob("escape.txt"))
    assert _attachment_path(tmp_path, "Vendors", 1, "quote v2.pdf") == tmp_path / "attachments" / "Vendors" / "1" / "quote v2.pdf"


@pytest.mark.parametrize("sid", ["../x", "a/b", ".hidden", "-x", "", "x" * 200])
def test_screen_ids_must_be_plain_names(sid):
    with pytest.raises(ValidationError):
        Screen.model_validate({"id": sid, "kind": "page", "title": "t", "route": "/t"})


def test_generated_screen_ids_are_accepted():
    for sid in ("Home", "VendorRequests-NewForm", "SitePages.Dashboard", "a1b2c3-4f5e6d"):
        assert Screen.model_validate({"id": sid, "kind": "page", "title": "t", "route": "/t"}).id == sid


def test_paths_are_resolved_inside(tmp_path: Path):
    (tmp_path / "files").mkdir()
    (tmp_path / "outside").mkdir()
    link = tmp_path / "files" / "link"
    link.symlink_to(tmp_path / "outside")
    with pytest.raises(SharePointError):
        inside(tmp_path / "files", "link/x.js")              # a symlink planted in the workspace can't redirect writes


def test_generated_app_processes_do_not_get_sp2react_credentials(monkeypatch):
    from sp2react import checks

    monkeypatch.setenv("SP_PASSWORD", "hunter2")
    monkeypatch.setenv("BRIDGER_TOKEN", "tok")
    monkeypatch.setenv("PATH_FOR_TEST", "kept")
    monkeypatch.setattr(checks, "HIDDEN_ENV", {"SP_PASSWORD", "BRIDGER_TOKEN"})
    env = checks.app_env({"DB_PATH": "x.db"})
    assert "SP_PASSWORD" not in env and "BRIDGER_TOKEN" not in env
    assert env["PATH_FOR_TEST"] == "kept" and env["DB_PATH"] == "x.db"
    code, out = checks._run([__import__("sys").executable, "-c", "import os; print(os.environ.get('SP_PASSWORD'))"], Path("."), 30)
    assert code == 0 and out.strip() == "None"


def test_the_pipeline_hides_the_configured_secret_variables(tmp_path):
    from conftest import make
    from scripted_agents import scripted
    from sp2react import checks
    from sp2react.pipeline import Pipeline

    cfg = make(tmp_path, SITE, run_builds=False)
    Pipeline(cfg, llm=scripted(), progress=lambda s: None)._app_env()
    assert {cfg.sharepoint.password_env, cfg.sharepoint.cookie_env, cfg.database.url_env} <= checks.HIDDEN_ENV


def test_text_functions_in_filters_need_a_quoted_value():
    """ClusterFuzzLite find: endswith(Title,0) raised TypeError (a 500) instead of a filter error."""
    import importlib.util

    import sp2react

    spec = importlib.util.spec_from_file_location(
        "generated_odata_t", Path(sp2react.__file__).parent / "scaffold" / "templates" / "backend" / "app" / "odata.py")
    odata = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(odata)
    items = [{"ID": 1, "Title": "50% off_sale"}]
    for bad in ("endswith(Title,0)", "startswith(Title,1.5)", "substringof(3,Title)", "[endswith(Ñ,00) "):
        with pytest.raises(odata.ODataError):
            odata.apply_query(items, bad)
    assert odata.apply_query(items, "startswith(Title,'50%')") == items
    assert odata.apply_query(items, "substringof('f_s',Title)") == items
