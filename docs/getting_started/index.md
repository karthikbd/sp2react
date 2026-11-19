# Getting started

```{toctree}
:maxdepth: 1

how-it-works
install
walkthrough
```

## In one minute

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

::::{grid} 1 3 3 3
:gutter: 2

:::{grid-item-card} How it works
:link: how-it-works
:link-type: doc
The stages, the agents, where the data comes from.
:::

:::{grid-item-card} Installation
:link: install
:link-type: doc
PyPI, Windows, corporate repositories, offline wheels, Node.js.
:::

:::{grid-item-card} End-to-end walkthrough
:link: walkthrough
:link-type: doc
A site from start to a deployed app.
:::
::::
