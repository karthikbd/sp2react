# sp2react: notes for Claude Code

Python package that converts classic SharePoint (ASPX + jQuery/SPServices list forms and web part pages) into a React (Vite + TS) + FastAPI app that runs on an existing database. Owner: Karthikeyan Balasundaram (karthikbd). Target: PNC Sanctions Dashboard on SharePoint on-prem (`/sites/SEA`), data already migrated to MySQL.

## Hard constraints
- No HTTP calls for business data. In `data_source: database` (default) the SharePoint client refuses list items, attachments, site users, rendered pages and group membership (`ItemReadBlocked`). Every request goes through `net.NetworkPolicy` (SharePoint host + `llm.base_url` host only, redirects included). SharePoint is GET-only. Keep `tests/test_network.py` green; never add another HTTP client: `transport.py` is the only code that opens connections.
- No runtime dependencies (like karthikbd/mssql-ocp-migrate and lodestream). HTTP + NTLMv2 (`transport.py`, `ntlm.py`), validation (`model.py`, pydantic-like) and the config YAML reader (`yamlish.py`) are standard library only. Database extras are imported lazily. The `zero-deps` CI job checks it.
- Generated code (the app's back-end tests and loader import agent-written handlers) runs only through `sandbox.Sandbox` (container, or the `sandbox_guard.py` audit-hook guard); never call the generated app with plain subprocesses. `sharepoint.auth` has no default; NTLM is refused over http unless `allow_ntlm_over_http`.
- AI agents use Claude through GitHub Copilot Bridger (`llm.provider: bridger`, `api_format: anthropic`). Agent output is accepted only after validation (`agents/tasks.py`).
- Standards as lodestream and mssql-ocp-migrate (OpenSSF Best Practices silver/baseline): `mypy --strict` and ruff with `S` rules clean, statement coverage >= 80% (`ci/check_coverage.py`), reproducible builds (`ci/reproducible_sdist.py`), DCO sign-off on every commit (`git commit -s`), dependency review; changes reach `main` through pull requests only. Update `docs/development/security-assurance.md` when adding inputs, connections, files written or generated-app endpoints.
- Packaging follows karthikbd/zipfinder and address-finder: MIT, author "Karthikeyan Balasundaram", `python-publish.yml` with PyPI Trusted Publishing (environment `release`), `scorecard.yml` (OpenSSF, needed for JFrog Curation at PNC), `.codacy/cli.sh`, `tests.yml` on 3.10–3.13.

## Layout
- `src/sp2react/pipeline.py`: ten gated stages (inputs, extract, inventory, spec, approve_spec, convert, review, test, fix, approve) plus `map_db`, `migrate`, `reconcile`.
- `sharepoint/`: read-only REST client and extraction. `analysis/`: ASPX parsing, JS tokenizer and jQuery/SPServices behaviour inventory. `spec/`: spec model, base spec, coverage gate.
- `agents/`: prompts (`prompts/*.md`) and the validate-and-retry tasks. `llm/providers.py`: Bridger, Anthropic, OpenAI, Azure, `ScriptedLLM` for tests.
- `dbmap.py`: schema-only reflection, mapping draft, validation. `migrate.py`: export, reconcile.
- `scaffold/templates/`: generated app. Backend `sql_repo.py` (OData to SQL over mapped tables), `rules.py`; frontend `runtime/rules.ts`. The two rule engines must agree on `scaffold/rule_vectors.json`.

## Commands
```bash
pip install --require-hashes -r ci/requirements-test.txt && pip install --no-deps -e .
ruff check src tests && mypy src
python -m coverage run -m pytest tests/ -q && python -m coverage report   # needs Node 22.6+ (generated-app build, TypeScript runtime tests)
python -m sphinx -W -b html docs docs/_build/html
python -m build && twine check dist/*
```
CI (all hash-locked, actions pinned by SHA): tests.yml (3.10-3.13 with coverage, zero-deps, reproducible-build, docs), dco.yml and dependency-review.yml (PRs), e2e.yml (MySQL 8.4, SQL Server 2022 via SP2REACT_E2E_DB_URL), vulnerability-audit.yml (pip-audit + npm audit of the generated app), cflite_pr/batch (tests/fuzz), codeql, scorecard, python-publish.yml (release only: test, build + no-deps check + SBOM, Trusted Publishing, Sigstore-signed assets), verify-release.yml.

## Open work (in priority order)
1. Releases: bump `version` in pyproject.toml and `__version__` in src/sp2react/__init__.py, move CHANGELOG [Unreleased] to the new version, add the release's template hashes to `src/sp2react/scaffold/released_templates.json` (sha256 of each file under `scaffold/templates`, placeholders `__SITE_TITLE__`/`__DEFAULT_SOURCE__` left in; `copy_templates` uses them to upgrade unchanged apps), merge it into main through a pull request, then publish a GitHub release `vX.Y.Z` on main. `python-publish.yml` tests and publishes to PyPI via Trusted Publishing (environment `release`). Published: 0.1.0, 0.1.1, 0.1.2, 0.1.3. Read the Docs project `sp2react` must be imported once on readthedocs.org (config in `.readthedocs.yaml`).
2. Site-wide assessment command: Site Contents incl. subsites, lists/libraries, content types, workflows, event receivers, InfoPath, with a per-page conversion readiness report.
3. Button/command inventory (ribbon, custom buttons, onclick handlers) mapped to spec actions.
4. Views with filters and grouping; rich grid (sort, search, select, export).
5. Modal dialogs (`SP.UI.ModalDialog`) to React dialogs.
6. Master-page branding capture.
7. Document libraries.
8. Side-by-side SharePoint vs React compare view (started in the demo, unfinished).
9. First real run against the UAT farm, real Bridger and the real SQL Server database (data already migrated there).
