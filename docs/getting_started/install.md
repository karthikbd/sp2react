# Installation

## Requirements

| What | Version | Needed for |
|---|---|---|
| Python | 3.10 – 3.13 | sp2react itself |
| Node.js | 20 or later (with npm) | building and type-checking the generated React app (the `test` stage). Without it, run with `--no-builds` |
| A database driver | see below | `data_source: database` |
| Network access | to the SharePoint site and to the model endpoint (Bridger) | nothing else |

## Choose the extras

sp2react itself has **no runtime dependencies**: its HTTP client, Windows (NTLM) sign-in, YAML reader and spec validation use only the Python standard library. Add extras only for the database you use:

| Extra | Installs | Use when |
|---|---|---|
| `mssql` | SQLAlchemy, pyodbc | your data is in **SQL Server** |
| `mysql` | SQLAlchemy, PyMySQL | your data is in **MySQL / MariaDB** |
| `db` | SQLAlchemy only | another database (add its driver yourself, e.g. `psycopg` for PostgreSQL) |
| `dev` | pytest, FastAPI, httpx, uvicorn, SQLAlchemy, requests | running sp2react's own test suite (the generated app's packages) |

Windows authentication (`auth: ntlm`) needs no extra any more; `sp2react[ntlm]` still installs, as an empty extra.

## Windows (PowerShell)

```powershell
# 1. A virtual environment
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install
python -m pip install --upgrade pip
pip install "sp2react[mssql,ntlm]"

# 3. Check
sp2react --version
```

If `Activate.ps1` is blocked, run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, or use `.\.venv\Scripts\activate.bat` from `cmd`.

**SQL Server only:** pyodbc needs Microsoft's ODBC driver. Check *ODBC Data Sources (64-bit) → Drivers* for **ODBC Driver 18 for SQL Server** (17 also works). If it is missing, install it from Microsoft or ask your desktop team.

## Inside a corporate network (JFrog Artifactory / Curation)

If pip goes through Artifactory, point it at your PyPI remote repository:

```powershell
pip install --index-url https://<artifactory-host>/artifactory/api/pypi/<pypi-remote>/simple "sp2react[mssql,ntlm]"
```

or once, for all installs:

```powershell
pip config set global.index-url https://<artifactory-host>/artifactory/api/pypi/<pypi-remote>/simple
```

JFrog Curation evaluates new packages before allowing them. sp2react is easy to approve:

- **One package, nothing else.** It has no runtime dependencies, so Curation evaluates exactly one
  package. The database extras add only SQLAlchemy and one driver (pyodbc or PyMySQL), which are
  usually approved already.
- **MIT-licensed**, published from GitHub with **PyPI Trusted Publishing**. Every file on PyPI has a
  **provenance attestation** linking it to the GitHub workflow run that built it.
- **Signed, reproducible releases.** GitHub release assets (wheel, sdist and a CycloneDX SBOM) are
  signed with **Sigstore**, and the same commit always builds to the same bytes.
- **Continuous checks:** OpenSSF Scorecard and Best Practices, CodeQL, fuzzing, and a weekly
  `pip-audit` of every build and test tool plus an audit of the generated app's packages.

A very new version can be held by a "package age" policy for some days; that is a policy wait, not a
problem with the package.

## Offline and air-gapped installs

sp2react has no dependencies, so a single wheel file is a complete installation of the converter:

```console
$ pip download --no-deps sp2react=={{ version }} -d wheels         # on a machine with access
$ pip install --no-index --no-deps wheels/sp2react-{{ version }}-py3-none-any.whl
```

`--no-index` makes pip refuse any network access, which proves nothing else is fetched. Download the
database extra's packages (`pip download "sp2react[mssql]" -d wheels`) the same way if you need them.

## Verifying a download

To check a downloaded file's signature against the GitHub workflow that produced it:

```console
$ pip download --no-deps sp2react=={{ version }} -d dl
$ gh release download v{{ version }} -R karthikbd/sp2react -p "sp2react-{{ version }}-py3-none-any.whl.sigstore.json" -D dl
$ python -m pip install sigstore
$ python -m sigstore verify github dl/sp2react-{{ version }}-py3-none-any.whl \
    --bundle dl/sp2react-{{ version }}-py3-none-any.whl.sigstore.json \
    --cert-identity https://github.com/karthikbd/sp2react/.github/workflows/python-publish.yml@refs/tags/v{{ version }} \
    --repository karthikbd/sp2react --ref refs/tags/v{{ version }} --trigger release
OK: dl/sp2react-{{ version }}-py3-none-any.whl
```

Behind a proxy that blocks Sigstore's update server (`tuf-repo-cdn.sigstore.dev`), add `--offline`. The
same check runs on GitHub after every release (`verify-release.yml`), which also confirms PyPI serves
byte-identical files.

## Linux / macOS

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install "sp2react[mssql,ntlm]"     # or [mysql,ntlm]
sp2react --version
```

For SQL Server on Linux, install `unixodbc` and Microsoft's `msodbcsql18` package.

## Node.js for the generated app

The `test` stage runs `npm install`, `tsc` and `vite build` on the generated front end. Check with:

```powershell
node --version   # v20 or later
npm --version
```

If npm also goes through Artifactory, set `npm config set registry https://<artifactory-host>/artifactory/api/npm/<npm-remote>/`. If you cannot install Node.js on the machine that runs sp2react, use `--no-builds` (or `pipeline.run_builds: false`) and build the front end elsewhere.

## Upgrading

```powershell
pip install --upgrade "sp2react[mssql,ntlm]"
```

Read [CHANGELOG.md](https://github.com/karthikbd/sp2react/blob/main/CHANGELOG.md) before upgrading in the middle of a conversion, and keep a copy of `sp2react-work/` and `db-mapping.json`.

## Next

[Configuration reference](../user_guide/configuration.md)
