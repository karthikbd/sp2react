# Security and network behaviour

This page answers the questions a security or architecture review usually asks. The policy itself is in [SECURITY.md](https://github.com/karthikbd/sp2react/blob/main/SECURITY.md).

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

## Windows sign-in (NTLM) and its cryptography

`auth: ntlm` (for on-premises SharePoint with Windows authentication) uses NTLMv2, which
the protocol defines with MD4 (the password hash) and HMAC-MD5. Both are weak by today's standards; they
are used only because the SharePoint server requires this protocol, and only toward the configured
SharePoint host. Python's `hashlib` no longer offers MD4 with OpenSSL 3, so `ntlm.py` contains a small
MD4 implementation checked against the RFC 1320 test vectors; HMAC-MD5 comes from `hmac` and `hashlib`.

Because of that, sp2react has **no default sign-in**: `sharepoint.auth` must be set, so NTLM is always a
choice made for compatibility. And it refuses NTLM on an `http://` site URL (the exchange would cross the
network without TLS) unless `sharepoint.allow_ntlm_over_http: true` is set for a test system; the
generated app does the same (`SP_AUTH` is required, `SP_ALLOW_NTLM_OVER_HTTP=1` for test systems).

What this means and how to reduce the risk:

- Anyone who records an NTLM exchange can try to guess the password offline, and an attacker in the
  middle could relay it. Use an `https://` site URL with certificate verification (the default):
  the exchange is then inside TLS, and sp2react adds **channel binding** (the server's certificate hash).
  Channel binding stops a relay only if the server checks it: turn on **Extended Protection for
  Authentication** (IIS, `tokenChecking="Require"`) on the SharePoint web applications. Keep `verify_ssl` on,
  or point it at your CA bundle.
- Use a service account with read access to the site only, and a long random password.
- If the farm supports another sign-in, prefer it: `auth: cookie` (a session from a signed-in browser) or
  `auth: bearer` (an Entra ID / SharePoint Online token). They use no MD4 or MD5 in sp2react.

Everything else that needs cryptography uses Python's `ssl` (TLS 1.2 or later, OpenSSL) and `hashlib`
(SHA-256 for checksums and fingerprints; SHA-1 only to shorten identifiers, never for security).

## Writes

- **SharePoint:** none. sp2react never writes to SharePoint.
- **Database:** sp2react never writes to your database. The generated app does, when users save forms. Its generated tests also write test items, so run them against a test database.
- **Local disk:** only the workspace, the output folder and `db-mapping.json`. Paths that come from the site (page and asset URLs, attachment names) are checked: one that would land outside these folders (`../`, an absolute or drive path, a symlink) is refused and listed as an extraction error.

## Running the generated app's tests

The `test` stage runs the generated back end's tests, and `reconcile` runs its loader. Both import the
custom handlers agents wrote (`backend/app/custom/*.py`), so that code runs **in a sandbox**
(`pipeline.sandbox`):

| Mode | Where | What the generated code can do |
|---|---|---|
| `container` | a throwaway Docker or Podman container | nothing outside it: no network (with `data_source: database`, only the database host), a read-only file system except the folder the step writes (`backend/`, or the reconcile database), no Linux capabilities, a non-root user, process and memory limits, and only the variables the app needs. The guard below runs inside it too |
| `guard` | this machine | writes only in that folder and a private temporary folder; no new processes; network only to loopback and the database host; no native code through `ctypes`. sp2react's credentials are removed from its environment. A guard, not isolation: Python's audit hooks are not a security boundary |
| `auto` (default) | `container` when Docker or Podman answers, otherwise `guard` | |
| `off` | plain processes | everything your user can do, minus sp2react's credentials. Not recommended |

The check report (`sp2react-work/tests/iteration-N.md`) names the mode each run used. The container image is
built once from sp2react's `container/Dockerfile` (Python, the app's `requirements.txt`, pytest and the
database driver); set `pipeline.sandbox_image` to use one from your registry instead. If `auto` cannot build
it (no access to the registry), the run falls back to `guard` and says so.

The front-end checks (`npm install`, `tsc`, `vite build`, the rule vectors) stay on the host: they run
template code only, and agent-written TypeScript is type-checked and bundled, never executed.

Page text can try to steer an agent (prompt injection). The sandbox contains what generated code can do
while sp2react checks it; whether the code is right is decided at the approval gates, where a person
reviews each screen. Review custom handlers (`custom/*.ts`, `custom/*.py`) like any other code change.
See the [security assurance case](../development/security-assurance.md) for every threat considered.

## The generated app

- Fails closed: without `AUTH_MODE`, the API expects an identity header from an authenticating gateway (`AUTH_MODE=header`) and answers 401 without it. `AUTH_MODE=dev` (set in `.env.example` for local work) only accepts requests from the same machine. For production use `header` behind your gateway, or Entra ID token validation in `app/auth.py`.
- Every API route, including `/api/screens` and `/api/specs`, needs a signed-in user. Deleting an item and adding or removing attachments follow the same lock and role rules as editing it.
- Serves only files inside the built front end (`FRONTEND_DIST`); other paths get the app shell.
- Legacy Content Editor / Script Editor markup is rebuilt from an allow-list of tags and attributes (`runtime/sanitize.ts`), so scripts, event handlers, `svg` and `javascript:` links cannot reach the page.
- Files written by agents must be plain relative paths inside the screen's own folder (or the handler's two files); anything else is refused before it is written.
- Regenerating never overwrites a template file someone changed (such as `app/auth.py`): the new version is written next to it as `<file>.sp2react-new`.
- Enforces every rule on the server (`app/rules.py`), so a direct API call cannot bypass validation, read-only fields, locks or role checks.
- Uses parameterised SQL through SQLAlchemy; `$filter` input is parsed into expressions, never concatenated into SQL.
- Restricts CORS to `CORS_ORIGINS`.

## Supply chain

- Published to PyPI from GitHub Actions with **Trusted Publishing** (OIDC, no stored tokens), from the public repository `karthikbd/sp2react`.
- Every GitHub Action is pinned to a commit SHA, and every CI tool set is installed from hash-locked requirement files (`ci/requirements-*.txt`, `pip install --require-hashes`).
- Each release carries PyPI provenance attestations; its wheel, sdist and CycloneDX SBOM are signed with Sigstore and attached to the GitHub release, and `verify-release.yml` checks the signatures and that PyPI serves the same files.
- `pip-audit` (every CI tool set, including versions pinned for other Python versions, and the generated app's back end) and `npm audit` (the generated app's front end) run on every push and weekly. On pull requests, dependency review blocks new dependencies with known vulnerabilities, and every commit must be signed off (DCO).
- Releases are reproducible: the same commit builds to the same bytes, checked in CI.
- `ruff` with the Bandit security rules and `mypy --strict` run on every change.
- ClusterFuzzLite fuzzes the parsers that read untrusted input: the config YAML, agent JSON (spec validation), ASPX pages and legacy JavaScript, NTLM challenges and the generated API's `$filter` parser.
- End-to-end CI runs `data_source: database` against real MySQL 8.4 and SQL Server 2022 containers.
- OpenSSF Scorecard runs weekly and on every push to `main`.
- CodeQL code scanning (Python and TypeScript) on every push to `main`, and weekly.
- Dependabot watches GitHub Actions, the Python dependencies and the generated app's npm and pip templates.
- The generated app's front-end template reports 0 known vulnerabilities (`npm audit`).
- No runtime dependencies: HTTP, NTLM (NTLMv2, with channel binding on HTTPS), YAML and validation are implemented on the standard library. Optional: `SQLAlchemy` with `pyodbc` or `PyMySQL` for `data_source: database`.
- Licence: MIT.
