# sp2react documentation

sp2react converts a classic SharePoint site (ASPX pages, list forms, jQuery and SPServices scripts) into a React + FastAPI application that reads and writes your existing database. AI agents (Claude, through GitHub Copilot Bridger by default) handle the parts that need judgement; plain code does the rest, and nothing an agent writes is accepted until it passes automatic checks.

## Start here

| If you want to... | Read |
|---|---|
| Understand what sp2react does and how | [1. How it works](01-how-it-works.md) |
| Install it (Windows, PNC/JFrog, Linux) | [2. Installation](02-installation.md) |
| Write `sp2react.yaml` | [3. Configuration reference](03-configuration.md) |
| Connect Claude through Bridger (or another provider) | [4. Model provider and Bridger](04-model-provider.md) |
| Use your existing SQL Server or MySQL database | [5. Your database](05-database.md) |
| Convert a site from start to finish | [6. End-to-end walkthrough](06-walkthrough.md) |
| Look up a command or flag | [7. Command reference](07-commands.md) |
| Run, change and deploy the generated app | [8. The generated app](08-generated-app.md) |
| Answer security / approval questions | [9. Security and network behaviour](09-security.md) |
| Fix an error | [10. Troubleshooting](10-troubleshooting.md) |
| Drive sp2react from your own Python tool | [11. Python API](11-python-api.md) |
| Know what is and is not converted | [12. Coverage and limitations](12-limitations.md) |

## The short version

```powershell
pip install "sp2react[mssql,ntlm]"
sp2react init                       # writes sp2react.yaml; edit site_url and the llm section
$env:SP_USERNAME = "CORP\me"; $env:SP_PASSWORD = "..."
$env:SP2REACT_DB_URL = "mssql+pyodbc://@db-host/SEA?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes"
sp2react doctor                     # checks SharePoint and the model
sp2react run --until spec           # extract, inventory, spec
#   review sp2react-work\specs\*.coverage.md, then for each screen:
sp2react approve <screen-id>
sp2react map-db                     # review sp2react-work\db-mapping.md
sp2react run --offline              # convert, review, test, fix
sp2react status
```
