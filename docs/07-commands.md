# 7. Command reference

```
sp2react [-c CONFIG] [-v] [--version] <command> [options]
```

| Global option | Meaning |
|---|---|
| `-c`, `--config FILE` | Config file to use. Default: `sp2react.yaml` in the current folder |
| `-v`, `--verbose` | Debug logging (every request and agent call) |
| `--version` | Print the version and exit |

Exit codes: `0` success, `1` refused (for example approving a spec that is not done), `2` configuration problem or a failed `doctor` check.

Every command that changes state rewrites `sp2react-work/report.md`.

---

## `init`

Write a starter `sp2react.yaml`.

```
sp2react init [--force]
```

| Option | Meaning |
|---|---|
| `--force` | Overwrite an existing file |

## `doctor`

Check the SharePoint connection and the model provider. Lists the provider's models (Claude models are highlighted) and makes a one-line test call.

```
sp2react doctor
```

## `run`

Run every stage in order, stopping at the next approval gate or at `--until`.

```
sp2react run [--page URL]... [--offline] [--until STAGE] [--auto-approve] [--no-builds]
```

| Option | Meaning |
|---|---|
| `--page URL` | Only these pages (repeatable). Server-relative (`/sites/SEA/SitePages/Dashboard.aspx`) or site-relative (`SitePages/Dashboard.aspx`). Default: every list's forms plus every `.aspx` in `SitePages` |
| `--offline` | Reuse the extraction already in the workspace; do not contact SharePoint |
| `--until STAGE` | Stop after this stage: `inputs`, `extract`, `inventory`, `spec`, `approve_spec`, `convert`, `review`, `test`, `fix`, `approve` (default `approve`) |
| `--auto-approve` | Skip both human approvals. For demos and CI only |
| `--no-builds` | Skip `npm install`, `tsc` and `vite build` in the test stage |

Screens that are not approved stop at `approve_spec`; the others continue. In database mode, `run` also runs `map-db` once specs are approved.

Typical use:

```powershell
sp2react run --until inventory           # see what was found
sp2react run --until spec --offline      # specs
sp2react approve <screen>                # for each screen
sp2react run --offline                   # map-db, convert, review, test, fix
```

## Single stages

Each of these runs one stage. They accept `--page` (limit to pages) and `--screen ID` (limit to screens, repeatable), and `--no-builds`.

| Command | Does | Needs |
|---|---|---|
| `extract` | connects and reads the site (GET only) into `sp2react-work/legacy/` | config, SharePoint access |
| `inventory` | groups pages into screens, finds behaviours: `screens.json`, `inventory/` | extraction |
| `spec` | builds and checks specs: `specs/<screen>.json`, `.coverage.md` | inventory, model |
| `map-db` | drafts and validates `db-mapping.json`, writes `db-mapping.md` | at least one spec; database URL |
| `convert` | generates `converted-app/` for approved screens | approved specs; in database mode a valid mapping |
| `review` | independent agent review: `reviews/<screen>.json` | convert done |
| `test` | runs tests and the fix loop | review done |
| `migrate` | `data_source: sqlite` only: exports every list item and attachment and regenerates the app with the data | item reads allowed |
| `reconcile` | compares the SharePoint lists with the app's data field by field: `reconciliation.md` | generated app; item reads allowed |

Examples:

```powershell
sp2react spec --screen VendorRequests-form        # redo one screen's spec
sp2react convert --screen Dashboard
sp2react test --screen Dashboard --no-builds
sp2react map-db
```

## `approve`

Record a human approval.

```
sp2react approve SCREEN_ID [--screen] [--by NAME]
```

| Option | Meaning |
|---|---|
| `SCREEN_ID` | Screen id as shown by `status` (e.g. `VendorRequests-form`, `Dashboard`) |
| *(no flag)* | Approve the **spec**. Refused unless the spec stage is done |
| `--screen` | Approve the **finished screen**. Refused unless tests passed |
| `--by NAME` | Name recorded with the approval in `approvals.json` |

## `status`

Show every screen's stage status.

```
sp2react status [--json]
```

| Option | Meaning |
|---|---|
| `--json` | Print the full state (`sp2react-work/state.json`) |

Status values: `running`, `done`, `failed`, `skipped`, `warning`, and `waiting` (for your approval; the text says which command to run). The text after each status explains it (counts, the reason for a failure, or where to look).

## Files written

| Path | Written by | Contents |
|---|---|---|
| `sp2react.yaml` | `init` | configuration |
| `db-mapping.json` | `map-db` | list-to-table mapping (you review and may edit) |
| `sp2react-work/state.json` | all | stage status per screen |
| `sp2react-work/report.md` | all | human-readable run report |
| `sp2react-work/legacy/` | extract | page source, web parts, scripts, CSS, list schemas, `manifest.json` |
| `sp2react-work/screens.json` | inventory | screens and their pages |
| `sp2react-work/inventory/<screen>.json` | inventory | behaviours and data calls with file:line |
| `sp2react-work/specs/<screen>.json` | spec | the spec |
| `sp2react-work/specs/<screen>.coverage.md` | spec | coverage report to review |
| `sp2react-work/approvals.json` | approve | who approved what, when |
| `sp2react-work/db-schema.json` | map-db | the database schema that was read |
| `sp2react-work/db-mapping.md` | map-db | mapping report to review |
| `sp2react-work/agents/<agent>/` | every agent | prompts, replies and validation results |
| `sp2react-work/reviews/<screen>.json` | review | review findings |
| `sp2react-work/tests/iteration-N.md` | test, fix | test and build output per round |
| `sp2react-work/data-export/` | migrate, reconcile | exported list items (only when item reads are allowed) |
| `sp2react-work/reconciliation.md` | reconcile | field-by-field comparison |
| `converted-app/` | convert | the generated application |
