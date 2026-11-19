"""HTTP client on the standard library (http.client + ssl): the only code in sp2react that opens connections.

It offers the small part of the `requests` interface sp2react used: a Session with default headers, TLS
verification (on, off, or a CA bundle path), timeouts, JSON bodies, redirects that are each passed through
`send` (so the network policy sees every hop), proxies from HTTP(S)_PROXY / NO_PROXY, and NTLM sign-in on a
kept-alive connection. Connections are reused per thread and host.
"""
from __future__ import annotations

import base64
import http.client
import json as _json
import os
import socket
import ssl
import threading
from typing import Any, Dict, Iterable, Optional, Tuple, Union, cast
from urllib.parse import urlencode, urljoin, urlsplit

from . import ntlm

MAX_REDIRECTS = 10


class RequestException(OSError):
    pass


class ConnectionError(RequestException):
    pass


class Timeout(RequestException):
    pass


class HTTPError(RequestException):
    def __init__(self, message: str, response: "Response"):
        super().__init__(message)
        self.response = response


class Headers(dict[str, Any]):
    """Case-insensitive header mapping (keys kept as first written)."""

    def __init__(self, data: Optional[Iterable[Any]] = None):
        super().__init__()
        self._lower: Dict[str, str] = {}
        if data:
            self.update(data)

    def __setitem__(self, key: str, value: str) -> None:
        old = self._lower.get(key.lower())
        if old is not None and old != key:
            super().__delitem__(old)
        self._lower[key.lower()] = key
        super().__setitem__(key, value)

    def __getitem__(self, key: str) -> str:
        return cast("str", super().__getitem__(self._lower[key.lower()]))

    def __delitem__(self, key: str) -> None:
        real = self._lower.pop(key.lower())
        super().__delitem__(real)

    def __contains__(self, key: object) -> bool:
        return isinstance(key, str) and key.lower() in self._lower

    def get(self, key: str, default: Any = None) -> Any:
        real = self._lower.get(key.lower()) if isinstance(key, str) else None
        return super().__getitem__(real) if real is not None else default

    def update(self, other: Any = (), **kw: str) -> None:  # type: ignore[override]
        items = other.items() if hasattr(other, "items") else other
        for k, v in list(items) + list(kw.items()):
            self[k] = v

    def copy(self) -> "Headers":
        return Headers(self)


def _merged(pairs: Iterable[Tuple[str, str]]) -> Headers:
    """Repeated headers (two WWW-Authenticate lines) are joined with ', ', as requests does."""
    h = Headers()
    for k, v in pairs:
        h[k] = f"{h[k]}, {v}" if k in h else v
    return h


class Request:
    def __init__(self, method: str, url: str, headers: Headers, body: Optional[bytes], timeout: float):
        self.method, self.url, self.headers, self.body, self.timeout = method, url, headers, body, timeout


class Response:
    def __init__(self, status: int, reason: str, headers: Headers, content: bytes, url: str, request: Request):
        self.status_code, self.reason, self.headers, self.content, self.url, self.request = status, reason, headers, content, url, request
        self.encoding: Optional[str] = None
        ct = headers.get("Content-Type", "")
        for part in ct.split(";")[1:]:
            k, _, v = part.strip().partition("=")
            if k.lower() == "charset" and v:
                self.encoding = v.strip('"')
        self.history: list[Any] = []

    @property
    def ok(self) -> bool:
        return self.status_code < 400

    @property
    def text(self) -> str:
        enc = self.encoding or "utf-8"
        try:
            return self.content.decode(enc, errors="replace")
        except LookupError:
            return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return _json.loads(self.content.decode(self.encoding or "utf-8", errors="replace"))

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise HTTPError(f"HTTP {self.status_code} {self.reason} for {self.url}", self)


def _no_proxy(host: str) -> bool:
    entries = [e.strip().lower() for e in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(",") if e.strip()]
    h = host.lower()
    for e in entries:
        if e == "*":
            return True
        e = e.lstrip(".")
        if h == e or h.endswith("." + e):
            return True
    return False


def _proxy_for(scheme: str, host: str) -> Optional[Tuple[str, int, Optional[str]]]:
    if _no_proxy(host):
        return None
    raw = os.environ.get(f"{scheme.upper()}_PROXY") or os.environ.get(f"{scheme}_proxy")
    if not raw:
        return None
    p = urlsplit(raw if "://" in raw else "http://" + raw)
    auth = None
    if p.username:
        auth = "Basic " + base64.b64encode(f"{p.username}:{p.password or ''}".encode()).decode()
    return p.hostname or "", p.port or 8080, auth


class Session:
    """requests.Session-like. `verify`: True, False or a CA bundle path. `auth`: None or NtlmAuth."""

    def __init__(self) -> None:
        self.headers = Headers({"User-Agent": "sp2react", "Accept": "*/*"})
        self.verify: Union[bool, str] = True
        self.auth: Optional["NtlmAuth"] = None
        self._local = threading.local()

    # ------------------------------------------------------------- connections
    def _ssl_context(self) -> ssl.SSLContext:
        if self.verify is False:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        if isinstance(self.verify, str):
            return ssl.create_default_context(cafile=self.verify) if os.path.isfile(self.verify) else ssl.create_default_context(capath=self.verify)
        return ssl.create_default_context()

    def _connection(self, url: str, timeout: float) -> Tuple[http.client.HTTPConnection, str]:
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise RequestException(f"unsupported URL scheme in {url}")
        host, port = parts.hostname or "", parts.port or (443 if scheme == "https" else 80)
        pool: Dict[Tuple[Any, ...], http.client.HTTPConnection] = getattr(self._local, "pool", None) or {}
        self._local.pool = pool
        key = (scheme, host, port, str(self.verify))
        conn = pool.get(key)
        proxy = _proxy_for(scheme, host)
        if conn is None:
            if scheme == "https":
                if proxy:
                    conn = http.client.HTTPSConnection(proxy[0], proxy[1], timeout=timeout, context=self._ssl_context())
                    conn.set_tunnel(host, port, headers={"Proxy-Authorization": proxy[2]} if proxy[2] else None)
                else:
                    conn = http.client.HTTPSConnection(host, port, timeout=timeout, context=self._ssl_context())
            else:
                conn = http.client.HTTPConnection(proxy[0], proxy[1], timeout=timeout) if proxy else http.client.HTTPConnection(host, port, timeout=timeout)
            pool[key] = conn
        conn.timeout = timeout
        if conn.sock is not None:
            conn.sock.settimeout(timeout)
        target = url if (proxy and scheme == "http") else (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        return conn, target

    def _drop(self, url: str) -> None:
        parts = urlsplit(url)
        pool = getattr(self._local, "pool", {}) or {}
        key = (parts.scheme.lower(), parts.hostname or "", parts.port or (443 if parts.scheme == "https" else 80), str(self.verify))
        conn = pool.pop(key, None)
        if conn is not None:
            conn.close()

    def _once(self, req: Request) -> Response:
        """One round trip on the pooled connection; retried once on a stale kept-alive connection."""
        for attempt in (0, 1):
            conn, target = self._connection(req.url, req.timeout)
            try:
                conn.request(req.method, target, body=req.body, headers=dict(req.headers))
                r = conn.getresponse()
                content = r.read()
            except socket.timeout as e:
                self._drop(req.url)
                raise Timeout(f"{req.method} {req.url} timed out after {req.timeout}s") from e
            except (http.client.RemoteDisconnected, BrokenPipeError, ConnectionResetError, http.client.CannotSendRequest) as e:
                self._drop(req.url)
                if attempt == 0:
                    continue
                raise ConnectionError(f"{req.method} {req.url}: {e}") from e
            except ssl.SSLError as e:
                self._drop(req.url)
                raise ConnectionError(f"{req.method} {req.url}: TLS error: {e}") from e
            except (OSError, http.client.HTTPException) as e:
                self._drop(req.url)
                raise ConnectionError(f"{req.method} {req.url}: {e}") from e
            if r.getheader("Connection", "").lower() == "close" or r.version == 10:
                self._drop(req.url)
            return Response(r.status, r.reason, _merged(r.getheaders()), content, req.url, req)
        raise ConnectionError(f"{req.method} {req.url}: connection lost")  # pragma: no cover

    def peer_certificate(self, url: str) -> Optional[bytes]:
        parts = urlsplit(url)
        if parts.scheme.lower() != "https":
            return None
        pool = getattr(self._local, "pool", {}) or {}
        key = (parts.scheme.lower(), parts.hostname or "", parts.port or 443, str(self.verify))
        conn = pool.get(key)
        sock = getattr(conn, "sock", None)
        return sock.getpeercert(binary_form=True) if isinstance(sock, ssl.SSLSocket) else None

    # ------------------------------------------------------------------ API
    def send(self, request: Request) -> Response:
        """Sends one request (no redirects). The network policy wraps this method, so it sees every hop."""
        r = self._once(request)
        if r.status_code == 401 and self.auth is not None:
            r = self.auth.handle_401(self, request, r)
        return r

    def request(self, method: str, url: str, params: Optional[dict[str, Any]] = None, headers: Optional[dict[str, Any]] = None,
                json: Any = None, data: Union[bytes, str, None] = None, timeout: float = 60,
                allow_redirects: bool = True) -> Response:
        if params:
            q = urlencode({k: v for k, v in params.items() if v is not None}, doseq=True)
            url = url + ("&" if urlsplit(url).query else "?") + q
        h = self.headers.copy()
        h.update(headers or {})
        body: Optional[bytes] = None
        if json is not None:
            body = _json.dumps(json).encode("utf-8")
            if "Content-Type" not in h:
                h["Content-Type"] = "application/json"
        elif data is not None:
            body = data.encode("utf-8") if isinstance(data, str) else data
        if body is not None:
            h["Content-Length"] = str(len(body))
        history: list[Response] = []
        for _ in range(MAX_REDIRECTS + 1):
            r = self.send(Request(method.upper(), url, h, body, timeout))
            if not allow_redirects or r.status_code not in (301, 302, 303, 307, 308) or "Location" not in r.headers:
                r.history = history
                return r
            history.append(r)
            url = urljoin(url, r.headers["Location"])
            if r.status_code in (301, 302, 303) and method.upper() not in ("GET", "HEAD"):
                method, body = "GET", None
                for k in ("Content-Length", "Content-Type"):
                    if k in h:
                        del h[k]
            if urlsplit(url).hostname != urlsplit(r.url).hostname:
                for k in ("Authorization", "Cookie"):        # credentials never follow a redirect to another host
                    if k in h:
                        del h[k]
        raise RequestException(f"more than {MAX_REDIRECTS} redirects from {url}")

    def get(self, url: str, **kw: Any) -> Response:
        return self.request("GET", url, **kw)

    def post(self, url: str, **kw: Any) -> Response:
        return self.request("POST", url, **kw)

    def close(self) -> None:
        for conn in (getattr(self._local, "pool", {}) or {}).values():
            conn.close()
        self._local.pool = {}


class NtlmAuth:
    """Answers an NTLM (or Negotiate offering NTLM) 401 with the three-message handshake on one connection."""

    def __init__(self, login: str, password: str, allow_http: bool = False):
        self.user, self.domain = ntlm.split_user(login)
        self.password = password
        self.allow_http = allow_http          # NTLM (MD4/HMAC-MD5) answers only over TLS unless this is set

    def handle_401(self, session: Session, req: Request, first: Response) -> Response:
        if not self.allow_http and not req.url.lower().startswith("https://"):
            raise RequestException(f"refusing NTLM sign-in over plain HTTP ({req.url}): the exchange would be sent "
                                   "without TLS. Use https://, or allow it for a test system (allow_ntlm_over_http).")
        offered = ",".join(v for k, v in first.headers.items() if k.lower() == "www-authenticate")
        scheme = "NTLM" if "ntlm" in offered.lower() else ("Negotiate" if "negotiate" in offered.lower() else None)
        if scheme is None:
            return first
        h = req.headers.copy()
        h["Authorization"] = f"{scheme} " + base64.b64encode(ntlm.negotiate_message()).decode()
        h["Connection"] = "Keep-Alive"
        challenge = session._once(Request(req.method, req.url, h, req.body, req.timeout))
        token = ntlm.header_token(challenge.headers.get("WWW-Authenticate", ""))
        if challenge.status_code != 401 or not token:
            return challenge
        host = urlsplit(req.url).hostname or ""
        msg = ntlm.authenticate_message(token, self.user, self.password, self.domain, workstation="",
                                        server_cert_der=session.peer_certificate(req.url), target_name=f"HTTP/{host}")
        h["Authorization"] = f"{scheme} " + base64.b64encode(msg).decode()
        return session._once(Request(req.method, req.url, h, req.body, req.timeout))
