# Architecture

sp2react is one Python package with no runtime dependencies. It reads a SharePoint site, analyses it
with plain code, asks AI agents for the parts that need judgement, and writes a React (Vite +
TypeScript) and FastAPI application from templates. The {doc}`/getting_started/how-it-works` page
describes the stages from a user's point of view; this page maps them to the code.

| Package / module | Responsibility |
|---|---|
| `pipeline.py` | The ten gated stages (inputs, extract, inventory, spec, approve_spec, convert, review, test, fix, approve) plus `map_db`, `migrate`, `reconcile`; state in `sp2react-work/state.json` |
| `transport.py`, `ntlm.py` | The only HTTP code: connections, TLS, proxies, redirects, NTLMv2 with channel binding |
| `net.py` | `NetworkPolicy`: every request and redirect hop must go to the SharePoint host or the model host |
| `sharepoint/` | Read-only REST client (GET and HEAD only; item reads blocked in `data_source: database`) and extraction to `sp2react-work/legacy/` |
| `analysis/` | ASPX parsing, a JavaScript tokenizer, the jQuery / SPServices behaviour inventory, list fields |
| `spec/` | The screen spec model, the base spec built from the inventory, the coverage gate |
| `agents/` | Prompts (`prompts/*.md`) and the validate-and-retry loop; every agent answer is checked before it is used |
| `llm/providers.py` | Bridger (Anthropic format), Anthropic, OpenAI, Azure OpenAI, and `ScriptedLLM` for tests |
| `dbmap.py`, `migrate.py` | Schema-only database reflection and the list-to-table mapping; export and reconciliation |
| `checks.py` | Builds and tests the generated app (pytest, npm, tsc, vite, rule vectors) |
| `sandbox.py`, `sandbox_guard.py`, `container/Dockerfile` | Where the generated app's own code runs: a Docker/Podman container, or an audit-hook guard on this machine; credentials never passed |
| `scaffold/` | The generated app's templates, the regeneration manifest and the hashes of released templates |
| `config.py`, `model.py`, `yamlish.py` | `sp2react.yaml`: a safe YAML subset reader and validated records |

## Trust and data flow

```text
sp2react.yaml ─► config ─► pipeline ─┬─► SharePoint (GET, policy-checked) ─► legacy/ (workspace)
                                     ├─► analysis (plain code) ─► inventory, base spec
                                     ├─► model (policy-checked) ─► agent answer ─► validation ─► spec / files
                                     ├─► database (schema only) ─► mapping
                                     └─► scaffold ─► generated app ─► checks (back-end tests in the sandbox)
```

Everything that comes from the site or the model is data until it passes a check; see
{doc}`security-assurance`.

## Rules the code keeps

- `transport.py` is the only module that opens connections; `tests/test_network.py` fails otherwise.
- No runtime dependencies; database extras are imported inside the functions that use them. The
  `zero-deps` CI job installs the package alone and runs it.
- The browser (`runtime/rules.ts`) and API (`app/rules.py`) rule engines must agree on
  `scaffold/rule_vectors.json`.
