"""Outbound network policy.

sp2react makes HTTP requests to exactly two kinds of host, both named in your config:
  * your SharePoint site (page source, scripts, list schemas; list items only when allowed),
  * your model endpoint (Bridger, or the provider you configured).
Every request (and every redirect hop) is checked against that allowlist before it is sent.
There is no telemetry, no update check and no third-party call.
"""
from __future__ import annotations

from typing import Iterable
from urllib.parse import urlsplit

import requests


class NetworkPolicyError(RuntimeError):
    pass


class NetworkPolicy:
    def __init__(self, hosts: Iterable[str]):
        self.hosts = {h.lower() for h in hosts if h}

    @staticmethod
    def host_of(url: str) -> str:
        return (urlsplit(url).hostname or "").lower()

    def check(self, url: str) -> None:
        host = self.host_of(url)
        if host not in self.hosts:
            raise NetworkPolicyError(
                f"Blocked request to '{host or url}': sp2react only contacts hosts named in your config "
                f"({', '.join(sorted(self.hosts)) or 'none'}). Add it to security.allowed_hosts if it is intended.")

    def guard(self, session: requests.Session) -> requests.Session:
        """Check every prepared request, including each redirect hop, before it leaves the machine."""
        send = session.send
        policy = self

        def guarded_send(request, **kwargs):
            policy.check(request.url)
            return send(request, **kwargs)

        session.send = guarded_send  # type: ignore[method-assign]
        return session


def policy_for(cfg) -> NetworkPolicy:
    """Allowed hosts = SharePoint site + model endpoint + anything listed in security.allowed_hosts."""
    hosts = [NetworkPolicy.host_of(cfg.sharepoint.site_url)]
    llm = cfg.llm
    if llm.base_url:
        hosts.append(NetworkPolicy.host_of(llm.base_url))
    elif llm.provider == "anthropic":
        hosts.append("api.anthropic.com")
    elif llm.provider == "openai":
        hosts.append("api.openai.com")
    hosts += list(cfg.security.allowed_hosts)
    return NetworkPolicy(hosts)
