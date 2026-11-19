# Security Policy

## Supported versions and end of support

| Version | Security fixes |
|---------|----------------|
| 0.1.x   | ✅ yes: the latest release line |
| older   | ❌ no: upgrade to the latest release |

Only the latest minor release line receives fixes. When a new minor version is released, the previous
one stops receiving security updates **on that day**; this is announced in [CHANGELOG.md](CHANGELOG.md).
Upgrading within 0.x keeps `sp2react.yaml`, the workspace and generated apps working unless the changelog
says otherwise (regeneration keeps files you changed; see the documentation's *The generated app* page),
so the upgrade path is always "install the latest release". Before 1.0, minor versions may change
behaviour; each change is listed in the changelog.

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Report vulnerabilities privately via GitHub's [Security Advisories](https://github.com/karthikbd/sp2react/security/advisories/new).

You can expect:
- **Acknowledgement** within 48 hours
- **Status update** within 7 days
- **Fix or mitigation** as soon as reasonably possible, coordinated with a disclosure date

## How reports are handled

1. **Acknowledge** within 48 hours and agree on a way to keep in touch.
2. **Triage** within 7 days: reproduce, assess severity (CVSS v4), and decide whether the report is a
   vulnerability in sp2react, in the application it generates, or in something it uses.
3. **Fix** on a private fork (GitHub Security Advisory), with a regression test. Target: 30 days for
   high and critical issues, 60 days for medium; low-severity issues may be fixed in the next release.
4. **Release** a patched version, then **publish** the advisory with a CVE (requested through GitHub)
   and list the fix under *Security* in the changelog. A fix in the generated app's templates says
   whether existing apps must be regenerated.
5. **Credit** the reporter by name in the advisory and the release notes, unless they prefer otherwise.

Known vulnerabilities, fixed or not, are published as GitHub Security Advisories for this repository.
Vulnerabilities in dependencies that do **not** affect sp2react or the apps it generates are recorded in
the VEX document [`vex.openvex.json`](vex.openvex.json) (OpenVEX), so scanners can tell users they need
not act.

## Network access

`sp2react` has no telemetry, no update check and no third-party calls. It opens HTTP connections to exactly two kinds of host, both named in your `sp2react.yaml`:

| Host | Why | What is sent / received |
|------|-----|-------------------------|
| `sharepoint.site_url` | Read the site being converted | GET requests only (the client refuses any other verb). Page source, web part definitions, custom scripts/CSS, list schemas, views, group names, navigation |
| `llm.base_url` (Bridger, or the provider you chose) | AI agent calls | Page source, scripts, list schemas and the draft spec or code under review |

Every request, and every redirect hop, is checked against that allowlist before it is sent (`sp2react/net.py`); anything else raises `NetworkPolicyError`. Extra hosts must be added explicitly under `security.allowed_hosts`.

## Business data

With `pipeline.data_source: database` (the default):
- list items, attachments, site users and rendered pages are **never read** from SharePoint; the client raises `ItemReadBlocked` if anything tries
- group membership is not read (group names only)
- no business data is sent to the model; prompts contain code and schema only
- `sp2react map-db` reads your database **schema** (tables, columns, types, keys) over the database driver; it does not read rows

Item reads over HTTP happen only when you set `data_source: sqlite` (sp2react migrates the data itself) or explicitly enable `security.sharepoint_item_reads: true` to reconcile the lists with your tables.

## Secrets

Credentials are read from environment variables named in the config (`SP_USERNAME`/`SP_PASSWORD`, `SP_COOKIE`, `SP_TOKEN`, the model token, the database URL). They are never written to the workspace, the generated app or agent transcripts. Page source and scripts are sent to the model and kept in the agent transcripts (`sp2react-work/agents/`); if your pages embed secrets in script, remove them before extraction or treat the workspace as secret.

## Generated application

The generated FastAPI app defaults to `AUTH_MODE=header`: it trusts the identity header set by an authenticating gateway in front of it and refuses requests without one. `AUTH_MODE=dev` (any user name in an `X-User` header) is for local testing and accepts requests from the same machine only. Before deployment, put the app behind your gateway, or replace `app/auth.py` with Entra ID token validation. The front end shows legacy Content Editor markup only after rebuilding it from an allow-list, and attachment names and the static-file route are checked so no request can read or write outside their folders.

## Supply chain

- Every CI `pip install` is hash-locked (`ci/requirements-*.txt`); every GitHub Action is pinned to a commit SHA.
- `vulnerability-audit.yml`: `pip-audit` of all CI tooling (every pinned version, whatever Python it is
  pinned for) and of the generated app's back end, and `npm audit` of its front end, weekly and on every change.
- On pull requests: dependency review blocks dependencies with known vulnerabilities, and every commit
  must be signed off (DCO).
- CodeQL and OpenSSF Scorecard on every push to `main` and weekly; Dependabot for actions, CI tooling and
  the generated app's templates.
- ClusterFuzzLite fuzzing (Atheris) of the config reader, spec validation, ASPX/JavaScript analysis, NTLM
  and the generated API's `$filter` parser on every pull request, push and daily.
- Releases: PyPI Trusted Publishing with provenance attestations; reproducible builds (checked in CI);
  Sigstore-signed wheel, sdist and a CycloneDX SBOM attached to each GitHub release, re-verified by
  `verify-release.yml`.

The documentation's [security assurance case](https://sp2react.readthedocs.io/en/latest/development/security-assurance.html)
lists the threats considered and what stops each one.

## Secrets and credentials used by the project

- **None are stored.** PyPI uploads use Trusted Publishing (short-lived OIDC tokens); release signing is
  keyless (Sigstore). The repository has no Actions secrets except GitHub's own `GITHUB_TOKEN`; tests use a
  scripted model, so no model API key or Copilot token is needed in CI.
- `GITHUB_TOKEN` is read-only by default in every workflow (`permissions: read-all`); jobs ask for write
  access only for what they do (for example `id-token: write` in the publish job).
- Secret scanning with push protection is enabled; a leaked credential would be revoked at the issuer
  first, then removed from history.
- If a secret is ever needed, it is stored as a GitHub environment secret limited to the job that uses
  it, reviewed when a maintainer changes and rotated at least yearly.
