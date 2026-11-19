# Security assurance case

Why we believe sp2react meets its security requirements: what it protects, who it trusts, what can go
wrong, and what stops it. It is reviewed before every release (see {doc}`releasing`) and whenever a
stage, agent, connection or generated-app endpoint is added.

## Security requirements (what users can expect)

1. **Business data stays where it is.** With `data_source: database` (the default), list items,
   attachments, site users, rendered pages and group membership are never read over HTTP, and prompts to
   the model contain code and schema only, never rows.
2. **The source site is not changed.** The SharePoint client sends GET and HEAD only.
3. **No surprise connections or code.** No telemetry, no update checks, no runtime dependencies; every
   request and every redirect hop goes to the SharePoint host or the model host named in the
   configuration, over TLS with certificate verification by default.
4. **Untrusted input stays data.** Page source, scripts, server answers and model output never become
   files outside the workspace or the output folder, SQL text, or accepted code without passing checks.
5. **The generated app is safe by default.** Authentication fails closed; roles, locks and validation
   are enforced by the API, not only the browser; legacy markup is rebuilt from an allow-list; files are
   served and stored only inside their folders.
6. **A trustworthy release.** What users install is what was built from the tagged commit: signed,
   reproducible, with a software bill of materials.

## Design and actors

See {doc}`architecture` for the components. Actors and what they can do:

| Actor | Trust | Can |
|---|---|---|
| Operator (writes `sp2react.yaml`, runs the CLI, approves specs and screens) | Trusted | Choose the site, model, database, credentials, output folder; approve or reject each spec and screen. |
| SharePoint site (page source, scripts, list schemas, server answers) | Data untrusted, identity verified (TLS) | Supply page markup, script, URLs, names; any site owner or editor controls page content. |
| Model (Bridger or another provider) | Identity verified (TLS); output untrusted | Return specs, code and reviews; may be steered by text in the pages it reads (prompt injection). |
| Database | Identity verified by its driver | Supply the schema (`map-db`); hold the business data the generated app serves. |
| Generated app users | Untrusted until the gateway authenticates them | Call the API and use the front end within their SharePoint roles. |
| Network between them | Untrusted | Observe or alter traffic unless TLS is used. |
| Contributors | Reviewed | Propose changes through pull requests with required checks. |
| CI and release pipeline | Trusted, constrained | Build, sign and publish from the repository only. |

## Trust boundaries

1. **Configuration → process.** The YAML subset reader refuses anchors, tags, tabs, duplicate keys and
   multiple documents; records are validated; secrets come only from environment variables.
2. **Site → process.** Everything extracted crosses here: markup, scripts, URLs, file and list names.
3. **Model → process.** Every agent answer is parsed and validated before anything is written.
4. **Process → file system.** The workspace (`sp2react-work/`), the generated app, the export folder.
5. **Process → generated app's builds and tests.** Generated code, including agent-written files, runs
   in child processes during the `test` stage.
6. **Users → generated app.** HTTP requests to the FastAPI back end and the static front end.
7. **Repository → release.** CI builds and signs; PyPI receives uploads only from the release workflow.

## Threats and countermeasures

| Threat (boundary) | Countermeasure | Evidence |
|---|---|---|
| Business data sent to the model or read over HTTP (2, 3) | Item, attachment, user, rendered-page and membership reads raise `ItemReadBlocked` in `data_source: database`; prompts are built from code and schema | `tests/test_network.py` |
| A request reaching another host, including through a redirect (2, 3) | `NetworkPolicy` checks every request and redirect hop; credentials are dropped on a cross-host redirect; only `transport.py` opens connections | `tests/test_network.py`, `tests/test_stdlib.py` |
| Changing the source site (2) | The client refuses any method but GET and HEAD | `tests/test_network.py` |
| Path traversal from page or asset URLs (`/sites/x/../../y.js`) writing outside the workspace (2→4) | `extract.inside()` refuses `..`, absolute and drive paths and checks the resolved path (symlinks included) stays under the folder; the asset is not downloaded | `tests/test_threat_model.py` |
| Path traversal from attachment names or item ids in the export (2→4) | Each segment must be a plain name; checked before the download | `tests/test_threat_model.py` |
| Agent-proposed file paths escaping the screen's folder, or overwriting build files (3→4) | `safe_target` and `path_problem`: plain relative paths inside the allowed folder only; handler names must be identifiers; screen ids are plain names | `tests/test_hardening.py`, `tests/test_threat_model.py` |
| Malformed or adversarial agent output (3) | Schema validation, the coverage gate (every behaviour carried or listed as not carried), TypeScript checks, retries with the problems, then failure | `tests/test_agents.py`; fuzz target `fuzz_spec` |
| Prompt injection: page text steering an agent to write harmful code (2→3) | Agents only write files in their screen's folder and spec rules; a separate review agent; builds and tests; the operator approves each spec before conversion and each screen before use. **Residual risk**, see below | `pipeline.py` gates |
| Agent-written code reading sp2react's credentials during the `test` stage (5) | Child processes get the environment without the configured SharePoint, model and database-URL variables | `tests/test_threat_model.py` |
| SQL injection through the generated API's `$filter`, `$orderby`, ids (6) | OData parsed into an expression tree; values bound as parameters; columns only from the mapping | generated app tests; fuzz target `fuzz_wire` |
| Script injection through legacy Content Editor markup (2→6) | Rebuilt from an allow-list of elements and attributes; `javascript:` and event handlers dropped | `tests/test_hardening.py` |
| Reading files through the static route, or writing them through attachment names (6) | The SPA route serves only files listed from `FRONTEND_DIST`; attachment names are checked | `tests/test_hardening.py` |
| Access without identity, or past roles and locks (6) | `AUTH_MODE=header` by default, failing closed; `dev` is local-only; role, lock and delete rules enforced in the API | `tests/test_hardening.py` |
| Eavesdropping or tampering in transit (network) | TLS verification on by default (`verify_ssl` may name a CA bundle); NTLMv2 with channel binding on HTTPS | `transport.py`, `ntlm.py` |
| Malformed configuration or pages crashing or hanging a run (1, 2) | Strict validation; linear-time tokenizer; fuzzed | fuzz targets `fuzz_config_yaml`, `fuzz_legacy_code` |
| Malicious or vulnerable dependency (7) | No runtime dependencies; generated app's dependencies audited (`pip-audit`, `npm audit`); CI tooling hash-locked; actions pinned by SHA; dependency review; Dependabot | `ci/`, `vulnerability-audit.yml`, `dependency-review.yml` |
| Tampered release (7) | PyPI Trusted Publishing with provenance; Sigstore-signed assets re-verified by `verify-release.yml`; reproducible builds checked in CI | `python-publish.yml`, `tests.yml` |

## Residual risks and how to reduce them

- **Prompt injection.** A page editor can write text that tries to steer an agent. Validation limits
  where agent output can go and what shape it has, but cannot prove that code which type-checks and
  passes tests does only what it should. The generated app is reviewed and approved screen by screen
  before use; treat its code like any other code change. Custom handlers (`custom/*.ts`, `custom/*.py`)
  are the place to look first.
- **Generated code runs on the conversion machine.** The `test` stage runs the generated back end's tests
  (which import agent-written Python handlers) and builds the front end. Credentials for SharePoint, the
  model and the database-URL variable are removed from their environment, but they run with the user's
  file and network access. Run sp2react in a container or a VM dedicated to the conversion, or use
  `--no-builds` and test the app elsewhere. Running these steps in a sandbox by default is on the roadmap.
- **Secrets inside page scripts.** Page source is sent to the model and kept in agent transcripts
  (`sp2react-work/agents/`). Remove secrets embedded in scripts before extraction, or treat the
  workspace as secret.

## Secure design principles applied

- **Least privilege:** read-only access to the site (GET and HEAD only); schema-only database access for
  mapping; child processes without sp2react's credentials; CI tokens read-only unless a job needs more.
- **Fail-safe defaults:** TLS verification on; `data_source: database` blocks item reads; generated app
  authentication fails closed; unknown or malformed YAML refused.
- **Complete mediation:** every request passes the network policy; every agent answer passes validation;
  every API call passes the role and lock rules on the server.
- **Economy of mechanism:** no runtime dependencies; HTTP in one module, enforced by a test.
- **Open design:** everything above is public and testable; nothing relies on obscurity.
- **Separation of privilege:** conversion needs the operator's approval at two gates; publishing needs
  the protected `release` environment and an OIDC identity, not a stored token.
- **Psychological acceptability:** each stage can be run and inspected on its own (`run --until`,
  `stage`, `status`), so safe operation is also the easy path.

## Common weaknesses considered

CWE-22 (path traversal), CWE-89 (SQL injection), CWE-79 (cross-site scripting), CWE-78 and CWE-94
(command and code injection: no shell, no `eval`, model output never executed by sp2react itself),
CWE-918 (SSRF: network policy), CWE-295 (certificate validation), CWE-306 and CWE-862 (missing
authentication or authorization in the generated app), CWE-312 and CWE-532 (cleartext or logged
secrets), CWE-400 and CWE-1333 (resource and regex DoS), CWE-494 and CWE-829 (unverified or untrusted
code), CWE-20 (input validation), CWE-1427 (prompt injection). CodeQL and `ruff`'s `S` rules scan for
these on every change; findings must be fixed or justified before merging.

## Review at release

Before each release the maintainer re-reads this page against the changes since the last release (new
inputs, new connections, new files written, new generated-app endpoints) and updates it; the release
checklist in {doc}`releasing` includes this step. The last review was for 0.1.4 (November 2026); it found
and fixed the path traversals from page, asset and attachment names and the credentials passed to the
generated app's test processes, listed above.
