# 2. Installation

## Requirements

| What | Version | Needed for |
|---|---|---|
| Python | 3.10 – 3.13 | sp2react itself |
| Node.js | 20 or later (with npm) | building and type-checking the generated React app (the `test` stage). Without it, run with `--no-builds` |
| A database driver | see below | `data_source: database` |
| Network access | to the SharePoint site and to the model endpoint (Bridger) | nothing else |

## Choose the extras

sp2react has a small core (`pydantic`, `pyyaml`, `requests`). Add extras for what you use:

| Extra | Installs | Use when |
|---|---|---|
| `mssql` | SQLAlchemy, pyodbc | your data is in **SQL Server** |
| `mysql` | SQLAlchemy, PyMySQL | your data is in **MySQL / MariaDB** |
| `db` | SQLAlchemy only | another database (add its driver yourself, e.g. `psycopg` for PostgreSQL) |
| `ntlm` | requests-ntlm | SharePoint on-premises with **Windows authentication** (`auth: ntlm`) |
| `dev` | pytest, FastAPI, httpx, uvicorn, SQLAlchemy | running sp2react's own test suite |

Combine them: `pip install "sp2react[mssql,ntlm]"`.

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

JFrog Curation evaluates new packages before allowing them. sp2react is MIT-licensed, published from GitHub with PyPI Trusted Publishing, and has an OpenSSF Scorecard. A very new version can be held by a "package age" policy for some days; that is a policy wait, not a problem with the package. Its dependencies (pydantic, PyYAML, requests, SQLAlchemy, pyodbc or PyMySQL, requests-ntlm) are common packages that are usually already approved.

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

Read [CHANGELOG.md](../CHANGELOG.md) before upgrading in the middle of a conversion, and keep a copy of `sp2react-work/` and `db-mapping.json`.

## Next

[3. Configuration reference](03-configuration.md)
