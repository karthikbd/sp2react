"""Who is calling. SharePoint groups become the user's roles, so spec conditions like
{"role": "Compliance Reviewers"} keep working unchanged.

AUTH_MODE=header  (default) trust an identity header set by your gateway (e.g. X-MS-CLIENT-PRINCIPAL-NAME from
                  Azure App Service authentication); never expose the API directly in this mode.
AUTH_MODE=dev     the X-User header or DEV_USER picks a seeded user. Local testing only: it must be set
                  explicitly, and requests from other machines are refused.
Replace current_user() with Entra ID token validation (fastapi-azure-auth / msal) for production.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

LOCAL_CLIENTS = {"127.0.0.1", "::1", "localhost", "testclient"}


def auth_mode() -> str:
    return os.environ.get("AUTH_MODE", "header").strip().lower()


def identity_header() -> str:
    return os.environ.get("IDENTITY_HEADER", "X-MS-CLIENT-PRINCIPAL-NAME")


def current_user(request: Request) -> dict:
    repo = request.app.state.repo
    mode = auth_mode()
    if mode == "dev":
        client = request.client.host if request.client else ""
        if client not in LOCAL_CLIENTS:
            raise HTTPException(403, "AUTH_MODE=dev only accepts requests from this machine.")
        login = request.headers.get("X-User") or os.environ.get("DEV_USER", "")
        u = repo.user_by_login(login) if login else (repo.users[0] if getattr(repo, "users", None) else None)
    elif mode == "header":
        login = request.headers.get(identity_header())
        if not login:
            raise HTTPException(401, "Not signed in")
        u = repo.user_by_login(login)
    else:
        raise HTTPException(500, f"Unknown AUTH_MODE {mode}")
    if not u:
        raise HTTPException(403, "Your account does not have access to this site.")
    return {"id": u["id"], "login": u["login"], "title": u["title"], "email": u.get("email"), "groups": u.get("groups", [])}
