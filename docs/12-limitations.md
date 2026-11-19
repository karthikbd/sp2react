# 12. Coverage and limitations

Run `sp2react run --until inventory` on your site first. The inventory shows exactly which pages, scripts and behaviours were found, before you commit to a conversion.

## Converted

| SharePoint | Becomes |
|---|---|
| List forms (New / Edit / Display), including customised form pages | one React screen per list, rendered by the shared form engine from the spec |
| jQuery / SPServices behaviour on forms: show and hide, required, read-only, defaults, derived values, cascading dropdowns (`SPCascadeDropdowns`), comparisons between fields, length / range / pattern checks, unique values, values set on save, item locking, confirmations, banners, redirects after save | spec rules, enforced in the browser **and** in the API |
| `PreSaveAction` validation and its messages | rules with the **same message text**, word for word |
| Role checks (`GetGroupCollectionFromUser`, current-user checks) | role conditions on SharePoint group names |
| Web part pages in `SitePages` with Script Editor / Content Editor JavaScript (dashboards, tiles, tables built from REST calls) | React page components written by agents, using the generated API |
| REST (`_api/...`) and SPServices data calls | calls to the generated FastAPI endpoints |
| Basic list views: columns, sort, row limit (first page only; see below) | list view screens |
| Attachments | attachment upload, download and delete |
| SharePoint groups | roles |
| Site CSS | carried over as `legacy.css` |
| Old URLs (`NewForm.aspx`, `EditForm.aspx?ID=`, `DispForm.aspx?ID=`, page URLs) | redirects to the new routes |

## Not converted, and not detected (needs your input)

sp2react does not look for the items below yet: check Site Contents and the site's workflow settings yourself.

| SharePoint | Why | What to do |
|---|---|---|
| Workflows (SharePoint Designer 2010/2013, Nintex, etc.) | their definitions are not readable as code over REST | export the definitions; reimplement as server handlers or a job |
| Event receivers, timer jobs, farm solutions (compiled .NET) | compiled code is not reachable over REST | provide the source, or reimplement |
| InfoPath forms, Power Apps forms | different technology; InfoPath list forms live under `Item/` and are not extracted | rebuild separately |
| Calculated columns | the formula is shown, but not recomputed | compute in the database (computed column or view) or add a `derive` rule |
| Managed metadata, item-level permissions, alerts and alert emails | no equivalent generated yet | handle in your platform |

## Planned (not yet in 0.1.x)

- Views with filters and grouping, and a rich grid (sort, search, multi-select, export).
- Modal dialogs (`SP.UI.ModalDialog`) as React dialogs.
- An explicit inventory of ribbon and custom buttons.
- Document libraries.
- Custom master-page branding.
- A site-wide assessment command covering Site Contents, subsites, content types, workflows and event receivers, with a readiness report.

## Known constraints

- Pages are found in `SitePages` and in each list's forms; the `Pages` library, master pages and page layouts are not extracted.
- List views: the view's columns, sort and row limit are used; its filter (`<Where>`) and paging beyond the first page are not.
- Multi-value lookup columns are shown as a single choice on the edit form, and an edit keeps one value.
- Date-and-time columns are shown in UTC on the edit form; check them before going live.
- Hyperlink columns keep the URL but not the description; managed metadata is not converted.
- Wiki page bodies (`WikiField`) are not read.
- Only SharePoint on-premises classic pages have been targeted (2013 / 2016 / 2019 / Subscription Edition). Modern pages and SharePoint Online are not targeted.
- `map-db` maps lists to **tables**, not views.
- One model is used for all agents.
- In database mode, group **membership** is not read from SharePoint: map a groups table or fill `data/roles.json`.
- Version 0.1 has been tested against a replica site, a mock SharePoint server and SQLite standing in for the migrated database. Treat the first runs on your farm and database as a pilot: start with one or two screens and check them side by side.
