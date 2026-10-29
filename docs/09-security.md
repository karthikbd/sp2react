# 9. Security and network behaviour

This page answers the questions a security or architecture review usually asks. The policy itself is in [SECURITY.md](../SECURITY.md).

## Where sp2react connects

sp2react opens HTTP connections to exactly two hosts, both named in `sp2react.yaml`:

| Host | Why | Direction |
|---|---|---|
| `sharepoint.site_url` | read the site being converted | **GET only.** The client refuses any other method before it is sent |
| `llm.base_url` (Bridger or your provider) | agent calls | POST prompts, receive replies |

Every request, **including each redirect hop**, is checked against these hosts (plus any in `security.allowed_hosts`) before it is sent; anything else raises `NetworkPolicyError`. There is no telemetry, no update check and no other HTTP client in the package. A test in the suite fails if any other module opens network connections.

The database connection (`map-db`, `reconcile`) uses your database driver, not HTTP.

## What is read from SharePoint

In the default `data_source: database`:

| Read | Not read |
|---|---|
| site title and settings | list **items** |
| list and field schemas, views, form pages | **attachments** |
| `.aspx` page source and web part definitions | site **users** |
| Script Editor / Content Editor content | group **members** (group names only) |
| custom JavaScript and CSS files linked by pages | rendered page HTML |
| navigation | |

The SharePoint client raises `ItemReadBlocked` if anything tries to read the "not read" column. Item reads happen only if you choose `data_source: sqlite` or set `security.sharepoint_item_reads: true` to run `reconcile`.

## What is sent to the model

| Sent | Not sent (database mode) |
|---|---|
| page source, scripts and CSS from the site | list items, attachments, people |
| list schemas (field names, types, choices) | database rows |
| the inventory and the draft spec | credentials |
| generated code under review or repair, with compiler and test output | |
| for `map-db`: table and column **names and types** | |

All prompts and replies are saved in `sp2react-work/agents/` so you can audit exactly what was sent.

If your scripts contain hard-coded secrets or personal data, they will be in the extracted source and in prompts. Check `sp2react-work/legacy/` after `extract`.

## What is read from the database

`map-db` reads the schema through SQLAlchemy's inspector, which queries the database's system catalog: table and column names, types, primary keys, foreign keys, nullability. It runs no query against the tables' data. `reconcile` (opt-in) reads every mapped row, through the generated app's data layer, to compare.

The account in `SP2REACT_DB_URL` needs read access to the schema for `map-db`. The generated app's account needs read and write access to the mapped tables.

## Secrets

All credentials come from environment variables named in the config: SharePoint username and password, cookie or token, the model token, the database URL. They are never written to the workspace, the generated app, the report or agent transcripts.

## Writes

- **SharePoint:** none. sp2react never writes to SharePoint.
- **Database:** sp2react never writes to your database. The generated app does, when users save forms. Its generated tests also write test items, so run them against a test database.
- **Local disk:** only the workspace, the output folder and `db-mapping.json`.

## The generated app

- Ships with `AUTH_MODE=dev` for local work. Production must use `AUTH_MODE=header` behind an authenticating gateway, or Entra ID token validation in `app/auth.py`.
- Enforces every rule on the server (`app/rules.py`), so a direct API call cannot bypass validation, read-only fields, locks or role checks.
- Uses parameterised SQL through SQLAlchemy; `$filter` input is parsed into expressions, never concatenated into SQL.
- Restricts CORS to `CORS_ORIGINS`.

## Supply chain

- Published to PyPI from GitHub Actions with **Trusted Publishing** (OIDC, no stored tokens), from the public repository `karthikbd/sp2react`.
- Every GitHub Action is pinned to a commit SHA.
- OpenSSF Scorecard runs weekly and on every push to `main`.
- CodeQL code scanning (Python and TypeScript) on every push to `main`, and weekly.
- Dependabot watches GitHub Actions, the Python dependencies and the generated app's npm and pip templates.
- The generated app's front-end template reports 0 known vulnerabilities (`npm audit`).
- Runtime dependencies: `pydantic`, `PyYAML`, `requests`; optional `SQLAlchemy`, `pyodbc` or `PyMySQL`, `requests-ntlm`.
- Licence: MIT.
