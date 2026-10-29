"""Who is calling. SharePoint groups become the user's roles, so spec conditions like
{"role": "Compliance Reviewers"} keep working unchanged.

AUTH_MODE=dev     (default) X-User header or DEV_USER env picks a seeded user - local testing only.
AUTH_MODE=header  trust an identity header set by your gateway (e.g. X-MS-CLIENT-PRINCIPAL-NAME from
                  Azure App Service authentication); never expose the API directly in this mode.
Replace current_user() with Entra ID token validation (fastapi-azure-auth / msal) for production.
"""
from __future__ import annotations

import os

from fastapi import HTTPException, Request

AUTH_MODE = os.environ.get("AUTH_MODE", "dev")
IDENTITY_HEADER = os.environ.get("IDENTITY_HEADER", "X-MS-CLIENT-PRINCIPAL-NAME")


def current_user(request: Request) -> dict:
    repo = request.app.state.repo
    if AUTH_MODE == "dev":
        login = request.headers.get("X-User") or request.query_params.get("as") or os.environ.get("DEV_USER", "")
        u = repo.user_by_login(login) if login else (repo.users[0] if getattr(repo, "users", None) else None)
    elif AUTH_MODE == "header":
        login = request.headers.get(IDENTITY_HEADER)
        if not login:
            raise HTTPException(401, "Not signed in")
        u = repo.user_by_login(login)
    else:
        raise HTTPException(500, f"Unknown AUTH_MODE {AUTH_MODE}")
    if not u:
        raise HTTPException(403, "Your account does not have access to this site.")
    return {"id": u["id"], "login": u["login"], "title": u["title"], "email": u.get("email"), "groups": u.get("groups", [])}
