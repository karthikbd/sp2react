# 6. End-to-end walkthrough

This walks through converting a real site from start to finish: a sanctions dashboard on on-premises SharePoint, whose list data has already been migrated to SQL Server. Replace names and URLs with yours.

Total hands-on time for a first screen is about an hour, most of it reviewing. Model time depends on the number of screens and Bridger's speed.

```
prepare ─► doctor ─► extract + inventory ─► spec ─► YOU approve specs ─► map-db ─► YOU review mapping
        ─► convert ─► review ─► test ─► fix ─► run the app ─► YOU approve screens ─► deploy
```

## Step 0. Prepare a project folder

```powershell
mkdir F:\projects\sea-migration; cd F:\projects\sea-migration
py -3.11 -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install "sp2react[mssql,ntlm]"
sp2react init
git init       # recommended: keep the config, mapping and generated app under version control
```

Add a `.gitignore` with `sp2react-work/legacy/`, `.venv/` and `converted-app/frontend/node_modules/`. The workspace holds the site's page source and scripts; decide with your team whether it may be committed.

Edit `sp2react.yaml` ([full reference](03-configuration.md)):

```yaml
sharepoint:
  site_url: https://app.wss-uat.example.net/sites/SEA
  auth: ntlm
  verify_ssl: C:/certs/corp-root-ca.pem
llm:
  provider: bridger
  api_format: anthropic
  base_url: http://localhost:4141
  model: claude-sonnet-4
pipeline:
  data_source: database
database:
  schema_name: dbo
```

Set the secrets for this PowerShell window:

```powershell
$env:SP_USERNAME = "CORP\you"
$env:SP_PASSWORD = Read-Host "SharePoint password"
$env:SP2REACT_DB_URL = "mssql+pyodbc://@sql-uat-host/SEA?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes"
# $env:BRIDGER_TOKEN = "..."   # only if Bridger needs one
```

## Step 1. Check connections

```powershell
sp2react doctor
```

Both lines must say OK. Put the exact Claude model id it lists into `llm.model`. If something fails, see [10. Troubleshooting](10-troubleshooting.md).

## Step 2. Extract and inventory: see what the site contains

```powershell
sp2react run --until inventory
```

What happens:
- **extract** reads, with GET requests only: the site, every list's schema, views and form pages, the `.aspx` pages in `SitePages`, web parts, Script Editor and Content Editor content, linked custom scripts and CSS, group names and navigation. In database mode no list items, people or group members are read.
- **inventory** groups pages into screens and lists every behaviour in their scripts.

Look at:

| File | What to check |
|---|---|
| `sp2react-work/legacy/manifest.json` | every file fetched, and `errors` (pages or scripts that could not be read, with the reason) |
| `sp2react-work/screens.json` | the screens found: one `<List>-form` per list with forms, one screen per other page |
| `sp2react-work/inventory/<screen>.json` | each behaviour (show/hide, required, read-only, default, cascade, validation message, role check, redirect, REST or SPServices call) with file and line, and anything **unresolved** |
| `sp2react-work/report.md` | the summary per screen |

**Pages outside `SitePages`.** Without `--page`, sp2react takes every list's forms and every `.aspx` in `SitePages`. If dashboard pages live elsewhere (a `Pages` library, `SiteAssets`, a subsite), name them:

```powershell
sp2react run --until inventory --page /sites/SEA/Pages/Dashboard.aspx --page /sites/SEA/SiteAssets/Alerts.aspx
```

**Work in batches.** For a large site, convert one menu area at a time by passing its pages with `--page`. Everything else in this walkthrough works the same.

## Step 3. Specs

```powershell
sp2react run --until spec --offline
```

`--offline` reuses the extraction from step 2. For each screen, code builds the base spec from the list schema (fields, types, required, choices, lookups) and the **spec agent** adds the rules that need interpretation from the scripts. The coverage gate then checks that every required behaviour is covered and every legacy message is quoted exactly. If it is not, the agent is told what is missing and tries again.

`sp2react status` shows each screen's spec as `done` or `failed`.

## Step 4. Review and approve each spec (you)

Open `sp2react-work/specs/<screen>.coverage.md`. It has:

1. **Coverage table:** every legacy behaviour (with its code) and the rule that carries it. Nothing may say **missing**.
2. **Rules:** every rule in plain form, e.g. `required HighRiskJustification when={"RiskRating": "High"} "Justification is required for high-risk vendors."`.
3. **Not carried:** behaviours deliberately dropped, each with a reason (e.g. a SharePoint-only ribbon tweak).
4. **Open questions:** where the agent was unsure. Answer them before approving.

Compare it with how the screen behaves in SharePoint today. If it is right:

```powershell
sp2react approve VendorRequests-form --by "Karthikeyan"
sp2react approve Dashboard --by "Karthikeyan"
```

If a spec is wrong, the cause is usually in the source the agent saw (a script that failed to load, see `manifest.json`) or in an open question. Fix the input and re-run `sp2react spec --screen <id>`. If the source changes later, the spec is regenerated and the approval is withdrawn automatically.

## Step 5. Map the database (you review)

```powershell
sp2react map-db
```

It reads the database **schema** only, drafts the mapping of lists to tables and fields to columns, asks the dbmap agent about anything unresolved, and validates the result. Review `sp2react-work/db-mapping.md` with the [checklist](05-database.md#review-checklist). Edit `db-mapping.json` (next to `sp2react.yaml`) if needed and re-run `sp2react map-db` until it says **Mapping ready**.

Fill in group members in `converted-app/backend/data/roles.json` later (step 7) unless the mapping has a groups table.

## Step 6. Convert, review, test, fix

```powershell
sp2react run --offline
```

For every approved screen:
- **convert** writes the app into `converted-app/`. List forms need no agent: the shared form engine renders them from the spec. Pages (dashboards) and custom handlers are written by agents, in parallel, and each file is checked: allowed imports only, no `fetch`/jQuery/`innerHTML`, legacy texts present, and it must type-check.
- **review**: an independent agent compares the new screen with the legacy source and lists findings.
- **test** runs the generated API tests, the shared rule vectors (browser and API engines must agree), `tsc` and `vite build`.
- **fix**: if something fails, the fix agent gets the real compiler and test output and edits only the files agents own; then test runs again, up to `max_fix_iterations` times.

Check progress:

```powershell
sp2react status
```
```
inputs     done      offline: using the existing extraction
extract    done      offline: skipped

VendorRequests-form
  inventory     done      2 custom scripts, 33 behaviours to carry, 6 data calls, 0 unresolved
  spec          done      33/33 required behaviours covered ...
  approve_spec  done      approved Karthikeyan
  convert       done      scaffold only (form engine renders this screen from the spec)
  review        done      verdict pass, 0 blocking finding(s), 0 total
  test          done      backend tests (generated API tests + rule vectors): ok
```

Details are in `sp2react-work/report.md`, `reviews/<screen>.json` and `tests/iteration-N.md`.

## Step 7. Run the app and compare with SharePoint

```powershell
# API
cd converted-app\backend
pip install -r requirements.txt pyodbc
copy .env.example .env      # then set DB_URL to your connection string and DATA_SOURCE=database
uvicorn app.main:app --env-file .env --reload --port 8000

# UI, in a second window
cd converted-app\frontend
npm install
npm run dev                 # http://localhost:5173
```

With `npm run dev` and `AUTH_MODE=dev`, the page header has an "Acting as" user switcher, so you can act as any user (it never appears in a production build). Use it to check role-dependent behaviour (a reviewer sees fields a requester does not).

Old SharePoint URLs keep working: `/sites/SEA/Lists/VendorRequests/NewForm.aspx` redirects to the new route.

Open the same screen in SharePoint and in the new app side by side and try:
- new / edit / display for each list form;
- each validation message (leave required fields empty, enter invalid values);
- cascading dropdowns and fields that show or hide;
- each role;
- dashboard tiles and tables against the same data.

## Step 8. Approve the screens (you)

```powershell
sp2react approve VendorRequests-form --screen --by "Karthikeyan"
```

A screen can be approved only after its tests pass.

## Step 9. Deploy

See [8. The generated app → Deploying](08-generated-app.md#deploying). Before production, switch `AUTH_MODE` to `header` behind your authenticating gateway, or replace `app/auth.py` with Entra ID token validation.

## When the site changes

Re-run from the top. Unchanged screens are skipped by the spec stage; changed ones get a new spec and need approval again. `db-mapping.json` keeps your edits. `convert` rewrites the scaffold, so keep custom changes where [8. The generated app](08-generated-app.md#changing-the-app) says.
