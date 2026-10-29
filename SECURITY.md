# Security Policy

## Supported Versions

| Version | Supported |
|---------|-----------|
| 0.1.x   | ✅ Active  |

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via GitHub's [Security Advisories](https://github.com/karthikbd/sp2react/security/advisories/new).

You can expect:
- **Acknowledgement** within 48 hours
- **Status update** within 7 days
- **Fix or mitigation** as soon as reasonably possible, coordinated with a disclosure date

## Network access

`sp2react` has no telemetry, no update check and no third-party calls. It opens HTTP connections to exactly two kinds of host, both named in your `sp2react.yaml`:

| Host | Why | What is sent / received |
|------|-----|-------------------------|
| `sharepoint.site_url` | Read the site being converted | GET requests only (the client refuses any other verb). Page source, web part definitions, custom scripts/CSS, list schemas, views, group names, navigation |
| `llm.base_url` (Bridger, or the provider you chose) | AI agent calls | Page source, scripts, list schemas and the draft spec or code under review |

Every request, and every redirect hop, is checked against that allowlist before it is sent (`sp2react/net.py`); anything else raises `NetworkPolicyError`. Extra hosts must be added explicitly under `security.allowed_hosts`.

## Business data

With `pipeline.data_source: database` (the default):
- list items, attachments, site users and rendered pages are **never read** from SharePoint; the client raises `ItemReadBlocked` if anything tries
- group membership is not read (group names only)
- no business data is sent to the model; prompts contain code and schema only
- `sp2react map-db` reads your database **schema** (tables, columns, types, keys) over the database driver; it does not read rows

Item reads over HTTP happen only when you set `data_source: sqlite` (sp2react migrates the data itself) or explicitly enable `security.sharepoint_item_reads: true` to reconcile the lists with your tables.

## Secrets

Credentials are read from environment variables named in the config (`SP_USERNAME`/`SP_PASSWORD`, `SP_COOKIE`, `SP_TOKEN`, the model token, the database URL). They are never written to the workspace, the generated app or agent transcripts.

## Generated application

The generated FastAPI app ships with `AUTH_MODE=dev` (an `X-User` header) for local testing only. Before deployment, use `AUTH_MODE=header` behind an authenticating gateway, or replace `app/auth.py` with Entra ID token validation.
