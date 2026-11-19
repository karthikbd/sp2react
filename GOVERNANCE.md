# Governance

sp2react is a small project with a single maintainer. This document says who decides what, who holds
which keys, and what happens if the maintainer becomes unavailable. It changes through a pull request
like any other file.

## Roles

| Role | Who | Responsibilities |
|---|---|---|
| **Maintainer** | Karthikeyan Balasundaram ([@karthikbd](https://github.com/karthikbd)) | Sets direction (see [ROADMAP.md](ROADMAP.md)); reviews and merges pull requests; cuts releases; answers security reports (see [SECURITY.md](SECURITY.md)); keeps CI, dependencies and documentation current; enforces the [Code of Conduct](CODE_OF_CONDUCT.md). |
| **Contributor** | Anyone who opens an issue or pull request | Follows [CONTRIBUTING.md](CONTRIBUTING.md), signs off commits (DCO), keeps changes tested and documented. |
| **Security reporter** | Anyone | Reports vulnerabilities privately as described in [SECURITY.md](SECURITY.md); is credited unless they ask not to be. |

## Decisions

- Day-to-day decisions (accepting a pull request, scheduling a release) are made by the maintainer, in
  the open: in the pull request or issue concerned.
- Larger changes (a new stage or agent, a change to the generated app's layout or API, a breaking
  change to `sp2react.yaml`, a new runtime dependency, which is normally refused) start as an issue so they can be discussed before code is written.
- Disagreements are settled by discussion on the issue; if that doesn't settle them, the maintainer
  decides and records the reasoning there.

## Access to sensitive resources

Everyone with access is listed here; there is no other access.

| Resource | Who has access | Notes |
|---|---|---|
| GitHub repository (admin) | Maintainer | Two-factor authentication required. `main` accepts changes only through pull requests with passing checks. |
| PyPI project `sp2react` | No person publishes | Releases are uploaded only by the `python-publish.yml` workflow through PyPI Trusted Publishing (OIDC), from the protected `release` environment. No API token exists. |
| Model provider credentials | None held by the project | Tests use a scripted model; no API key or Copilot token is stored in the repository or its CI. |
| Release signing | No long-lived key | Sigstore keyless signing in the release workflow, tied to the workflow's identity. |
| Read the Docs project | Maintainer | Builds from the GitHub repository through the Read the Docs GitHub App. |
| OpenSSF Best Practices entry | Maintainer | sp2react's entry on bestpractices.dev (linked from the README badge). |

## New maintainers and changes to permissions

- Someone becomes a maintainer after a sustained record of reviewed contributions, by agreement of the
  existing maintainer(s), recorded in a pull request that updates this file.
- New collaborators start with the lowest GitHub role that lets them do their task (triage, then
  write); admin rights and the PyPI/Read the Docs roles are granted only to maintainers.
- Any request to raise someone's permissions is reviewed by an existing maintainer before it is
  granted, and the change is recorded in this file.
- Access is removed when it is no longer used, and at the latest after 12 months of inactivity.

## Continuity

The project currently has one maintainer (a "bus factor" of 1), which we would like to change; see
[ROADMAP.md](ROADMAP.md). Until then:

- everything needed to build, test and release is in the repository and runs in GitHub Actions; no
  secret or personal machine is involved, so anyone with admin rights can release;
- the maintainer's GitHub account has a designated successor, so the repository (and through Trusted
  Publishing, the ability to release) can be handed over if the maintainer is unable to continue;
- the project is MIT-licensed, so anyone may fork and continue it.
