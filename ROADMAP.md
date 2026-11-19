# Roadmap

What we plan for the next 12 months (December 2026 to November 2027). Plans change; issues and pull
requests that move these forward are welcome, and each item will get its own issue when work starts.

## Project health

- **A second maintainer** (ideally from another organization), so changes get a second reviewer, releases
  don't depend on one person, and the project can reach the OpenSSF Best Practices **gold** level and
  **baseline level 3** (non-author approval on every merge).
- **Coverage**: raise statement coverage from about 85% to 90% and branch coverage from about 76% to
  80% (gold levels); the command-line module and the model providers are the least covered today.
- **Copyright and SPDX license lines** in every source file.
- Mark issues suitable for new contributors with the `good first issue` label.

## Conversion

- **Site-wide assessment**: one command that walks Site Contents (subsites, lists and libraries, content
  types, workflows, event receivers, InfoPath forms) and writes a per-page conversion readiness report.
- **Buttons and commands**: inventory of ribbon actions, custom buttons and `onclick` handlers, mapped to
  spec actions.
- **Views**: filters and grouping, and a richer grid (sort, search, select, export).
- **Dialogs**: `SP.UI.ModalDialog` pages to React dialogs.
- **Branding**: capture of master-page branding into the generated app's theme.
- **Document libraries** as screens.
- **Compare view**: SharePoint and the generated screen side by side.

## Generated application

- **GraphQL API** as an option next to the REST (FastAPI) API, chosen per project.
- **Material UI** components as an option for the generated front end.
- **Reusable conversion skills**: a library of written conversion patterns the agents follow, so common
  SharePoint idioms convert the same way every time.
- **Agents through a coding CLI**: drive the convert and fix stages through a coding agent's command line
  (one long-lived session, renewed only when it slows down) as well as through model APIs.

## Releases

About one minor release per quarter, patch releases as needed (see [SECURITY.md](SECURITY.md) for which
versions receive fixes). Every release is signed, reproducible and listed in [CHANGELOG.md](CHANGELOG.md).
