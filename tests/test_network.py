"""sp2react only talks to the hosts in your config, and never reads list data in database mode."""
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests

from mock_sharepoint import MockSharePoint
from sp2react.config import Config, LLMConfig, SharePointConfig
from sp2react.llm.providers import make_llm
from sp2react.net import NetworkPolicy, NetworkPolicyError, policy_for
from sp2react.sharepoint.client import ItemReadBlocked, SharePointClient


def test_policy_allows_only_configured_hosts():
    cfg = Config(sharepoint=SharePointConfig(site_url="https://sp.corp.local/sites/SEA", auth="none"),
                 llm=LLMConfig(provider="bridger", base_url="http://bridger.corp.local:4141", model="claude-sonnet-4"))
    pol = policy_for(cfg)
    assert pol.hosts == {"sp.corp.local", "bridger.corp.local"}
    s = pol.guard(requests.Session())
    with pytest.raises(NetworkPolicyError):
        s.get("https://pypi.org/simple/")
    llm = make_llm(cfg.llm, pol)
    with pytest.raises(NetworkPolicyError):
        llm.session.get("https://api.example.com/")


def test_redirect_to_another_host_is_blocked():
    class Redirect(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            self.send_response(302)
            self.send_header("Location", "http://localhost.evil.test/steal")
            self.end_headers()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Redirect)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = NetworkPolicy(["127.0.0.1"]).guard(requests.Session())
        with pytest.raises(NetworkPolicyError):
            s.get(f"http://127.0.0.1:{srv.server_address[1]}/")
    finally:
        srv.shutdown()


def test_item_reads_are_refused_when_disabled(monkeypatch):
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        sp = SharePointClient(SharePointConfig(site_url=m.site_url, auth="cookie"), item_reads=False)
        lst = sp.lists()[0]
        assert sp.fields(lst["Id"])                      # schema is fine
        for call in (lambda: sp.items(lst["Id"], 5), lambda: list(sp.all_items(lst["Id"])), lambda: sp.site_users(),
                     lambda: sp.rendered("SitePages/Dashboard.aspx"), lambda: sp.file_bytes("/x")):
            with pytest.raises(ItemReadBlocked):
                call()
        sp.site_groups()
        group_calls = [path for _, path in m.requests if "sitegroups" in path]
        assert group_calls and all("expand" not in p and "Users" not in p for p in group_calls)   # names only, no members


def test_no_other_network_code_in_the_package():
    """Only the two clients open connections; everything else is local."""
    import pathlib
    import re
    root = pathlib.Path(__file__).parents[1] / "src" / "sp2react"
    offenders = []
    for f in root.rglob("*.py"):
        rel = f.relative_to(root).as_posix()
        if rel.startswith("scaffold/templates/"):       # code of the generated app, not of the tool
            continue
        text = f.read_text()
        if re.search(r"\b(urllib\.request|http\.client|socket\.|httpx|aiohttp|requests\.(get|post|put|request))\b", text) and \
                rel not in ("sharepoint/client.py", "llm/providers.py", "net.py"):
            offenders.append(rel)
    assert offenders == []


def test_sharepoint_client_refuses_writes(monkeypatch):
    from sp2react.sharepoint.client import SharePointError
    monkeypatch.setenv("SP_COOKIE", "FedAuth=test-cookie")
    with MockSharePoint() as m:
        sp = SharePointClient(SharePointConfig(site_url=m.site_url, auth="cookie"))
        with pytest.raises(SharePointError, match="only reads"):
            sp.session.post(m.site_url + "/_api/web/lists", json={})
        assert all(verb == "GET" for verb, _ in m.requests)
