# Changelog

All notable changes to `sp2react` are documented here.

## [Unreleased]

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
