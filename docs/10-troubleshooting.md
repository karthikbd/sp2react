# 10. Troubleshooting

Start with `sp2react status` and `sp2react-work/report.md`: a failed stage always says why and where to look. Add `-v` to any command for debug logging.

## Configuration

| Message | Fix |
|---|---|
| `Config file not found: sp2react.yaml` | Run `sp2react init`, or pass `-c path\to\file.yaml` |
| `Invalid config ...` | The message names the key. Check spelling and indentation (spaces, not tabs) |
| `Set the environment variable X (...)` | Set it in the same window you run sp2react in: `$env:X = "..."` |
| `No environment variable configured for ...` | The config has no `..._env` key for a secret it needs (e.g. `llm.api_key_env`) |

## SharePoint

| Message / symptom | Fix |
|---|---|
| `NTLM auth needs the extra` | `pip install "sp2react[ntlm]"` |
| `HTTP 401` | Wrong credentials, or the site does not use NTLM. Use `CORP\user` (domain, backslash, user). For ADFS or forms sign-in use `auth: cookie` |
| `HTTP 403` | Your account cannot read that page, list or library. You need at least read access to every page and script being converted |
| `SSLError` / `CERTIFICATE_VERIFY_FAILED` | Point `sharepoint.verify_ssl` at your corporate root CA (`.pem`). Export it from the browser's certificate viewer, or ask your desktop team |
| `NetworkPolicyError: Blocked request to '<host>'` | The site redirects to another host (e.g. a sign-in server or a different alias). Use that host in `site_url`, or add it to `security.allowed_hosts` |
| `sp2react only reads from SharePoint; refused POST ...` | Expected protection: something tried to write. Report it with the `-v` log |
| `ItemReadBlocked: Reading items from SharePoint is disabled` | Expected in database mode. Only set `security.sharepoint_item_reads: true` if you mean to run `reconcile` |
| A page is missing from `screens.json` | It is not a list form or in `SitePages`. Pass it with `--page /sites/SEA/<library>/<page>.aspx` |
| `manifest.json` lists errors for scripts | A script is referenced by URL but could not be read (moved, permissions, external CDN). Behaviour from it will be missing: fix access, or note it before approving the spec |

## Model / Bridger

| Message / symptom | Fix |
|---|---|
| `bridger: set llm.base_url` | Add `base_url: http://host:port` |
| `set llm.model (run sp2react doctor ...)` | Run `sp2react doctor` and copy a listed id |
| `HTTP 404` from `/v1/messages` | Bridger serves the OpenAI format: `api_format: openai` |
| `HTTP 401` / `403` | Token missing or wrong (`llm.api_key_env`) |
| `HTTP 429`, slow runs | Rate limiting. Lower `pipeline.max_concurrency` |
| `agent output kept failing validation; see <transcript>` | Open the transcript in `sp2react-work/agents/<agent>/`. The last validation problems say what the agent could not get right. Usually the source is ambiguous or incomplete; fix the source or raise `pipeline.agent_retries` and run the stage again |
| `timed out after N s per attempt` | Raise `pipeline.agent_timeout` or `llm.timeout` |

## Database

| Message / symptom | Fix |
|---|---|
| `map-db needs SQLAlchemy and your driver` | `pip install "sp2react[mssql]"` (or `[mysql]`) |
| `Data source name not found and no default driver specified` | The ODBC driver name in the URL is not installed. Check *ODBC Data Sources (64-bit) → Drivers* and use that exact name (`ODBC+Driver+17+for+SQL+Server` etc.) |
| `Login failed for user` | Wrong credentials, or Windows authentication not allowed. Try a SQL login, or check `trusted_connection=yes` |
| `SSL Provider: certificate chain was issued by an authority that is not trusted` | Add `&TrustServerCertificate=yes`, or install the server's CA |
| `map-db` finds no tables | Wrong database or schema: set `database.schema_name`. `map-db` looks at tables, not views |
| `Mapping needs attention` | Read the problems in `db-mapping.md`, edit `db-mapping.json`, re-run `map-db` |
| `convert` failed: `data_source=database needs a reviewed list->table mapping` | Run `sp2react map-db` until it says **Mapping ready** |
| Insert fails: `Cannot insert NULL into column` | A `NOT NULL` column has no mapping and no default. Map it, or give it a default in the database |
| Insert fails: `cannot have any enabled triggers if the statement contains an OUTPUT clause` | See [SQL Server notes](05-database.md#sql-server-notes) |
| Update fails on the version column | It is a `rowversion` column. Remove `version` from `system` in the mapping |

## Convert, test, fix

| Message / symptom | Fix |
|---|---|
| `convert`: `waiting for spec approval` | Approve the spec: `sp2react approve <screen>` |
| `npm not found on PATH` | Install Node.js 20+, or use `--no-builds` |
| `npm install` fails | Registry access: `npm config set registry <your Artifactory npm remote>` |
| `fix` failed: `failures are in shared scaffold code or the environment` | The failing code is not agent-owned, so no agent may change it. Read `tests/iteration-N.md`; it is usually the environment (Node version, a missing driver) |
| `fix` failed: `still failing after N iteration(s)` | Read the last `tests/iteration-N.md`. Raise `max_fix_iterations`, or fix the spec and re-convert |
| `test` failed: `data reconciliation failed` | Only with item reads on. See `reconciliation.md`; fix the mapping or the migrated data |

## The generated app

| Symptom | Fix |
|---|---|
| The API ignores `.env` | Start it with `uvicorn app.main:app --env-file .env`, or set the variables in the environment |
| `KeyError: 'DB_URL'` at startup | Set `DB_URL` (database mode) |
| "Your account does not have access to this site." | The signed-in login is not in the users table (or `data/roles.json` for roles). Check the login format matches (`CORP\user` vs `user@corp.com`) |
| Fields that should be editable are read-only | Role rules: check the user's groups (`GET /api/me`) against the spec's role conditions |
| `412` on save | Someone else changed the item since it was opened; reload |
| Browser shows CORS errors | Add the UI's origin to `CORS_ORIGINS` |

## Getting help

Open an issue at https://github.com/karthikbd/sp2react/issues with:
- `sp2react --version`;
- the command, and the output with `-v`;
- the relevant part of `report.md`, `tests/iteration-N.md` or the agent transcript.

Remove site content, hostnames and credentials before posting.
