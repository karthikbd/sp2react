# Testing

| Layer | Where | Needs |
|---|---|---|
| Unit and analysis | `tests/test_extract_inventory.py`, `tests/test_stdlib.py` | nothing |
| Agents | `tests/test_agents.py` | nothing: a scripted model (`tests/scripted_agents.py`) and in-process HTTP servers standing in for Bridger, Anthropic and OpenAI |
| Pipeline | `tests/test_pipeline.py` | Node 22.6+ for the generated app's build and TypeScript tests: all ten stages against a mock SharePoint site (`tests/mock_sharepoint.py`, over HTTP with NTLM) |
| Generated app | `tests/test_fidelity.py`, `tests/test_hardening.py` | the generated app's packages (in `ci/requirements-test.txt`) |
| Guards | `tests/test_network.py`, `tests/test_threat_model.py` | nothing: only configured hosts, GET only, no other network code; the threat model's regression tests |
| End to end | `tests/test_pipeline.py -k database` with `SP2REACT_E2E_DB_URL` | a real MySQL or SQL Server |
| Fuzzing | `tests/fuzz/` | Atheris; run by ClusterFuzzLite in CI |

```console
$ pytest -q
$ python -m coverage run -m pytest -q && python -m coverage report   # CI fails below 80% statements
$ SP2REACT_E2E_DB_URL="mysql+pymysql://root:pw@127.0.0.1:3306/sea" pytest tests/test_pipeline.py -k database -v
```

End-to-end jobs in CI (`e2e.yml`) run `data_source: database` against a MySQL 8.4 container and a SQL
Server 2022 container (pyodbc with Microsoft ODBC Driver 18): the database is created in the shape a
migration leaves it, `map-db` maps it, and the generated app's tests and the reconciliation run against
it.

Fuzzing (`tests/fuzz`, Atheris): the config YAML reader, spec validation, ASPX and JavaScript analysis,
NTLM challenge parsing, and the generated API's `$filter` parser. `cflite_pr.yml` fuzzes the code a
pull request changes; `cflite_batch.yml` fuzzes longer on every push to `main` and daily. Locally:

```console
$ pip install atheris
$ python tests/fuzz/fuzz_config_yaml.py -max_total_time=60
```

CI (`.github/workflows/`) runs: `tests.yml` (Python 3.10–3.13 with ruff, mypy `--strict`, coverage;
`zero-deps`; a reproducible-build check; a warnings-as-errors docs build), `e2e.yml`,
`cflite_pr.yml` / `cflite_batch.yml`, `codeql.yml`, `scorecard.yml`, `vulnerability-audit.yml`, and
on pull requests `dependency-review.yml` and `dco.yml`.

## Locked tool versions

Every `pip install` in CI uses `--require-hashes` with a file from `ci/`. To change a tool version, edit
the `.in` file and regenerate the `.txt` file for the lowest Python version of the jobs that install it
(the command is in the header of each `.txt` file):

```console
$ uv pip compile --universal --generate-hashes --python-version 3.10 ci/requirements-test.in -o ci/requirements-test.txt
```

| File | Python | Used by |
|---|---|---|
| `requirements-test.txt` | 3.10 | tests (3.10–3.13), e2e, publish |
| `requirements-build.txt` | 3.11 | publish, reproducible-build |
| `requirements-e2e.txt` | 3.12 | e2e |
| `requirements-docs.txt`, `-audit.txt`, `-verify.txt` | 3.12 | docs and Read the Docs, vulnerability audit, verify-release |
