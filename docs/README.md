# sp2react documentation

sp2react converts a classic SharePoint site (ASPX pages, list forms, jQuery and SPServices scripts) into a React + FastAPI application that reads and writes your existing database. AI agents (Claude, through GitHub Copilot Bridger by default) handle the parts that need judgement; plain code does the rest, and nothing an agent writes is accepted until it passes automatic checks.

## Start here

| If you want to... | Read |
|---|---|
| Understand what sp2react does and how | [How it works](getting_started/how-it-works.md) |
| Install it (Windows, PNC/JFrog, Linux) | [Installation](getting_started/install.md) |
| Write `sp2react.yaml` | [Configuration reference](user_guide/configuration.md) |
| Connect Claude through Bridger (or another provider) | [Model provider and Bridger](user_guide/model-provider.md) |
| Use your existing SQL Server or MySQL database | [Your database](user_guide/database.md) |
| Convert a site from start to finish | [End-to-end walkthrough](getting_started/walkthrough.md) |
| Look up a command or flag | [Command reference](reference/cli.md) |
| Run, change and deploy the generated app | [The generated app](user_guide/generated-app.md) |
| Answer security / approval questions | [Security and network behaviour](user_guide/security.md) |
| Fix an error | [Troubleshooting](user_guide/troubleshooting.md) |
| Drive sp2react from your own Python tool | [Python API](reference/api.md) |
| Know what is and is not converted | [Coverage and limitations](user_guide/limitations.md) |
| Look up the release notes | [Release notes](whatsnew/index.md) |
| Contribute, or check how sp2react is secured and released | [Development](development/index.md) |

## The short version

```powershell
pip install "sp2react[mssql]"
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
