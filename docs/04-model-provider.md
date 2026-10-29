# 4. Model provider and Bridger

sp2react uses one model for all of its agents (spec, page, handler, review, fix, dbmap). The default is **Claude through GitHub Copilot Bridger**. Anthropic's API, OpenAI and Azure OpenAI also work.

## Bridger (default)

Bridger exposes your GitHub Copilot models as an HTTP API on a host and port, typically on your own machine (`http://localhost:4141`) or on a shared internal host. It can serve Claude in one of two wire formats; sp2react supports both.

### 1. Find Bridger's address and format

Ask whoever runs Bridger, or check its startup output, for:
- the base URL, e.g. `http://localhost:4141`;
- whether it needs a token;
- which API it serves: Anthropic Messages (`/v1/messages`) or OpenAI Chat Completions (`/v1/chat/completions`).

### 2. Configure

```yaml
llm:
  provider: bridger
  api_format: anthropic           # or openai
  base_url: http://localhost:4141
  model: claude-sonnet-4          # replace with an id from step 3
  api_key_env: BRIDGER_TOKEN      # delete this line if Bridger needs no token
```

```powershell
$env:BRIDGER_TOKEN = "..."        # only if needed
```

With `api_format: anthropic`, the token is sent both as `x-api-key` and as `Authorization: Bearer`, so either style of Bridger accepts it.

### 3. Pick the model with `doctor`

```powershell
sp2react doctor
```

```
SharePoint: OK - 'Sanctions Dashboard' (/sites/SEA)
Model provider (bridger): OK - 14 model(s); Claude: claude-sonnet-4, claude-opus-4, ...
Model call: OK - claude-sonnet-4 replied 'ready'
```

Copy one of the listed Claude ids into `llm.model` exactly. If `doctor` warns that the configured model is not in the provider's list, the id is wrong. Use the strongest Claude model Bridger offers; spec and page agents benefit most from it.

### If it fails

| Symptom | Fix |
|---|---|
| `HTTP 404` on `/v1/messages` | Bridger serves the OpenAI format: set `api_format: openai` |
| `HTTP 401` / `403` | token missing or wrong: check `api_key_env` and the variable's value |
| `HTTP 429` | rate limited. sp2react already retries (5 attempts, honouring `Retry-After`); lower `pipeline.max_concurrency` to 1 or 2 |
| `NetworkPolicyError` | `base_url` host differs from the host Bridger redirects to; add that host to `security.allowed_hosts` |
| Replies are cut off | raise `llm.max_tokens`, or check whether Bridger caps output |

## Anthropic API

```yaml
llm:
  provider: anthropic
  model: claude-sonnet-5-5
  api_key_env: ANTHROPIC_API_KEY
```

## Azure OpenAI

```yaml
llm:
  provider: azure_openai
  base_url: https://<resource>.openai.azure.com
  deployment: <deployment-name>
  api_key_env: AZURE_OPENAI_API_KEY
  api_version: 2024-10-21
```

## OpenAI

```yaml
llm:
  provider: openai
  base_url: https://api.openai.com/v1
  model: <model id>
  api_key_env: OPENAI_API_KEY
```

## How agents are kept honest

Every agent task follows the same loop:

1. sp2react builds the prompt from the extracted source and the current spec or code.
2. The agent replies.
3. sp2react validates the reply. For example:
   - a spec must cover every required behaviour and quote legacy messages exactly;
   - a page component may import only allowed modules, must not use `fetch`, jQuery or `innerHTML`, and must compile;
   - a mapping must point at tables and columns that exist.
4. If validation fails, the agent gets the exact list of problems and tries again, up to `pipeline.agent_retries` times. If it still fails, the stage is marked failed and the transcript is kept.

Transcripts of every call (prompt, reply, validation result) are in `sp2react-work/agents/<agent>/`. The run report shows the number of calls and tokens per stage.
