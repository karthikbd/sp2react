# Changelog

All notable changes to `sp2react` are documented here.

## [Unreleased]

### Security
- Generated app: `requirements.txt` now requires `starlette>=1.3.1` (FastAPI's web layer) and `h11>=0.16.0` (uvicorn's HTTP parser). The old minimums let an existing environment keep versions with known advisories; a fresh install already got fixed versions. `fastapi` moves to `>=0.133.0`, the first release that accepts starlette 1.x, and `pydantic` to `>=2.7.0`, which that fastapi needs anyway. Python 3.10 is still supported. Regenerating an existing app picks this up (files you changed are kept)

### Changed
- Generated app front end: React 19 (was 18), Vite 8 (was 6) and `@vitejs/plugin-react` 6, with the matching `@types/react` and `@types/react-dom`. **Upgrade note:** building the generated app now needs Node.js 22.12+ or 20.19+ (Vite 8); the `test` stage says so instead of failing inside the build when Node.js is older. Regenerating an existing app picks this up (files you changed are kept); custom code that uses React 18-only APIs (`ReactDOM.render`, the global `JSX` namespace, `useRef()` without an argument) is reported by `tsc` and sent to the `fix` stage

## [0.1.5] - 2026-11-19

### Fixed
- JavaScript analysis: a script whose own code contained text shaped like the scanner's internal string placeholders (`__S7__`) stopped the inventory with an `IndexError` (found by ClusterFuzzLite). Such text is now kept apart from the placeholders

## [0.1.4] - 2026-11-19

OpenSSF Best Practices silver and baseline groundwork, and the fixes found by a threat model of sp2react. Each fix has a test in `tests/test_threat_model.py` that fails on 0.1.3.

### Security
- `extract`: a page or asset URL from the site with `..` segments (for example `<script src="/sites/x/../../../y.js">` in a page) was written relative to the workspace, so a page editor could make sp2react write files outside it. Every file the extract writes (page source, web part, wiki and rendered sidecars, assets, list folders) is now checked (`..`, absolute and drive paths, symlinks) and a refused one is listed as an extraction error, before it is downloaded
- `migrate`: attachment names and item ids from the server are checked the same way before the attachment is downloaded and written to the export folder
- The generated app's builds and tests (which run agent-written handlers) no longer receive sp2react's own credentials: the variables named in `sharepoint.*_env`, `llm.api_key_env` and `database.url_env` are removed from their environment
- Spec screen ids must be plain names (letters, digits, `_`, `-`, `.`, at most 128 characters), since they become folder and file names; generated ids longer than 100 characters are shortened and keep a hash of the full name
- **The generated app's back-end tests and loader run in a sandbox** (`pipeline.sandbox`, default `auto`). They import custom handlers written by agents, which until now ran as ordinary processes with the user's file and network access. `container` runs them in a throwaway Docker or Podman container with no network (or only the database host), a read-only file system except the folder the step writes, no capabilities, a non-root user and none of the host's environment; `guard` (used by `auto` when no container runtime answers) runs them under an audit hook that refuses writes outside that folder, new processes, other network hosts and `ctypes`; `off` keeps plain processes. Set `pipeline.sandbox_image` to use a check image from your registry
- **NTLM is an explicit, TLS-only choice.** `sharepoint.auth` has no default any more (NTLMv2 needs MD4 and HMAC-MD5 by protocol), and NTLM is never answered over plain HTTP (the site URL or any later request, so a redirect cannot downgrade it) unless `sharepoint.allow_ntlm_over_http: true`. The generated app's SharePoint data source does the same (`SP_AUTH` required, `SP_ALLOW_NTLM_OVER_HTTP=1`). **Upgrade note:** a config without `sharepoint.auth` now fails with "Field required"; add `auth: ntlm` (or `cookie`, `bearer`, `none`). Configs written by `sp2react init` already have it

### Fixed
- Generated app: `startswith`, `endswith` and `substringof` in `$filter` with a number instead of quoted text (`endswith(Title,0)`) failed with a server error; they now answer 400 like any other bad filter (found by ClusterFuzzLite). With `DATA_SOURCE=database`, `%` and `_` in their text are matched literally, as SharePoint and the other data sources do, instead of acting as SQL wildcards. Regenerating an existing app picks this up (`odata.py`, `sql_repo.py`; files you changed are kept)

### Added
- `GOVERNANCE.md`, `CODE_OF_CONDUCT.md`, `ROADMAP.md`, a VEX document (`vex.openvex.json`), and in the documentation a security assurance case (threat model), a dependency and scanning policy, testing and releasing pages
- Pull requests: a DCO check (every commit signed off) and GitHub dependency review
- CI: statement coverage must stay at 80% or more (about 86% now); a job builds the package twice and checks the files are identical, and releases are built the same way (`SOURCE_DATE_EPOCH`, `ci/reproducible_sdist.py`); the vulnerability audit also checks versions pinned only for other Python versions (`ci/all_pins.py`); Dependabot watches the fuzzing image

### Changed
- `mypy --strict` and `ruff` with the Bandit security rules (`S`), comprehensions, `PIE` and `RUF` are clean and required
- CI tool locks are compiled for the Python versions their jobs run (build 3.11, e2e 3.12)
- Documentation reorganised into Getting started, User guide, Reference, Development and Release notes; installation covers offline installs and verifying a download's signature, and the JFrog Curation notes no longer list the dependencies removed in 0.1.3

## [0.1.3] - 2026-11-19

Fixes found in a review of 0.1.2, no runtime dependencies, and signed, verifiable releases. Each fix has a test (`tests/test_hardening.py`, `tests/test_fidelity.py`, `tests/test_stdlib.py`) that fails on 0.1.2.

### Security
- Generated app: the catch-all route that serves the front end could return any file on the server (`/..%2fbackend%2f.env`, `/%2Fetc%2Fhostname`). It now serves only files inside `FRONTEND_DIST`
- Generated app: `AUTH_MODE` now defaults to `header` and fails closed (401 without the identity header). `dev` must be set explicitly, accepts requests from the same machine only, and no longer takes the user from the `?as=` query parameter. **Upgrade note:** set `AUTH_MODE=dev` when you run the app locally (the generated `.env.example` already does)
- Generated app: `/api/screens` and `/api/specs/{id}` now need a signed-in user
- Generated app: deleting an item and adding or removing attachments now follow the same role and lock rules as editing it (a locked item answered 204 to `DELETE`); attachment names are checked (no `/`, `\`, `..`, leading dots)
- Generated app: legacy Content Editor / Script Editor markup is rebuilt from an allow-list (`runtime/sanitize.ts`) instead of three regular expressions that `<svg/onload>`, unquoted and entity-encoded `javascript:` links got past
- Generated app (`DATA_SOURCE=sharepoint`): a user is matched by exact login, not by the first login that contains the text
- Agents: file paths proposed by the page, handler and fix agents must be plain relative paths inside the screen's folder; a path with `..` could overwrite `frontend/vite.config.ts` or write outside the output folder. Custom handler names must be identifiers

### Fixed
- Columns whose internal name starts with `_` or a digit (`2nd Approver` is `_x0032_nd_x0020_Approver`, `OData__x0032_nd_x0020_Approver` in REST) were migrated empty while the reconciliation said every list matched. Fields now record their REST name (`rest_name`), migration and the SharePoint data source read it, and specs from 0.1.2 work through the same naming rule. Reconciliation now fails when a field is in no exported item
- SharePoint throttling (429, 503) and dropped connections are retried with `Retry-After` (`sharepoint.retries`, `sharepoint.max_retry_wait`). If a list's fields or views, or a page's source, still cannot be read, `extract` fails instead of passing with an empty screen
- List pages: the "Title (linked to item)" column (`LinkTitle`) showed an empty column headed "LinkTitle"; it is now the Title column linked to the item. The page opens the list's default view with that view's sort order, instead of sorting by `ID desc`
- Two pages with the same file name in different libraries (`SitePages/Home.aspx`, `Pages/Home.aspx`) no longer share one screen id: both get their folder in the id
- Regenerating the app overwrote files the team had changed, such as `backend/app/auth.py`. A changed file is now kept, and the new version is written next to it as `<file>.sp2react-new`. Apps generated by 0.1.0 to 0.1.2 are recognised, so their unchanged files are still updated
- Multi-value lookup columns were edited as a single choice and an edit kept one value; they are now a multi-select list and every value is saved
- Date-and-time columns showed the UTC clock as local time on the edit form, and saved values had no zone. They are now edited in the browser's time zone and stored in UTC (`...Z`), as SharePoint returns them; values with an offset are converted by the API
- Hyperlink columns lost their description; they are now `{url, description}` everywhere (form, list, migration, reconciliation; a `description_column` in the database mapping). Managed metadata was stored as the raw REST object (`[object Object]`); terms are now `{label, term_id}` with the label read from the field's hidden note column, shown read-only
- List views ignored the view's filter and showed only the first page. The `<Where>` of the view is translated to the API filter (comparisons, And/Or, In, Contains, BeginsWith, IsNull, `<UserID />`, `<Today />`), a filter that cannot be translated is reported on the page, and the list pages through all items
- The list API returned every row when `$top` was not given; like SharePoint it now answers 100 rows by default and at most 5,000
- Wiki pages: their text lives in the page's `WikiField` column, which was never read, so a wiki page converted to an empty screen. It is now extracted and treated like Content Editor text
- A list whose URL name contains a space failed the spec gate (`endpoint path ... must contain only path characters`); the API client now also encodes list names in URLs

### Added
- Supply chain: hash-locked CI tool sets (`ci/requirements-*.txt`), a `zero-deps` job that installs and runs the package with nothing else installed, weekly `pip-audit` of every tool set and of the generated app's back end plus `npm audit` of its front end, ClusterFuzzLite fuzzing (`tests/fuzz`: config YAML, spec validation, ASPX/JavaScript analysis, NTLM challenges, the generated API's `$filter` parser), and an end-to-end workflow that runs `data_source: database` against real MySQL 8.4 and SQL Server 2022 containers
- Releases: published from GitHub releases only, with a check that the wheel declares no runtime dependencies, a CycloneDX SBOM, PyPI attestations, and Sigstore-signed wheel, sdist and SBOM on the GitHub release; `verify-release.yml` checks the signatures and that PyPI serves the same files
- Documentation site configuration for Read the Docs (Sphinx + MyST, warnings are errors), `CONTRIBUTING.md`, `THIRD_PARTY_NOTICES.md`; `ruff` and `mypy` clean

### Changed
- **No runtime dependencies.** `requests`, `requests-ntlm`, `pydantic` and `PyYAML` are replaced by standard-library code in the package: an HTTP client (`transport.py`: TLS verification or a CA bundle, proxies from `HTTPS_PROXY`/`NO_PROXY`, redirects checked hop by hop by the network policy), NTLMv2 Windows sign-in with channel binding on HTTPS (`ntlm.py`, checked against the MS-NLMP test vectors), validated records (`model.py`) and a YAML reader for the config file (`yamlish.py`, which refuses anchors, tags, tabs and duplicate keys with a line number). `pip install sp2react` installs one wheel. The `ntlm` extra remains, empty
- Docs: workflows, event receivers, InfoPath and Power Apps are listed as not detected (they were described as reported); remaining known gaps are listed in [Coverage and limitations](https://sp2react.readthedocs.io/en/latest/user_guide/limitations.html)

## [0.1.2] - 2026-10-29

### Security
- Generated app front-end template moved to versions with no known vulnerabilities: Vite 6.4.4+ (was 5.4), react-router-dom 7.18.4+ (was 6.28), @vitejs/plugin-react 4.7. `npm audit` on the template reports 0 vulnerabilities; the generated app builds and passes the 29-step browser walkthrough
- Minimum versions raised past every known advisory: `requests>=2.33.0` (package and generated back end), `pymysql>=1.1.1` (`mysql` extra), `pytest>=9.0.3` (`dev` extra)

### Added
- Dependabot for GitHub Actions, pip and the generated app templates
- CodeQL code scanning (Python, JavaScript/TypeScript)
- `setup.py` shim for tools that still call it

## [0.1.1] - 2026-10-29

### Added
- End-to-end documentation in `docs/`: how it works, installation (Windows, JFrog), configuration reference, Bridger and other model providers, SQL Server / MySQL / PostgreSQL and the mapping file, a full walkthrough, command reference, the generated app and deployment, security, troubleshooting, Python API, coverage and limitations

### Changed
- `sp2react init` template and the generated `.env.example` show SQL Server connection URLs and `database.schema_name`
- README: run the generated API with `uvicorn --env-file .env` (the app does not load `.env` by itself)
- CI: every GitHub Action pinned to a commit SHA; Scorecard uses an existing `ossf/scorecard-action` release

## [0.1.0] - 2026-10-29

First public release.

### Added
- Ten-stage pipeline (inputs, extract, inventory, spec, approve spec, convert, review, test, fix, approve) with gating: a stage only starts when the one before it is done
- Read-only SharePoint extraction: `.aspx` source, browser-added web parts, Script Editor / Content Editor content and links, JSLink, custom scripts and CSS, list schemas, views, forms, groups, navigation
- Inventory of jQuery / SPServices behaviour with file:line references (show/hide, read-only, defaults, cascades, PreSaveAction validation, group checks, redirects, REST and SPServices calls)
- Spec model, deterministic base spec and a coverage gate that blocks approval until every required behaviour is covered and legacy texts are verbatim
- AI agents (Claude through GitHub Copilot Bridger by default; Anthropic, OpenAI and Azure OpenAI also supported) for spec, page, custom handler, review, fix and database mapping, each validated before its output is accepted
- Generated React (Vite + TypeScript) + FastAPI app: shared list-form engine driven by the spec, the same rule engine in the browser and the API (checked by shared test vectors), legacy URL redirects, SharePoint groups as roles
- `data_source: database`: the generated API reads and writes your existing tables (MySQL, SQL Server, PostgreSQL via SQLAlchemy) through a reviewed list-to-table mapping drafted by `sp2react map-db`; filters, sorting and paging run as SQL
- `data_source: sqlite`: full paged export of list items and attachments, loaded into a SQLite copy
- Field-by-field reconciliation report between SharePoint lists and the app's data (opt-in in database mode)
- Network policy: every request is checked against the configured SharePoint and model hosts, including redirects; list items, attachments, people and rendered pages are never read in database mode
