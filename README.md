# sp2react

[![PyPI version](https://badge.fury.io/py/sp2react.svg)](https://pypi.org/project/sp2react/)
[![Python versions](https://img.shields.io/pypi/pyversions/sp2react.svg)](https://pypi.org/project/sp2react/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![OpenSSF Scorecard](https://api.securityscorecards.dev/projects/github.com/karthikbd/sp2react/badge)](https://securityscorecards.dev/viewer/?uri=github.com/karthikbd/sp2react)

Convert classic SharePoint (2013 / 2016 / 2019 / Subscription Edition) list forms and pages built with **ASPX, jQuery and SPServices** into a **React + FastAPI** app that runs on **your existing database**.

Plain code does everything mechanical. AI agents (Claude through your GitHub Copilot **Bridger** by default) do the parts that need judgement. Nothing an agent writes is accepted until it passes automatic checks.

**No business data over HTTP:** in the default `database` mode, list items, attachments and people are never read from SharePoint, and every request is checked against the hosts in your config.

---

## Table of Contents

- [Installation](#installation)
- [Quick Start](#quick-start)
- [Configuration](#configuration)
- [The ten stages](#the-ten-stages)
- [Your existing database](#your-existing-database)
- [The generated app](#the-generated-app)
- [Use it from your own tool](#use-it-from-your-own-tool)
- [What converts and what does not](#what-converts-and-what-does-not)
- [Running Tests](#running-tests)
- [CI / CD](#ci--cd)
- [Security](#security)
- [Changelog](#changelog)
- [License](#license)

---

## Installation

```bash
pip install "sp2react[mysql]"     # MySQL / MariaDB tables
pip install "sp2react[mssql]"     # SQL Server tables
pip install "sp2react[ntlm]"      # add for on-premises Windows authentication
```

Python 3.10+. Node.js 20+ is needed to build the generated React app.

## Quick Start

```bash
sp2react init                                   # writes sp2react.yaml
export SP_USERNAME='CORP\me' SP_PASSWORD='...'  # or SP_COOKIE / SP_TOKEN
export BRIDGER_TOKEN='...'                      # only if Bridger needs one
export SP2REACT_DB_URL='mysql+pymysql://user:password@db-host:3306/sea'

sp2react doctor                                 # checks SharePoint, lists Bridger's Claude models
sp2react run --page /sites/SEA/SitePages/Dashboard.aspx --until spec
#   review sp2react-work/specs/<screen>.coverage.md, then:
sp2react approve Dashboard
sp2react map-db                                 # drafts db-mapping.json; review db-mapping.md
sp2react run --page /sites/SEA/SitePages/Dashboard.aspx --offline
sp2react status
```

## Configuration

```yaml
sharepoint:
  site_url: https://sharepoint.example.com/sites/SEA
  auth: ntlm                 # ntlm | cookie | bearer | none ; secrets come from environment variables
llm:
  provider: bridger          # bridger | anthropic | openai | azure_openai
  api_format: anthropic      # how Bridger serves Claude: anthropic (/v1/messages) or openai (/v1/chat/completions)
  base_url: http://localhost:4141
  model: claude-sonnet-4     # exact id from `sp2react doctor`
  api_key_env: BRIDGER_TOKEN
pipeline:
  data_source: database      # database | sqlite | sharepoint
  max_concurrency: 4
  max_fix_iterations: 5
database:
  url_env: SP2REACT_DB_URL
  mapping: ./db-mapping.json
security:
  allowed_hosts: []
```

## The ten stages

Each stage starts only after the previous one has finished.

| # | Stage | Who | What happens | Checked by |
|---|---|---|---|---|
| 1 | inputs | code | config and connectivity | |
| 2 | extract | code | `.aspx` source, browser-added web parts, Script Editor / Content Editor content, JSLink, custom JS/CSS, list schemas, views, forms, group names, navigation. GET only | manifest of fetched files and errors |
| 3 | inventory | code | groups each list's New/Edit/Display forms into one screen and finds every jQuery behaviour and data call, with file:line | deterministic |
| 4 | spec | **agent** | builds the base spec from the schema, then the agent adds the rules that need interpretation | **coverage gate**: every required behaviour covered, legacy texts verbatim, rules valid |
| 5 | approve_spec | you | read `specs/<screen>.coverage.md` | |
| 6 | convert | code + **agents** | writes the fixed scaffold in seconds. List forms are rendered by the shared form engine from the spec; agents write only page components and custom handlers, in parallel | import whitelist, no fetch/jQuery/innerHTML, legacy texts present, `tsc` |
| 7 | review | **agent** | independent parity review | findings fed to fix |
| 8 | test | code | generated API tests, rule vectors (browser and API engines must agree), `tsc` + `vite build`, data reconciliation | |
| 9 | fix | **agent** | gets the real compiler and test output and edits only agent-owned files; up to N rounds | re-test |
| 10 | approve | you | | |

## Your existing database

If your team has already moved the list data into MySQL or SQL Server, the generated FastAPI app reads and writes those tables directly.

1. `sp2react map-db` reads the database **schema only** (tables, columns, types, keys).
2. It drafts the mapping: each list to a table, each field to a column, lookups to foreign keys, people to a users table or login column, plus created/modified/author/editor/version columns and attachments.
3. The `dbmap` agent resolves what the draft could not, for example `Countries.Title` migrated as `countries.country_name`.
4. Validation blocks code generation until every table and column exists and every required field is mapped.
5. You review `db-mapping.md`, and can edit `db-mapping.json` directly.

At runtime, OData-style queries from the forms and pages (`$filter`, `$orderby`, `$top`, lookup paths such as `Country/Title`) are translated to SQL. Optimistic concurrency uses your version column if you have one, otherwise the modified timestamp.

To check the earlier migration, set `security.sharepoint_item_reads: true`. `reconciliation.md` then compares every list item with its row, field by field, including orphaned lookups and attachment checksums.

## The generated app

```bash
cd converted-app/backend && pip install -r requirements.txt pymysql && cp .env.example .env && uvicorn app.main:app
cd converted-app/frontend && npm install && npm run dev
```

- Behaviour comes from the spec at runtime. `runtime/rules.ts` (browser) and `app/rules.py` (API) interpret the same rules, and shared vectors keep them in agreement, so a direct API call cannot bypass a rule.
- The form uses SharePoint's layout, labels and control titles, the legacy site CSS is carried over, and old URLs (`/Lists/X/EditForm.aspx?ID=3&Source=...`) redirect to the new routes.
- SharePoint groups become roles. Membership comes from your users/groups tables or `data/roles.json`.
- Authentication: `AUTH_MODE=dev` for local work; `header` behind your gateway, or Entra ID in `app/auth.py`.

## Use it from your own tool

```python
from sp2react import Pipeline, load_config

p = Pipeline(load_config("sp2react.yaml"), progress=print)
p.stage_inputs(offline=False)
p.stage_extract(pages=["SitePages/Dashboard.aspx"], offline=False)
screens = [s["id"] for s in p.stage_inventory(["SitePages/Dashboard.aspx"])]
p.stage_spec(screens)
p.approve("Dashboard", "spec", by="reviewer")
p.stage_map_db([p.load_spec(s) for s in p.approved_sids()])
p.stage_convert(screens)
p.stage_review(screens)
p.stage_test_and_fix(screens)
p.state            # also written to sp2react-work/state.json
```

## What converts and what does not

| Converts | Needs your input, or is not converted yet |
|---|---|
| List forms (New/Edit/Display) and their jQuery/SPServices behaviour | Workflows, event receivers, compiled solutions: their code is not reachable over REST. They are flagged; export the definitions or source to convert them |
| Web part pages (SitePages) with Script Editor / Content Editor JavaScript | InfoPath and Power Apps forms: reported, not converted |
| Basic list views (columns, sort, row limit) | Views with filters and grouping, document libraries, custom master-page branding, rich grids (sort/search/select/export), modal dialogs: planned |
| SharePoint groups as roles, old URL redirects | Calculated columns are shown but not recomputed; managed metadata, item-level permissions, alert emails |

Run the inventory on your site first. It shows which pages and scripts were found and what each one does, before you commit to a conversion.

## Running Tests

```bash
pip install -e ".[dev]"
python -m pytest tests/ -v
```

The suite runs against `tests/fixtures/legacy-site`, a fictional Contoso procurement site with jQuery 1.12 / SPServices list forms and a REST-driven dashboard. It covers:
- a mock SharePoint server that rejects writes,
- a scripted stand-in for the model, including retry-on-feedback and give-up,
- a renamed-schema database standing in for an earlier migration,
- the network policy,
- all ten stages including the fix loop,
- a real `npm install` + `tsc` + `vite build` of the generated app.

## CI / CD

- `tests.yml`: runs the test suite on Python 3.10–3.13 on every push and pull request.
- `python-publish.yml`: on a `v*` tag or a published release, tests, builds and publishes to PyPI through **Trusted Publishing** (OIDC, no stored token).
- `scorecard.yml`: runs the OpenSSF Scorecard weekly and on every push to `main`.

## Security

See [SECURITY.md](SECURITY.md). In short:
- Requests go only to the configured SharePoint and model hosts, and SharePoint is read-only.
- In database mode no list data is read over HTTP and no business data is sent to the model.
- Secrets come from environment variables only.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT. See [LICENSE](LICENSE).
