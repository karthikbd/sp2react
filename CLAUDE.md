# sp2react: notes for Claude Code

Python package that converts classic SharePoint (ASPX + jQuery/SPServices list forms and web part pages) into a React (Vite + TS) + FastAPI app that runs on an existing database. Owner: Karthikeyan Balasundaram (karthikbd). Target: PNC Sanctions Dashboard on SharePoint on-prem (`/sites/SEA`), data already migrated to MySQL.

## Hard constraints
- No HTTP calls for business data. In `data_source: database` (default) the SharePoint client refuses list items, attachments, site users, rendered pages and group membership (`ItemReadBlocked`). Every request goes through `net.NetworkPolicy` (SharePoint host + `llm.base_url` host only, redirects included). SharePoint is GET-only. Keep `tests/test_network.py` green; never add another HTTP client.
- AI agents use Claude through GitHub Copilot Bridger (`llm.provider: bridger`, `api_format: anthropic`). Agent output is accepted only after validation (`agents/tasks.py`).
- Packaging follows karthikbd/zipfinder and address-finder: MIT, author "Karthikeyan Balasundaram", `python-publish.yml` with PyPI Trusted Publishing (environment `release`), `scorecard.yml` (OpenSSF, needed for JFrog Curation at PNC), `.codacy/cli.sh`, `tests.yml` on 3.10–3.13.

## Layout
- `src/sp2react/pipeline.py`: ten gated stages (inputs, extract, inventory, spec, approve_spec, convert, review, test, fix, approve) plus `map_db`, `migrate`, `reconcile`.
- `sharepoint/`: read-only REST client and extraction. `analysis/`: ASPX parsing, JS tokenizer and jQuery/SPServices behaviour inventory. `spec/`: spec model, base spec, coverage gate.
- `agents/`: prompts (`prompts/*.md`) and the validate-and-retry tasks. `llm/providers.py`: Bridger, Anthropic, OpenAI, Azure, `ScriptedLLM` for tests.
- `dbmap.py`: schema-only reflection, mapping draft, validation. `migrate.py`: export, reconcile.
- `scaffold/templates/`: generated app. Backend `sql_repo.py` (OData to SQL over mapped tables), `rules.py`; frontend `runtime/rules.ts`. The two rule engines must agree on `scaffold/rule_vectors.json`.

## Commands
```bash
pip install -e ".[dev]"
python -m pytest tests/ -q          # needs Node 20+ for the generated-app build test
python -m build && twine check dist/*
```

## Open work (in priority order)
1. Releases: bump `version` in pyproject.toml and `__version__` in src/sp2react/__init__.py, move CHANGELOG [Unreleased] to the new version, push main, then publish a GitHub release `vX.Y.Z` on main. `python-publish.yml` tests and publishes to PyPI via Trusted Publishing (environment `release`). Published: 0.1.0, 0.1.1.
2. Site-wide assessment command: Site Contents incl. subsites, lists/libraries, content types, workflows, event receivers, InfoPath, with a per-page conversion readiness report.
3. Button/command inventory (ribbon, custom buttons, onclick handlers) mapped to spec actions.
4. Views with filters and grouping; rich grid (sort, search, select, export).
5. Modal dialogs (`SP.UI.ModalDialog`) to React dialogs.
6. Master-page branding capture.
7. Document libraries.
8. Side-by-side SharePoint vs React compare view (started in the demo, unfinished).
9. First real run against the UAT farm, real Bridger and the real SQL Server database (data already migrated there).
