# 3. Configuration reference

sp2react reads one YAML file, `sp2react.yaml` by default (`-c other.yaml` to use another). Create a starter file with:

```powershell
sp2react init            # add --force to overwrite an existing file
```

**Secrets never go in this file.** It names environment variables; sp2react reads the values from the environment when it needs them.

Relative paths (`pipeline.workspace`, `pipeline.output`, `database.mapping`) are relative to the **config file's folder**, not the folder you run the command from.

## A complete example (SQL Server, on-premises SharePoint, Bridger)

```yaml
sharepoint:
  site_url: https://app.wss-uat.example.net/sites/SEA
  auth: ntlm
  username_env: SP_USERNAME
  password_env: SP_PASSWORD
  verify_ssl: C:/certs/corp-root-ca.pem     # or true / false

llm:
  provider: bridger
  api_format: anthropic
  base_url: http://localhost:4141
  model: claude-sonnet-4                    # exact id from `sp2react doctor`
  api_key_env: BRIDGER_TOKEN                # remove if Bridger needs no token

pipeline:
  workspace: ./sp2react-work
  output: ./converted-app
  data_source: database
  max_concurrency: 4
  max_fix_iterations: 5

database:
  url_env: SP2REACT_DB_URL
  schema_name: dbo
  mapping: ./db-mapping.json

security:
  allowed_hosts: []
```

## `sharepoint`

| Key | Default | Meaning |
|---|---|---|
| `site_url` | *(required)* | Full URL of the site to convert, e.g. `https://sp.example.com/sites/SEA`. A trailing `/` is removed |
| `auth` | `ntlm` | `ntlm` (Windows authentication, needs the `ntlm` extra), `cookie`, `bearer` or `none` |
| `username_env` | `SP_USERNAME` | Environment variable holding `DOMAIN\user` (ntlm) |
| `password_env` | `SP_PASSWORD` | Environment variable holding the password (ntlm) |
| `cookie_env` | `SP_COOKIE` | Environment variable holding a cookie header copied from a signed-in browser, e.g. `FedAuth=...; rtFa=...` (cookie) |
| `token_env` | `SP_TOKEN` | Environment variable holding a bearer token (bearer) |
| `verify_ssl` | `true` | `true`, `false`, or the path to your corporate CA bundle (`.pem`). Prefer the CA bundle over `false` |
| `timeout` | `60` | Seconds per request |
| `sample_items` | `200` | Items read per list when item reads are allowed (sqlite/sharepoint modes). Not used in database mode |
| `extra_headers` | `{}` | Extra HTTP headers sent with every SharePoint request |

### Which `auth` to use

| Your SharePoint | `auth` | Set |
|---|---|---|
| On-premises, Windows sign-in (most common) | `ntlm` | `SP_USERNAME=CORP\you`, `SP_PASSWORD` |
| Behind a sign-in page (ADFS/forms) | `cookie` | `SP_COOKIE` = the `Cookie` request header from your browser's developer tools on any page of the site |
| A token from Entra ID | `bearer` | `SP_TOKEN` |
| Anonymous test site | `none` | nothing |

Setting the variables in PowerShell (current window only):

```powershell
$env:SP_USERNAME = "CORP\kbalasundaram"
$env:SP_PASSWORD = Read-Host "SharePoint password"    # typed, not stored in history
```

## `llm`

| Key | Default | Meaning |
|---|---|---|
| `provider` | `bridger` | `bridger`, `anthropic`, `openai` or `azure_openai` |
| `api_format` | `anthropic` | Bridger only. `anthropic` = Bridger serves Claude on `/v1/messages`; `openai` = on `/v1/chat/completions` |
| `base_url` | – | Bridger: `http://host:port`. Azure: `https://<resource>.openai.azure.com`. Optional for `anthropic` / `openai` |
| `model` | – | Model id exactly as the provider lists it. `sp2react doctor` prints Bridger's Claude models |
| `api_key_env` | – | Environment variable holding the key or token. Omit if Bridger needs none |
| `deployment` | – | Azure OpenAI deployment name |
| `api_version` | `2024-10-21` | Azure OpenAI API version |
| `temperature` | `0.0` | Keep at 0 for repeatable output |
| `max_tokens` | `16000` | Upper limit per model reply |
| `timeout` | `600` | Seconds per model call |
| `json_mode` | `true` | Ask for JSON output where the provider supports it |
| `extra_headers` | `{}` | Extra headers sent to the model endpoint |
| `verify_ssl` | `true` | As for SharePoint |

Details and examples for each provider: [4. Model provider and Bridger](04-model-provider.md).

## `pipeline`

| Key | Default | Meaning |
|---|---|---|
| `workspace` | `./sp2react-work` | Where extraction, inventory, specs, transcripts, test output and state are kept |
| `output` | `./converted-app` | Where the generated app is written |
| `data_source` | `database` | `database` (your existing tables), `sqlite` (sp2react migrates the items into SQLite) or `sharepoint` (the app uses the live lists). See [1. How it works](01-how-it-works.md#where-the-data-comes-from) |
| `max_concurrency` | `4` | Agent tasks run in parallel. Lower it if Bridger rate-limits you |
| `agent_retries` | `2` | How many times an agent is asked again when its output fails validation |
| `agent_timeout` | `900` | Seconds per agent task attempt |
| `max_fix_iterations` | `5` | Rounds of the fix stage before giving up |
| `auto_approve` | `false` | Skip the two human approvals. For demos and CI only |
| `run_builds` | `true` | Run `npm install`, `tsc` and `vite build` in the test stage |

## `database`

Used when `pipeline.data_source` is `database`.

| Key | Default | Meaning |
|---|---|---|
| `url_env` | `SP2REACT_DB_URL` | Environment variable holding the SQLAlchemy connection URL |
| `schema_name` | *(database default)* | Schema holding the migrated tables, e.g. `dbo` |
| `mapping` | `./db-mapping.json` | The list-to-table mapping file. `sp2react map-db` writes it; you review it |

Connection URL formats and the mapping file: [5. Your database](05-database.md).

## `security`

| Key | Default | Meaning |
|---|---|---|
| `allowed_hosts` | `[]` | Extra hosts sp2react may contact. The SharePoint host and the model host are always allowed; every other request is refused |
| `sharepoint_item_reads` | *(unset)* | Whether list items may be read from SharePoint. Unset = allowed only for `data_source: sqlite`. Set `true` in database mode only to run `reconcile` |

## Environment variables

| Variable | Read by | When |
|---|---|---|
| `SP_USERNAME`, `SP_PASSWORD` | sp2react | `auth: ntlm` (names configurable) |
| `SP_COOKIE` | sp2react | `auth: cookie` |
| `SP_TOKEN` | sp2react | `auth: bearer` |
| `BRIDGER_TOKEN` (or what `llm.api_key_env` names) | sp2react | if the model endpoint needs a key |
| `SP2REACT_DB_URL` (or what `database.url_env` names) | sp2react | `map-db`, database-mode tests |
| `DB_URL`, `DATA_SOURCE`, `MAPPING_FILE`, `AUTH_MODE`, ... | the **generated app** | at runtime; see [8. The generated app](08-generated-app.md#settings) |

To keep them for every new PowerShell window, use `[Environment]::SetEnvironmentVariable("SP2REACT_DB_URL", "...", "User")`. Do not store passwords that way on shared machines.
