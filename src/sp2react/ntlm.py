"""NTLMv2 authentication (MS-NLMP) for Windows-authenticated SharePoint, using only the standard library.

Only what HTTP authentication needs: the NEGOTIATE message, reading the server's CHALLENGE, and an
AUTHENTICATE message with an NTLMv2 response. No signing or sealing is negotiated. On HTTPS the response
carries a channel binding (MsvAvChannelBindings, "tls-server-end-point"), so it also works where IIS has
Extended Protection switched on. MD4 is implemented here because OpenSSL 3 no longer offers it.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import struct
import time
from typing import Optional, Tuple

# negotiate flags
NEGOTIATE_UNICODE = 0x00000001
REQUEST_TARGET = 0x00000004
NEGOTIATE_NTLM = 0x00000200
NEGOTIATE_ALWAYS_SIGN = 0x00008000
NEGOTIATE_EXTENDED_SESSIONSECURITY = 0x00080000
NEGOTIATE_TARGET_INFO = 0x00800000
NEGOTIATE_VERSION = 0x02000000
NEGOTIATE_128 = 0x20000000
NEGOTIATE_56 = 0x80000000
FLAGS = (NEGOTIATE_UNICODE | REQUEST_TARGET | NEGOTIATE_NTLM | NEGOTIATE_ALWAYS_SIGN | NEGOTIATE_EXTENDED_SESSIONSECURITY
         | NEGOTIATE_TARGET_INFO | NEGOTIATE_128 | NEGOTIATE_56)

AV_EOL, AV_TIMESTAMP, AV_TARGET_NAME, AV_CHANNEL_BINDINGS = 0, 7, 9, 10
SIGNATURE = b"NTLMSSP\x00"


class NTLMError(RuntimeError):
    pass


# ------------------------------------------------------------------ MD4 (RFC 1320)
def md4(data: bytes) -> bytes:
    def f(x, y, z):
        return (x & y) | (~x & z)

    def g(x, y, z):
        return (x & y) | (x & z) | (y & z)

    def h(x, y, z):
        return x ^ y ^ z

    def rotl(v, s):
        v &= 0xFFFFFFFF
        return ((v << s) | (v >> (32 - s))) & 0xFFFFFFFF

    msg = bytearray(data)
    bit_len = (8 * len(data)) & 0xFFFFFFFFFFFFFFFF
    msg.append(0x80)
    while len(msg) % 64 != 56:
        msg.append(0)
    msg += struct.pack("<Q", bit_len)
    a, b, c, d = 0x67452301, 0xEFCDAB89, 0x98BADCFE, 0x10325476
    for off in range(0, len(msg), 64):
        x = struct.unpack("<16I", bytes(msg[off:off + 64]))
        aa, bb, cc, dd = a, b, c, d
        for i in (0, 4, 8, 12):
            a = rotl(a + f(b, c, d) + x[i], 3)
            d = rotl(d + f(a, b, c) + x[i + 1], 7)
            c = rotl(c + f(d, a, b) + x[i + 2], 11)
            b = rotl(b + f(c, d, a) + x[i + 3], 19)
        for i in (0, 1, 2, 3):
            a = rotl(a + g(b, c, d) + x[i] + 0x5A827999, 3)
            d = rotl(d + g(a, b, c) + x[i + 4] + 0x5A827999, 5)
            c = rotl(c + g(d, a, b) + x[i + 8] + 0x5A827999, 9)
            b = rotl(b + g(c, d, a) + x[i + 12] + 0x5A827999, 13)
        for i in (0, 2, 1, 3):
            a = rotl(a + h(b, c, d) + x[i] + 0x6ED9EBA1, 3)
            d = rotl(d + h(a, b, c) + x[i + 8] + 0x6ED9EBA1, 9)
            c = rotl(c + h(d, a, b) + x[i + 4] + 0x6ED9EBA1, 11)
            b = rotl(b + h(c, d, a) + x[i + 12] + 0x6ED9EBA1, 15)
        a, b, c, d = (a + aa) & 0xFFFFFFFF, (b + bb) & 0xFFFFFFFF, (c + cc) & 0xFFFFFFFF, (d + dd) & 0xFFFFFFFF
    return struct.pack("<4I", a, b, c, d)


# ------------------------------------------------------------------ keys and responses
def nt_owf_v1(password: str) -> bytes:
    return md4(password.encode("utf-16-le"))


def nt_owf_v2(user: str, domain: str, password: str) -> bytes:
    return hmac.new(nt_owf_v1(password), (user.upper() + domain).encode("utf-16-le"), hashlib.md5).digest()


def ntlmv2_response(key: bytes, server_challenge: bytes, client_challenge: bytes, timestamp: bytes, av_pairs: bytes) -> Tuple[bytes, bytes]:
    """-> (NTChallengeResponse, LmChallengeResponse) per MS-NLMP 3.3.2."""
    temp = b"\x01\x01" + b"\x00" * 6 + timestamp + client_challenge + b"\x00" * 4 + av_pairs + b"\x00" * 4
    proof = hmac.new(key, server_challenge + temp, hashlib.md5).digest()
    lm = hmac.new(key, server_challenge + client_challenge, hashlib.md5).digest() + client_challenge
    return proof + temp, lm


def filetime(now: Optional[float] = None) -> bytes:
    t = time.time() if now is None else now
    return struct.pack("<Q", int((t + 11644473600) * 10_000_000))


# ------------------------------------------------------------------ AV pairs
def parse_av_pairs(data: bytes) -> list:
    out, i = [], 0
    while i + 4 <= len(data):
        av_id, length = struct.unpack("<HH", data[i:i + 4])
        if av_id == AV_EOL:
            break
        out.append((av_id, data[i + 4:i + 4 + length]))
        i += 4 + length
    return out


def build_av_pairs(pairs: list) -> bytes:
    return b"".join(struct.pack("<HH", k, len(v)) + v for k, v in pairs) + struct.pack("<HH", AV_EOL, 0)


def channel_binding_hash(server_cert_der: bytes) -> bytes:
    """MD5 of gss_channel_bindings_struct carrying 'tls-server-end-point:' + certificate hash (RFC 5929)."""
    algo = hashlib.sha256
    if any(oid in server_cert_der for oid in (b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0c", b"\x2a\x86\x48\xce\x3d\x04\x03\x03")):
        algo = hashlib.sha384           # sha384WithRSAEncryption / ecdsa-with-SHA384
    elif any(oid in server_cert_der for oid in (b"\x2a\x86\x48\x86\xf7\x0d\x01\x01\x0d", b"\x2a\x86\x48\xce\x3d\x04\x03\x04")):
        algo = hashlib.sha512
    app = b"tls-server-end-point:" + algo(server_cert_der).digest()
    struct_ = struct.pack("<IIIII", 0, 0, 0, 0, len(app)) + app
    return hashlib.md5(struct_).digest()


# ------------------------------------------------------------------ messages
def negotiate_message() -> bytes:
    return SIGNATURE + struct.pack("<II", 1, FLAGS) + b"\x00" * 16


def parse_challenge(msg: bytes) -> Tuple[int, bytes, bytes]:
    """-> (flags, server challenge, target info)."""
    if len(msg) < 32 or msg[:8] != SIGNATURE or struct.unpack("<I", msg[8:12])[0] != 2:
        raise NTLMError("the server did not send an NTLM CHALLENGE message")
    flags = struct.unpack("<I", msg[20:24])[0]
    challenge = msg[24:32]
    info = b""
    if len(msg) >= 48:
        ln, _, off = struct.unpack("<HHI", msg[40:48])
        info = msg[off:off + ln]
    return flags, challenge, info


def authenticate_message(challenge_msg: bytes, user: str, password: str, domain: str = "", workstation: str = "",
                         server_cert_der: Optional[bytes] = None, target_name: Optional[str] = None,
                         client_challenge: Optional[bytes] = None, now: Optional[float] = None) -> bytes:
    flags, server_challenge, info = parse_challenge(challenge_msg)
    pairs = parse_av_pairs(info)
    timestamp = next((v for k, v in pairs if k == AV_TIMESTAMP), None) or filetime(now)
    extra = []
    if server_cert_der:
        extra.append((AV_CHANNEL_BINDINGS, channel_binding_hash(server_cert_der)))
    if target_name:
        extra.append((AV_TARGET_NAME, target_name.encode("utf-16-le")))
    av = build_av_pairs([p for p in pairs if p[0] not in (AV_CHANNEL_BINDINGS, AV_TARGET_NAME)] + extra)
    cc = client_challenge or os.urandom(8)
    nt, lm = ntlmv2_response(nt_owf_v2(user, domain, password), server_challenge, cc, timestamp, av)
    if any(k == AV_TIMESTAMP for k, _ in pairs):
        lm = b"\x00" * 24           # MS-NLMP: with a server timestamp, the LM response is zeros
    use_flags = FLAGS & (flags | NEGOTIATE_UNICODE)
    dom, usr, ws = (s.encode("utf-16-le") for s in (domain, user, workstation))
    payload = [lm, nt, dom, usr, ws, b""]
    offset = 64
    fields = b""
    for blob in payload:
        fields += struct.pack("<HHI", len(blob), len(blob), offset)
        offset += len(blob)
    return SIGNATURE + struct.pack("<I", 3) + fields + struct.pack("<I", use_flags) + b"".join(payload)


def split_user(login: str) -> Tuple[str, str]:
    """'DOMAIN\\user' or 'user@domain' -> (user, domain)."""
    if "\\" in login:
        domain, user = login.split("\\", 1)
        return user, domain
    return login, ""


def header_token(header_value: str) -> Optional[bytes]:
    """The NTLM blob from a WWW-Authenticate header ('NTLM <base64>', also inside a comma-separated list)."""
    for part in header_value.split(","):
        p = part.strip()
        for scheme in ("NTLM ", "Negotiate "):
            if p.startswith(scheme):
                try:
                    return base64.b64decode(p[len(scheme):].strip())
                except ValueError:
                    return None
    return None
