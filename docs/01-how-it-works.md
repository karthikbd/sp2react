# 1. How it works

## What goes in, what comes out

**In:**
- the URL of a classic SharePoint site (2013, 2016, 2019 or Subscription Edition, on-premises);
- a Claude model through GitHub Copilot Bridger (or another provider);
- in the default mode, your existing database that already holds the migrated list data.

**Out:**
- `converted-app/`: a React (Vite + TypeScript) front end and a FastAPI back end that reproduce the site's list forms and pages and read and write your database;
- `sp2react-work/`: everything sp2react learned and decided along the way (extracted source, behaviour inventory, specs, coverage reports, agent transcripts, test results, a run report), so every step can be reviewed.

## The idea

A classic SharePoint form is a list (the data), a New/Edit/Display form page, and jQuery or SPServices code that hides fields, sets defaults, cascades dropdowns, validates on save and calls REST. sp2react does not translate that jQuery line by line. It:

1. finds every behaviour in the scripts and records where it is (file and line);
2. writes each behaviour down as a rule in a **spec**, a JSON description of the screen (fields, rules, messages, roles);
3. renders forms from the spec with one shared form engine, and enforces the same rules in the API;
4. proves the result: every behaviour must be covered by a rule, legacy messages must appear word for word, the browser and API rule engines must agree on shared test vectors, and the app must compile and pass its generated tests.

Plain code does everything that can be done deterministically. AI agents are used only where judgement is needed, and their output is validated before it is accepted; if it fails validation the agent is told exactly what was wrong and asked again.

## The stages

Each screen moves through ten stages. A stage starts only when the one before it is done, and two of them wait for a person.

| # | Stage | Done by | What happens | Output in `sp2react-work/` |
|---|---|---|---|---|
| 1 | inputs | code | loads the config, checks the connection | `state.json` |
| 2 | extract | code | reads the site over REST, GET only: page source (`.aspx`), web parts added in the browser, Script Editor and Content Editor content, JSLink, custom JS and CSS, list schemas, views, forms, SharePoint group names, navigation | `legacy/` (+ `manifest.json` listing every file fetched and every error) |
| 3 | inventory | code | groups each list's New/Edit/Display forms into one **screen**, every other page into its own screen; finds every jQuery/SPServices behaviour and data call with file:line | `screens.json`, `inventory/<screen>.json` |
| 4 | spec | code + **spec agent** | code builds the base spec from the list schema; the agent adds the rules that need interpretation | `specs/<screen>.json`, `specs/<screen>.coverage.md` |
| 5 | approve_spec | **you** | you read the coverage report and approve | `approvals.json` |
| – | map_db | code + **dbmap agent** | database mode only: maps lists to tables and fields to columns from the database schema | `db-mapping.json` (next to your config), `db-mapping.md`, `db-schema.json` |
| 6 | convert | code + **page agents** | writes the app scaffold; list forms are rendered by the shared form engine; agents write page components and custom handlers, in parallel | `converted-app/` |
| 7 | review | **review agent** | an independent agent compares the result with the legacy source | `reviews/<screen>.json` |
| 8 | test | code | generated API tests, rule vectors, `tsc` and `vite build`, data reconciliation when enabled | `tests/iteration-N.md` |
| 9 | fix | **fix agent** | gets the real compiler and test output and edits only the files agents own; repeats up to `max_fix_iterations` | `tests/iteration-N.md` |
| 10 | approve | **you** | you check the screen and approve it | `approvals.json` |

`report.md` in the workspace always shows where every screen is.

## Where the data comes from

`pipeline.data_source` decides what the generated app talks to:

| Value | The app reads and writes | sp2react reads list items over HTTP? |
|---|---|---|
| `database` (default) | your existing tables (SQL Server, MySQL, PostgreSQL), through a reviewed list-to-table mapping | **No.** Only schemas, page source and scripts are read |
| `sqlite` | a SQLite copy that sp2react fills by exporting every list item and attachment | Yes |
| `sharepoint` | the live SharePoint lists | Yes, at runtime, by the generated app |

Use `database` when the data has already been migrated. See [5. Your database](05-database.md).

## What the agents see

Agents receive page source, scripts, list schemas, the inventory, and the draft spec or code they are working on. In database mode they never receive list items; the dbmap agent receives table and column names and types only. See [9. Security](09-security.md).

## Re-running

The workspace remembers everything:

- `--offline` reuses the extraction instead of reading SharePoint again.
- The spec stage skips a screen whose inventory has not changed. If the source changed, the spec is regenerated and its approval is withdrawn.
- `map-db` keeps a mapping file you already reviewed and only adds lists that are missing from it.
- `convert` rewrites the scaffold files in `converted-app/` every time. Keep your own changes in the places described in [8. The generated app](08-generated-app.md#changing-the-app), and keep `converted-app/` in git.
