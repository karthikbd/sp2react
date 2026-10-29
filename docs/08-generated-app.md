# 8. The generated app

`converted-app/` is a normal React + FastAPI project. Nothing in it depends on sp2react at runtime.

## Layout

```
converted-app/
├─ backend/                      FastAPI
│  ├─ app/
│  │  ├─ main.py                 creates the app, picks the data source, serves the built front end
│  │  ├─ api.py                  REST endpoints (lists, items, lookups, attachments, current user)
│  │  ├─ rules.py                the rule engine: enforces the spec on every write
│  │  ├─ sql_repo.py             DATA_SOURCE=database: your tables through mapping.json
│  │  ├─ store.py                DATA_SOURCE=sqlite: local SQLite store
│  │  ├─ sp_repo.py              DATA_SOURCE=sharepoint: live lists over REST
│  │  ├─ odata.py                $filter / $orderby parsing
│  │  ├─ auth.py                 who is calling; SharePoint groups become roles
│  │  └─ custom/                 agent-written server handlers (custom rules)
│  ├─ specs/<screen>.json        the approved specs (the app's behaviour)
│  ├─ mapping.json              copy of db-mapping.json (database mode)
│  ├─ data/roles.json            group members when there is no groups table
│  ├─ tests/                    generated API tests + rule vector tests
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend/                     React 18, Vite, TypeScript, react-router
│  ├─ src/
│  │  ├─ runtime/rules.ts        the same rule engine as rules.py, for the browser
│  │  ├─ components/sp/          SharePoint-look form engine, list views, tiles, layout
│  │  ├─ screens/ListFormScreen.tsx   renders any list form from its spec
│  │  ├─ screens/<Page>/         agent-written page components (dashboards etc.)
│  │  ├─ screens/LegacyRedirect.tsx   old .aspx URLs -> new routes
│  │  ├─ custom/                 agent-written browser handlers (custom rules)
│  │  ├─ specs/<screen>.json     same specs as the back end
│  │  └─ styles/legacy.css       the site's own CSS, carried over
│  └─ package.json
└─ shared/rule_vectors.json      cases both rule engines must agree on
```

## Running locally

```powershell
# back end
cd converted-app\backend
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt pyodbc          # pymysql for MySQL
copy .env.example .env                           # edit: DATA_SOURCE, DB_URL, ...
uvicorn app.main:app --env-file .env --reload --port 8000
# API docs: http://localhost:8000/docs

# front end (second window)
cd converted-app\frontend
npm install
npm run dev                                      # http://localhost:5173, /api is proxied to :8000
```

## Settings

The back end reads environment variables (or `--env-file .env` with uvicorn).

| Variable | Default | Meaning |
|---|---|---|
| `DATA_SOURCE` | as generated | `database`, `sqlite` or `sharepoint` |
| `DB_URL` | – | SQLAlchemy URL of your database (same format as `SP2REACT_DB_URL`) |
| `MAPPING_FILE` | `./mapping.json` | list-to-table mapping |
| `DB_SCHEMA` | from the mapping | schema, if not in the mapping |
| `AUTH_MODE` | `dev` | `dev` (local only) or `header` |
| `IDENTITY_HEADER` | `X-MS-CLIENT-PRINCIPAL-NAME` | header carrying the signed-in login when `AUTH_MODE=header` |
| `DEV_USER` | first user | default user in `dev` mode |
| `CORS_ORIGINS` | `http://localhost:5173` | comma-separated origins allowed to call the API |
| `FRONTEND_DIST` | `../frontend/dist` | built front end to serve; if present, the API serves the UI too |
| `SPEC_DIR`, `DATA_DIR` | `specs/`, `data/` | where specs and data files are read from |
| `DB_PATH` | `data/app.db` | `DATA_SOURCE=sqlite` only |
| `SP_SITE_URL`, `SP_AUTH`, `SP_USERNAME`, `SP_PASSWORD`, `SP_COOKIE`, `SP_TOKEN`, `SP_VERIFY_SSL` | – | `DATA_SOURCE=sharepoint` only |

## Users and roles

SharePoint groups become roles with the same names, so rules such as "only Compliance Reviewers may edit Status" keep working unchanged.

- **`AUTH_MODE=dev`**: the caller is chosen by an `X-User` header, the `DEV_USER` variable, or the "Acting as" switcher shown in `npm run dev`. Local testing only.
- **`AUTH_MODE=header`**: the login comes from `IDENTITY_HEADER`, set by an authenticating gateway in front of the API (for example Azure App Service authentication, or a reverse proxy doing Windows authentication). Never expose the API directly in this mode.
- **Entra ID**: replace `current_user()` in `app/auth.py` with token validation (e.g. `fastapi-azure-auth` or MSAL).

The user is looked up in the mapped users table (database mode). Their roles come from the mapped groups table, or from `data/roles.json`. A user who is not found gets "Your account does not have access to this site."

## API

| Method and path | Purpose |
|---|---|
| `GET /api/me` | current user and roles |
| `GET /api/users?search=` | people picker search |
| `GET /api/screens`, `GET /api/specs/{screen}` | screens and their specs |
| `GET /api/lists/{list}/items` | query items: `$filter`, `$orderby`, `$top`, `$skip`, `$select` |
| `GET /api/lists/{list}/items/{id}` | one item (with its version for concurrency) |
| `GET /api/lists/{list}/items/{id}/state` | what the current user may do with the item (locks, read-only) |
| `POST /api/lists/{list}/items` | create; rules enforced; `422` with field messages when invalid |
| `PATCH /api/lists/{list}/items/{id}` | update; `412` on a concurrent change, `423` when the item is locked |
| `DELETE /api/lists/{list}/items/{id}` | delete |
| `GET /api/lists/{list}/lookup/{field}` | options for a lookup or choice field (respects cascades) |
| `GET /api/lists/{list}/unique/{field}` | duplicate check for unique-value rules |
| `GET/POST/DELETE /api/lists/{list}/items/{id}/attachments[/{name}]` | attachments |
| `/api/custom/...` | routes added by custom server handlers |

Full, live documentation: `http://localhost:8000/docs`.

## Tests

```powershell
cd converted-app\backend
$env:DB_URL = "..."; python -m pytest tests -q      # database-mode API tests skip without DB_URL
cd ..\frontend
npm run typecheck
node scripts/check-rules.ts                        # browser rule engine vs shared/rule_vectors.json (Node 23.6+; on Node 22 add --experimental-strip-types)
```

Database-mode API tests **write test items** to the tables. Point `DB_URL` at a test copy of the database, never at production.

## Changing the app

While you are still converting, sp2react owns the generated code: `convert` rewrites the scaffold every time, and agent-written files (`screens/<Page>/`, `custom/`) can be rewritten when a screen is converted again. During that phase:

- **change behaviour through the spec**, by fixing the source or answering the spec's open questions and re-running `spec`, then `convert`;
- **change data access through `db-mapping.json`** (next to `sp2react.yaml`), then re-run `map-db` and `convert`. `backend/mapping.json` is a copy and is replaced on every `convert`;
- `backend/data/roles.json` is created once and **kept** on later runs, so group members you fill in there survive;
- keep `converted-app/` in git and review the diff after every `convert`.

Once screens are approved and you stop running `convert`, `converted-app/` is an ordinary codebase: change it like any other project.

## Deploying

1. Build the front end:
   ```powershell
   cd converted-app\frontend; npm ci; npm run build      # writes frontend\dist
   ```
2. Install the back end on the server with its driver (`pip install -r requirements.txt pyodbc`), and make sure the ODBC driver is installed there too.
3. Set the variables: `DATA_SOURCE=database`, `DB_URL`, `MAPPING_FILE`, `AUTH_MODE=header`, `IDENTITY_HEADER`, `CORS_ORIGINS` (the site's own origin), and `FRONTEND_DIST` if `dist` is elsewhere.
4. Run the API without `--reload`, with workers, behind your web server or gateway:
   ```
   uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
   ```
   If `frontend/dist` exists, the same process serves the UI, so one URL serves both.
5. Put an authenticating reverse proxy in front (IIS, nginx, Azure App Service, or your platform's gateway) that sets the identity header and blocks direct access to the API port.
6. Point the old SharePoint URLs at the new host if you want bookmarks to keep working: the app redirects `.../Lists/<List>/NewForm.aspx`, `EditForm.aspx?ID=`, `DispForm.aspx?ID=` and converted page URLs to the new routes.

Container, Windows service and IIS setups all work; the app is a standard ASGI application.
