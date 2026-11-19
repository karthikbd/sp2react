# Contributing to sp2react

Thanks for helping. Bug reports, documentation fixes, new SharePoint patterns the analysis should recognise and better generated code are all welcome.

## Reporting bugs and asking questions

- **Bugs and feature requests:** open a [GitHub issue](https://github.com/karthikbd/sp2react/issues).
  Include the sp2react version (`sp2react --version`), Python version, SharePoint version, the
  command you ran, and the output of `sp2react doctor` if it is relevant. Remove host names,
  credentials, list data and page content you can't share.
- **Security vulnerabilities:** do **not** open a public issue. Report them privately as described in
  [SECURITY.md](SECURITY.md).

The maintainer aims to respond to new issues within 7 days.

## Making a change

1. Open an issue first for anything larger than a small fix, so the approach can be agreed.
2. Fork the repository and create a branch from `main`.
3. Set up a development environment:

   ```console
   $ python -m venv .venv && . .venv/bin/activate
   $ pip install --require-hashes -r ci/requirements-test.txt
   $ pip install --no-deps -e .
   ```

4. Make the change, **with tests** (see below), and update the documentation in `docs/` and
   `CHANGELOG.md` when behaviour changes.
5. Run the checks CI runs:

   ```console
   $ ruff check src tests          # lint: must be clean
   $ mypy src                      # types: must be clean
   $ pytest -q                     # unit, pipeline, generated-app and over-the-wire HTTP tests (Node 22 for the TypeScript ones)
   $ python -m sphinx -W -b html docs docs/_build/html   # docs: warnings are errors
   ```

6. Open a pull request against `main`. CI runs the tests on Python 3.10–3.13, the end-to-end suite
   against MySQL 8.4 and SQL Server 2022, CodeQL, a vulnerability audit and ClusterFuzzLite
   fuzzing. All of them must pass.

## Rules for code

- **No runtime dependencies.** sp2react must install and run with the Python standard library only.
  The database extras (SQLAlchemy and a driver) are imported inside the functions that need them.
  The `zero-deps` CI job installs the package alone and runs it.
- **No network access except to configured systems.** Only `src/sp2react/transport.py` opens
  connections, every request passes `net.NetworkPolicy`, and SharePoint is read with GET only.
  `tests/test_network.py` enforces this.
- **Agents never write unchecked output.** Anything an agent returns is validated in
  `agents/tasks.py` before it is accepted, and file paths must stay inside their screen's folder.
- **Tests are required.** New functionality needs tests that would fail without it; bug fixes need a
  regression test. Code that talks to SharePoint needs a test against the mock site
  (`tests/mock_sharepoint.py`); database code runs in the end-to-end job against real servers.
  The browser and API rule engines must agree on `scaffold/rule_vectors.json`.
- **Legacy pages, agent output and configs are untrusted.** Parsing code should have a fuzz target in
  `tests/fuzz` (Atheris).
- **Style:** `ruff` and `mypy` clean; type hints on public functions.
- **CI tooling is hash-locked.** To change a tool version, edit `ci/requirements-*.in` and regenerate
  the `.txt` file with `uv pip compile --universal --generate-hashes --python-version 3.10 ci/requirements-X.in -o ci/requirements-X.txt`.
  GitHub Actions are pinned by commit SHA.

## Licensing of contributions

sp2react is MIT-licensed. By submitting a pull request you agree that your contribution is licensed
under the same [MIT License](LICENSE), and you confirm you have the right to submit it. Code copied
from other projects must have a compatible license and be recorded in `THIRD_PARTY_NOTICES.md`.

## Releases

Releases follow [semantic versioning](https://semver.org/) and are described in `CHANGELOG.md`. To release:
bump the version in `pyproject.toml` and `src/sp2react/__init__.py`, date the CHANGELOG entry, add the release's
template hashes to `src/sp2react/scaffold/released_templates.json`, merge to `main`, then publish a GitHub release
`vX.Y.Z`. `python-publish.yml` tests, builds, publishes with Trusted Publishing and signs the assets;
`verify-release.yml` then checks the signatures and the files on PyPI.
