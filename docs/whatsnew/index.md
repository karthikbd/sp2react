# Release notes

## 0.1.4 (November 2026)

- **Security fixes found by a threat model** (see the {doc}`security assurance case </development/security-assurance>`):
  - Page and asset URLs from the site (`/sites/x/../../y.js` in a page's script tags) could make
    `extract` write files outside the workspace; attachment names from the server could do the same
    during `migrate`. Both are now refused and recorded as extraction errors, before anything is
    downloaded.
  - The generated app's builds and tests (which include agent-written handlers) no longer receive
    sp2react's own credentials: the configured SharePoint, model and database-URL variables are removed
    from their environment.
  - Screen ids in specs must be plain names.
- **Generated app**: text functions in `$filter` with a number (`endswith(Title,0)`) now answer 400
  instead of a server error (a fuzzing find), and on your database `%` and `_` in their text are matched
  literally. Regenerate existing apps to pick this up.
- **Project standards** (OpenSSF Best Practices silver and baseline): governance, code of conduct,
  roadmap, security assurance case, dependency and scanning policy, a VEX document; `mypy --strict` and
  Bandit security lint; a coverage floor of 80% of statements; reproducible builds checked in CI and used
  for releases; signed-off commits (DCO) and dependency review on pull requests; every version pinned in
  the CI tool locks is audited, including versions pinned for other Python versions.
- **Documentation** reorganised into *Getting started*, *User guide*, *Reference* and *Development*, with
  install notes for offline installs and for verifying a download's signature.

## 0.1.3 (November 2026)

Security and data fixes from a review of 0.1.2 (generated app: static route, authentication defaults,
role and lock checks on delete and attachments, legacy markup sanitising; agents: file paths), REST
names for columns starting with `_` or a digit, retries for throttling, list views with their filters
and paging, wiki pages, multi-value lookups, date-and-time zones, hyperlinks and managed metadata; **no
runtime dependencies**; and the release standards of signed, attested releases with an SBOM.

## Earlier releases

See the {doc}`/changelog`.
