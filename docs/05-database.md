# 5. Your database

When the SharePoint list data has already been migrated into SQL Server, MySQL or another relational database, use `data_source: database` (the default). The generated FastAPI app then reads and writes those tables directly, and sp2react never reads list items from SharePoint.

What sp2react needs to know is **which table holds each list and which column holds each field**. That is the mapping file, `db-mapping.json`. `sp2react map-db` drafts it from the database schema; you review it.

## 1. Connection URL

Put a SQLAlchemy URL in the environment variable named by `database.url_env` (default `SP2REACT_DB_URL`).

### SQL Server

Install: `pip install "sp2react[mssql]"`, plus **ODBC Driver 18 for SQL Server** on the machine.

SQL login:
```powershell
$env:SP2REACT_DB_URL = "mssql+pyodbc://USER:PASSWORD@db-host:1433/SEA?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes"
```

Windows authentication (the signed-in Windows account):
```powershell
$env:SP2REACT_DB_URL = "mssql+pyodbc://@db-host/SEA?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes"
```

- Named instance: `db-host\INSTANCE` in place of `db-host:1433`.
- Remove `TrustServerCertificate=yes` when the server's certificate is trusted by your machine.
- With ODBC Driver 17, use `driver=ODBC+Driver+17+for+SQL+Server`.

### MySQL / MariaDB

Install: `pip install "sp2react[mysql]"`.
```powershell
$env:SP2REACT_DB_URL = "mysql+pymysql://USER:PASSWORD@db-host:3306/sea?charset=utf8mb4"
```

### PostgreSQL

Install: `pip install "sp2react[db]" "psycopg[binary]"`.
```powershell
$env:SP2REACT_DB_URL = "postgresql+psycopg://USER:PASSWORD@db-host:5432/sea"
```

### Special characters in passwords

URL-encode them: `@` → `%40`, `:` → `%3A`, `/` → `%2F`, `#` → `%23`, `%` → `%25`. In Python: `urllib.parse.quote_plus("p@ss:word")`.

### Schema

If the tables are not in the connection's default schema, set it in the config:
```yaml
database:
  schema_name: dbo        # SQL Server; for PostgreSQL e.g. public or sea
```

## 2. Draft the mapping: `sp2react map-db`

Run it after at least one spec has been approved (`sp2react run` also runs it automatically once specs are approved):

```powershell
sp2react map-db
```

What it does:

1. **Reads the schema only:** table names, column names and types, primary keys, nullability. It does not read any rows. The result is saved as `sp2react-work/db-schema.json`.
2. **Drafts the mapping** with plain name matching:
   - list name or title to table name (ignoring case, separators and prefixes such as `tbl_`);
   - field internal or display name to a column of a compatible type;
   - lookups to the column with a foreign key to the looked-up table, or an `..._id` column;
   - people to user-id or login columns (text columns become `"ref": "login"`);
   - `Created`/`Modified`/`Author`/`Editor`/version to typical audit column names;
   - a `users`/`app_users` table, if there is one.
3. **Validates** the draft against the schema.
4. If anything is still unresolved, the **dbmap agent** gets the list schemas, the table and column names and types, the draft and the problems, and proposes the missing pieces. For example, it can find that `Countries.Title` was migrated as `countries.country_name`, or which table holds attachments and group membership. Its proposal is validated again.
5. Writes `db-mapping.json` (next to your config) and a readable report, `sp2react-work/db-mapping.md`.

The command ends with **Mapping ready** or **Mapping needs attention**. `convert` will not run in database mode until the mapping has no problems.

If `db-mapping.json` already exists, sp2react **keeps it** and only adds lists that are missing from it. Your edits are not overwritten.

## 3. Review the mapping

Open `sp2react-work/db-mapping.md`. For each list it shows the table, the key, and every field next to its column and column type, followed by problems and warnings.

**Problems** block code generation:
- a list with no table, or a table or column that does not exist;
- a required list field with no column;
- a mapped name that is not a field of the list.

**Warnings** should be read but do not block:
- a field type that does not obviously match the column type (e.g. a date field on a `VARCHAR` column);
- an optional field with no column (it will not be saved);
- a lookup to a list that is not mapped (lookup titles will be empty);
- a `NOT NULL` column that nothing writes (inserts fail unless the column has a default).

Fix anything wrong by editing `db-mapping.json` directly, then run `sp2react map-db` again to re-validate.

### Review checklist

- [ ] Every list points at the right table and the right key column.
- [ ] Lookup fields point at the column that holds the **key of the looked-up row**, not its title text.
- [ ] People fields point at a user id or login column, and `ref` says which (see below).
- [ ] `Created`, `Modified`, `Author`, `Editor` point at the audit columns the migration filled.
- [ ] `version` is mapped only to an integer column (see the SQL Server notes).
- [ ] Choice fields hold the same text values as in SharePoint (e.g. `Approved`, not `A`).
- [ ] Group membership comes from a groups table or `data/roles.json`.

## 4. The mapping file

```json
{
  "version": 1,
  "schema": "dbo",
  "lists": {
    "VendorRequests": {
      "table": "tbl_vendor_requests",
      "key": "request_id",
      "fields": {
        "Title": "vendor_name",
        "Country": "country_id",
        "Requester": {"column": "requester_login", "ref": "login"},
        "Tags": {"column": "tags", "delimiter": ";"}
      },
      "system": {
        "Created": "created_at", "Modified": "modified_at",
        "Author": "created_by", "Editor": "modified_by",
        "version": "row_version"
      },
      "attachments": {"table": "vendor_request_files", "item": "request_id", "name": "file_name", "content": "content"}
    },
    "Countries": {"table": "countries", "key": "id", "fields": {"Title": "country_name"}, "system": {}}
  },
  "users": {
    "table": "app_users", "id": "user_id", "login": "login", "title": "display_name", "email": "email",
    "groups": {"table": "user_groups", "user": "user_id", "group": "group_name"}
  }
}
```

| Part | Meaning |
|---|---|
| `lists.<ListKey>` | One entry per SharePoint list. The key is the list's internal key as shown in `db-mapping.md` |
| `table`, `key` | The table and its primary key column. The key plays the role of the SharePoint item `ID` |
| `fields` | Field internal name → column name. Use an object for special cases: |
| &nbsp;&nbsp;`{"column": c, "ref": "login"}` | a person field stored as a login (`CORP\user`) rather than a user id |
| &nbsp;&nbsp;`{"column": c, "delimiter": ";"}` | a multi-value field (multi-choice, multi-lookup) stored in one text column |
| `system` | Audit columns: `Created`, `Modified`, `Author`, `Editor`, and optionally `version` |
| `attachments` | Table holding attachments: the item key column, file name column and content (binary) column |
| `users` | Table of people: id, login, display name, email. `groups` names a table linking users to SharePoint group names |

**Lookups:** the column holds the key of the row in the looked-up list's table, and that list must be mapped too.

**People:** by default the column holds the `users` table id; with `"ref": "login"` it holds the login. Without a `users` entry, people are just their login, and roles come from `converted-app/backend/data/roles.json`:

```json
{ "Compliance Reviewers": ["CORP\\bob", "CORP\\alice"], "Procurement Owners": ["CORP\\carol"] }
```

sp2react writes this file with the SharePoint group names and empty member lists; in database mode it does not read group membership from SharePoint, so fill in the members (or map a groups table).

## 5. What the app does at runtime

- Reads, filters, sorts and pages in SQL. The forms and pages ask for data with OData-style parameters (`$filter`, `$orderby`, `$top`, `$skip`, lookup paths such as `Country/Title`), and the API translates them into SQL on the mapped tables.
- Writes through the same mapping, after enforcing the same rules as the browser (required fields, validation, derived values, locks).
- Prevents lost updates: an edit must carry the version the user loaded; if the row changed in the meantime the API answers `412` and the form shows SharePoint's own "Save Conflict" message. It uses the `version` column if mapped, otherwise the `Modified` column.
- Sets `Created`/`Modified`/`Author`/`Editor` on every write when mapped.

## 6. Check the earlier migration (optional): `reconcile`

To compare the SharePoint lists with your tables field by field, allow item reads for this one purpose:

```yaml
security:
  sharepoint_item_reads: true
```

```powershell
sp2react reconcile        # after convert: it reads your tables through the generated app
```

sp2react exports every list item and attachment over REST, reads every row back **through the generated app's own data layer**, and compares them field by field: values, lookups (including orphans), people, dates, numbers, attachment checksums. The result is `sp2react-work/reconciliation.md` (and `reconciliation.json`). While item reads are on, the `test` stage also runs this comparison and fails any screen whose lists do not match; such failures are fixed in the mapping or the data, not by the fix agent. Set `sharepoint_item_reads` back to `false` (or remove it) afterwards.

## SQL Server notes

- **`rowversion` / `timestamp` columns** are written by SQL Server itself and cannot be updated. Do not map one as `system.version`; leave `version` out (the app then uses `Modified`) or map an integer column.
- **Tables with triggers:** SQLAlchemy uses `OUTPUT inserted...` on inserts, which SQL Server rejects on tables with triggers ("The target table ... cannot have any enabled triggers if the statement contains an OUTPUT clause"). If you see this, set `implicit_returning=False` on those tables in `converted-app/backend/app/sql_repo.py` and report it so it can become a mapping option.
- **Identity keys:** inserts let SQL Server generate the key; the new id is returned to the form.
- **`nvarchar(max)` / `varbinary(max)`** work for multi-line text and attachment content.

## MySQL notes

- Use `charset=utf8mb4` in the URL so non-ASCII text round-trips.
- `TINYINT(1)` columns work for yes/no fields.
