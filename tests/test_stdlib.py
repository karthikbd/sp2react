"""The standard-library replacements for requests, requests-ntlm, pydantic and PyYAML."""
from __future__ import annotations

import base64
import hashlib
import hmac
import struct
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Literal, Optional, Union

import pytest

from sp2react import ntlm, transport
from sp2react.model import BaseModel, Field, ValidationError, field_validator
from sp2react.yamlish import YAMLError, safe_load


# ------------------------------------------------------------------ NTLM (MS-NLMP 4.2.4 test vectors)
def test_md4_rfc1320_vectors():
    assert ntlm.md4(b"").hex() == "31d6cfe0d16ae931b73c59d7e0c089c0"
    assert ntlm.md4(b"abc").hex() == "a448017aaf21d8525fc10ae87aa6729d"
    assert ntlm.md4(b"message digest").hex() == "d9130a8164549fe818874806e1c7014b"
    assert ntlm.md4(b"1234567890" * 8).hex() == "e33b4ddc9c38f2199c3e7b164fcc0536"


def test_ntlmv2_matches_the_specification_example():
    assert ntlm.nt_owf_v1("Password").hex() == "a4f49c406510bdcab6824ee7c30fd852"
    key = ntlm.nt_owf_v2("User", "Domain", "Password")
    assert key.hex() == "0c868a403bfd7a93a3001ef22ef02e3f"
    av = ntlm.build_av_pairs([(2, "Domain".encode("utf-16-le")), (1, "Server".encode("utf-16-le"))])
    nt, lm = ntlm.ntlmv2_response(key, bytes.fromhex("0123456789abcdef"), b"\xaa" * 8, b"\x00" * 8, av)
    assert nt[:16].hex() == "68cd0ab851e51c96aabc927bebef6a1c"
    assert lm.hex() == "86c35097ac9cec102554764a57cccc19aaaaaaaaaaaaaaaa"


class NtlmServer(BaseHTTPRequestHandler):
    """Windows authentication as IIS does it: the handshake must stay on one connection, then the
    NTLMv2 proof is checked against the password."""
    protocol_version = "HTTP/1.1"
    challenges: Dict[int, bytes] = {}
    password = "S3cret!"
    seen: List[str] = []

    def log_message(self, *a):
        pass

    def _send(self, status, headers=(), body=b""):
        self.send_response(status)
        for k, v in headers:
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        auth = self.headers.get("Authorization", "")
        conn = id(self.connection)
        if not auth:
            self.seen.append("anonymous")
            return self._send(401, [("WWW-Authenticate", "Negotiate"), ("WWW-Authenticate", "NTLM")])
        msg = base64.b64decode(auth.split(" ", 1)[1])
        kind = struct.unpack("<I", msg[8:12])[0]
        if kind == 1:
            self.seen.append("negotiate")
            challenge = b"\x11\x22\x33\x44\x55\x66\x77\x88"
            self.challenges[conn] = challenge
            info = ntlm.build_av_pairs([(2, "CORP".encode("utf-16-le")), (1, "SP01".encode("utf-16-le"))])
            body = ntlm.SIGNATURE + struct.pack("<I", 2) + struct.pack("<HHI", 0, 0, 56) + struct.pack("<I", ntlm.FLAGS) + challenge \
                + b"\x00" * 8 + struct.pack("<HHI", len(info), len(info), 56) + b"\x00" * 8 + info
            return self._send(401, [("WWW-Authenticate", "NTLM " + base64.b64encode(body).decode())])
        self.seen.append("authenticate")
        challenge = self.challenges.get(conn)
        if challenge is None:                       # the handshake moved to another connection
            return self._send(401, [("WWW-Authenticate", "NTLM")])
        fields = [struct.unpack("<HHI", msg[12 + 8 * i:20 + 8 * i]) for i in range(5)]
        nt = msg[fields[1][2]:fields[1][2] + fields[1][0]]
        domain = msg[fields[2][2]:fields[2][2] + fields[2][0]].decode("utf-16-le")
        user = msg[fields[3][2]:fields[3][2] + fields[3][0]].decode("utf-16-le")
        key = ntlm.nt_owf_v2(user, domain, self.password)
        ok = hmac.compare_digest(hmac.new(key, challenge + nt[16:], hashlib.md5).digest(), nt[:16])
        self._send(200 if ok else 401, [("Content-Type", "application/json")], b'{"user": "%s"}' % user.encode() if ok else b"")


def test_ntlm_handshake_against_a_windows_style_server():
    NtlmServer.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), NtlmServer)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/sites/SEA/_api/web"
        s = transport.Session()
        s.auth = transport.NtlmAuth("CORP\\alice", "S3cret!")
        r = s.get(url, timeout=10)
        assert r.status_code == 200 and r.json() == {"user": "alice"}
        assert NtlmServer.seen == ["anonymous", "negotiate", "authenticate"]
        bad = transport.Session()
        bad.auth = transport.NtlmAuth("CORP\\alice", "wrong")
        assert bad.get(url, timeout=10).status_code == 401
    finally:
        srv.shutdown()


def test_channel_binding_value():
    cert = b"0\x82fake-der-certificate"
    app = b"tls-server-end-point:" + hashlib.sha256(cert).digest()
    assert ntlm.channel_binding_hash(cert) == hashlib.md5(b"\x00" * 16 + struct.pack("<I", len(app)) + app).digest()
    msg = ntlm.authenticate_message(
        ntlm.SIGNATURE + struct.pack("<I", 2) + struct.pack("<HHI", 0, 0, 48) + struct.pack("<I", ntlm.FLAGS) + b"\x01" * 8 + b"\x00" * 8
        + struct.pack("<HHI", 4, 4, 48) + b"\x00\x00\x00\x00", "u", "p", "D", server_cert_der=cert, target_name="HTTP/sp")
    nt_len, _, nt_off = struct.unpack("<HHI", msg[20:28])
    pairs = dict(ntlm.parse_av_pairs(msg[nt_off + 16 + 28:nt_off + nt_len]))
    assert pairs[ntlm.AV_CHANNEL_BINDINGS] == ntlm.channel_binding_hash(cert)
    assert pairs[ntlm.AV_TARGET_NAME] == "HTTP/sp".encode("utf-16-le")


# ------------------------------------------------------------------ transport
def test_headers_are_case_insensitive_and_repeated_ones_merge():
    h = transport._merged([("WWW-Authenticate", "Negotiate"), ("www-authenticate", "NTLM"), ("Content-Type", "x")])
    assert h["www-authenticate"] == "Negotiate, NTLM" and h.get("CONTENT-TYPE") == "x" and "content-type" in h


def test_credentials_do_not_follow_a_redirect_to_another_host():
    seen = {}

    class Hop(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            seen[self.path] = self.headers.get("Authorization")
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", f"http://localhost:{self.server.server_address[1]}/next")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Hop)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        s = transport.Session()
        s.headers["Authorization"] = "Bearer secret"
        r = s.get(f"http://127.0.0.1:{srv.server_address[1]}/start", timeout=10)
        assert r.text == "ok" and seen["/start"] == "Bearer secret" and seen["/next"] is None and len(r.history) == 1
    finally:
        srv.shutdown()


def test_no_proxy_rules(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://user:pw@proxy.corp:3128")
    monkeypatch.setenv("NO_PROXY", "localhost,.corp.local")
    assert transport._proxy_for("https", "sp.corp.local") is None
    host, port, auth = transport._proxy_for("https", "api.anthropic.com")
    assert (host, port) == ("proxy.corp", 3128) and auth == "Basic " + base64.b64encode(b"user:pw").decode()


# ------------------------------------------------------------------ model
class Inner(BaseModel):
    kind: Literal["a", "b"]
    n: int = 0


class Outer(BaseModel):
    name: str
    tags: List[str] = Field(default_factory=list)
    inner: List[Inner] = Field(default_factory=list)
    extra: Dict[str, int] = Field(default_factory=dict)
    verify: Union[bool, str] = True
    note: Optional[str] = None
    list: Optional[str] = None                 # a field named like a builtin, as Rule.list is

    @field_validator("name")
    @classmethod
    def _strip(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must not be blank")
        return v.strip()


def test_model_validates_and_reports_locations():
    o = Outer.model_validate({"name": " x ", "inner": [{"kind": "a", "n": "3"}], "verify": "/etc/ca.pem", "ignored": 1})
    assert o.name == "x" and o.inner[0].n == 3 and o.verify == "/etc/ca.pem" and o.tags == []
    assert Outer.model_validate({"name": "y"}).tags is not Outer.model_validate({"name": "z"}).tags     # fresh defaults
    with pytest.raises(ValidationError) as e:
        Outer.model_validate({"tags": "x", "inner": [{"kind": "c"}, {"n": True}], "extra": {"k": "v"}})
    locs = {".".join(str(x) for x in err["loc"]): err["msg"] for err in e.value.errors()}
    assert locs["name"] == "Field required" and "list" in locs["tags"] and "'a' or 'b'" in locs["inner.0.kind"]
    assert "inner.1.kind" in locs and "integer" in locs["inner.1.n"] and "integer" in locs["extra.k"]
    with pytest.raises(ValidationError, match="must not be blank"):
        Outer.model_validate({"name": "  "})


def test_model_dump_round_trip():
    o = Outer.model_validate({"name": "x", "inner": [{"kind": "b"}], "note": None})
    assert o.model_dump(exclude_none=True) == {"name": "x", "tags": [], "inner": [{"kind": "b", "n": 0}], "extra": {}, "verify": True}
    assert Outer.model_validate_json(o.model_dump_json(indent=2)) == o
    assert list(o.model_dump()) == ["name", "tags", "inner", "extra", "verify", "note", "list"]      # field order kept


# ------------------------------------------------------------------ YAML
def test_yaml_reads_config_files():
    text = """
# comment
sharepoint:
  site_url: https://sp.corp.local/sites/SEA   # trailing comment
  verify_ssl: "C:\\\\certs\\\\corp.pem"
  extra_headers: {X-Env: uat, X-Team: 'sanctions #1'}
llm:
  provider: bridger
  temperature: 0.0
  max_tokens: 16000
  json_mode: yes
security:
  allowed_hosts:
    - bridger.corp.local
    - "*.corp.local"
  sharepoint_item_reads: ~
notes: |
  line one
  line two
folded: >-
  a
  b
empty:
list_inline: [1, two, 3.5, null, true]
"""
    d = safe_load(text)
    assert d["sharepoint"] == {"site_url": "https://sp.corp.local/sites/SEA", "verify_ssl": "C:\\certs\\corp.pem",
                               "extra_headers": {"X-Env": "uat", "X-Team": "sanctions #1"}}
    assert d["llm"] == {"provider": "bridger", "temperature": 0.0, "max_tokens": 16000, "json_mode": True}
    assert d["security"] == {"allowed_hosts": ["bridger.corp.local", "*.corp.local"], "sharepoint_item_reads": None}
    assert d["notes"] == "line one\nline two\n" and d["folded"] == "a b" and d["empty"] is None
    assert d["list_inline"] == [1, "two", 3.5, None, True]


def test_yaml_lists_of_mappings_and_nesting():
    assert safe_load("- a: 1\n  b: [x]\n- - 1\n  - 2\n-\n  c: d\n") == [{"a": 1, "b": ["x"]}, [1, 2], {"c": "d"}]
    assert safe_load("k:\n- 1\n- 2\nz: 0\n") == {"k": [1, 2], "z": 0}


@pytest.mark.parametrize("bad", ["a: \"\\U00110000\"\n", "a: 1\na: 2\n", "a: &x 1\nb: *x\n", "a:\n\tb: 1\n", "a: \"open\n", "- a\nb: 1\n", "a: 1\n---\nb: 2\n",
                                 "a: [1, 2\n", "a: {b\n"])
def test_yaml_refuses_what_it_does_not_support(bad):
    with pytest.raises(YAMLError):
        safe_load(bad)
