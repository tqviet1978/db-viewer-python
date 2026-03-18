# WORKLOG — DB Viewer Python v1.0.2

**Date:** 2026-03-18
**Base version:** v1.0.1
**Status:** ✅ All items implemented, 259 tests passing

---

## 1. Summary

This release completes the remaining low-priority items from v1.0.0 and all
new items identified during v1.0.1 work.

**By the numbers:**

| Metric | v1.0.1 | v1.0.2 | Delta |
|--------|--------|--------|-------|
| Tests | 204 | 259 | +55 |
| Python lines (src + tests) | 5,723 | 6,805 | +1,082 |
| Frontend lines | 1,079 | 1,311 | +232 |
| New source files | — | 1 | +1 |
| Modified source files | — | 6 | — |
| New test file | — | 1 | — |
| New API endpoints | — | 4 | +4 |

---

## 2. Items Implemented

### Item 1 — Dark Mode ✅

**Approach:** CSS custom-property swap using `@media (prefers-color-scheme: dark)`
plus a manual class-based override (`:root.dark` / `:root.light`), so the
system preference is the default but users can pin their choice.

**CSS additions (`static/index.html`):**
```css
/* Follows OS preference by default, but respects .light override */
@media (prefers-color-scheme: dark) {
  :root:not(.light) {
    --bg: #0d1117;  --bg2: #161b22;  --border: #30363d;
    --text: #e6edf3;  --text2: #8b949e;
    --accent: #58a6ff;  --success: #3fb950;  --danger: #f85149;
    --btn-bg: #21262d;  --btn-border: rgba(240,246,252,0.1);  --btn-hover: #30363d;
  }
}
/* Manual dark override */
:root.dark  { /* same vars as above */ }
```

All existing CSS already used `var(--*)` everywhere, so no further style
changes were needed — the variable swap is sufficient.

**Vue state and persistence:**
- `isDark` computed from `localStorage.getItem('dbviewer_theme')`, falling back
  to `window.matchMedia('(prefers-color-scheme: dark)').matches`
- `watch: isDark` toggles `.dark` / `.light` class on `<html>` and writes to
  `localStorage`
- `mounted()` applies the class immediately before first paint to prevent flash

**UI:** A `☀ Light` / `🌙 Dark` button replaces the standalone sign-out button
in the sidebar footer (both buttons now sit in a two-column flex row).

**No backend changes required.**

---

### Item 2 — Column Ordering (Client-Side Sort) ✅

**HTML table header changes (`drivers/base.py`):**
Each column header in `export_as_html_table` is now:
```html
<th class="sortable" data-col="COLUMN_NAME">
  COLUMN_NAME<span class="sort-arrow"> ⇅</span>
</th>
```
The `#` (index) column is intentionally kept non-sortable.

**CSS:**
```css
.response-pane table th.sortable { cursor: pointer; user-select: none; }
.response-pane table th.sortable:hover { background: var(--btn-hover); }
.sort-arrow { font-size: 10px; opacity: .5; }
th.sort-active .sort-arrow { opacity: 1; }
```

**Vue event delegation (`_sortTableDom(table, col)`):**
The existing `onResponsePaneClick` handler (which already manages inline cell
editing) is extended to intercept clicks on `th.sortable` elements:

1. Finds the column index from `th.dataset.col`
2. Toggles `asc` → `desc` → `asc` via `table.dataset.sortDir`
3. Updates arrow indicators on all headers (active: `▲`/`▼`, inactive: `⇅`)
4. Sorts `<tbody>` rows in place using `Element.appendChild` (moves existing
   DOM nodes — no re-render required)
5. Sort comparison: numeric-aware — tries `parseFloat` first, falls back to
   `localeCompare` for strings

**No backend changes required.** Works on any table returned by any API endpoint.

---

### Item 3 — Multi-Statement SQL Import ✅

**New file: `src/dbviewer/sql_tokenizer.py`** (199 lines)

`split_statements(script, delimiter=";")` replaces the naive `query.split(";")`
that broke on any SQL file containing stored procedures, triggers, or functions.

**Handled correctly:**
| Syntax | Handling |
|--------|----------|
| `'string with ; inside'` | Single-quoted string — semicolons ignored |
| `"string with ; inside"` | Double-quoted string — semicolons ignored |
| `''` escaped quote | Doubled-quote escape |
| `/* block comment ; */` | Block comment — content ignored |
| `-- line comment ;` | Line comment — content ignored until newline |
| `# line comment ;` | MySQL hash comment |
| `$tag$...$tag$` | PostgreSQL dollar-quoting |
| `BEGIN ... END` | Depth-tracked — delimiter inside block is not a split point |
| `DELIMITER //` | Resets the statement delimiter for subsequent statements |

The tokenizer is a single-pass character scanner (no regex splitting) with
explicit state machine for all quoting/comment modes.

**Integration in `importSqlFile` endpoint:**
```python
from .sql_tokenizer import split_statements
parts = split_statements(sql)
ok, errors = 0, []
for part in parts:
    _, error, _ = d.execute_query(part)
    if error:
        errors.append(f"Error in: {part[:80]}…<br/>{error}")
    else:
        ok += 1
return {"success": True, "html": f"Imported {ok}/{len(parts)} statements."}
```

Error messages include the first 80 characters of the failing statement to aid
debugging, unlike the previous implementation which just said "Error: ...".

---

### Item 4 — `--log-level` CLI Flag ✅

**CLI addition (`cli.py`):**
```
--log-level {critical,error,warning,info,debug}
    Uvicorn log level (default: warning)
```

**Server change (`server.py`):**
`start_server()` accepts `log_level: str = "warning"` and passes it directly to
Uvicorn:
```python
uvicorn_kwargs: dict = dict(host=host, port=port, log_level=log_level)
```

**Usage:**
```bash
dbviewer --log-level debug     # Verbose — shows all requests
dbviewer --log-level info      # Shows request logs (useful for monitoring)
dbviewer --log-level warning   # Default — only warnings and errors
dbviewer --log-level error     # Minimal — production-style
```

---

### Item 5 — EXPLAIN ANALYZE for PostgreSQL ✅

**Change in `executeQuery` handler (`api.py`):**
When `mode == "explain"`, the handler now detects the database backend and
chooses the appropriate EXPLAIN syntax:

```python
if body.mode == "explain":
    from .schema_diff import _detect_db_type
    explain_kw = "EXPLAIN ANALYZE" if _detect_db_type(d) in ("postgres", "postgresql") \
                 else "EXPLAIN"
    query = f"{explain_kw} {query}"
    output_query = False
```

`EXPLAIN ANALYZE` actually executes the query and returns real timing
statistics (not just the estimated plan), which is far more useful for
PostgreSQL performance debugging.

For MySQL and MSSQL, the existing `EXPLAIN` continues to be used unchanged
(MySQL's `EXPLAIN ANALYZE` is supported but adds less value for typical use,
and MSSQL uses `SHOWPLAN` which requires a different mechanism).

**No UI changes needed** — the existing "Explain" button is reused.

---

### Item 6 — HTTPS Auto-Certificate ✅

**New function: `generate_dev_cert(data_dir)` in `server.py`**

Uses the `trustme` library to generate a locally-trusted TLS certificate:

```python
def generate_dev_cert(data_dir: str) -> tuple[str, str]:
    ca = trustme.CA()
    server_cert = ca.issue_cert("localhost", "127.0.0.1")
    # Write cert chain to data_dir/dev-cert.pem
    # Write private key to data_dir/dev-key.pem
    return cert_path, key_path
```

- Certificate is issued for `localhost` and `127.0.0.1`
- Files are cached in `data_dir` and **reused on subsequent starts** (no
  regeneration unless the files are deleted)
- If `trustme` is not installed, a clear warning is printed and HTTP is used
  as a fallback

**CLI usage:**
```bash
# Manual cert (unchanged from v1.0.1)
dbviewer --ssl-cert /path/to/cert.pem --ssl-key /path/to/key.pem

# Auto-generated dev cert via trustme
dbviewer --ssl-cert auto
```

When `--ssl-cert auto` is used:
1. `generate_dev_cert(data_dir)` is called
2. The generated cert paths are used as `ssl_certfile` / `ssl_keyfile` in
   Uvicorn's kwargs
3. The startup banner shows `TLS → auto-generated dev cert (localhost only)`

**Note:** `trustme` certs are intended for local development only and are not
trusted by browsers by default. For production, use real certificates from
Let's Encrypt or a CA.

---

### Item 7 — Connection Form Port Auto-Fill ✅

**Vue watcher (`static/index.html`):**
```javascript
watch: {
  'connForm.type'(val) {
    const defaults = { mysql: 3306, postgres: 5432, mssql: 1433, sqlite: 0 }
    if (defaults[val] !== undefined) this.connForm.port = defaults[val]
  }
}
```

When the user changes the Type dropdown in the Settings → Connections form,
the Port field is automatically updated to the standard default for that
database type:

| Type | Default port |
|------|-------------|
| MySQL | 3306 |
| PostgreSQL | 5432 |
| MSSQL | 1433 |
| SQLite | 0 (no port) |

Port is only auto-filled when the type changes — manually entered ports are
preserved when editing an existing connection unless the user explicitly
changes the type.

---

### Item 8 — Settings Tab — User Management ✅

**New API endpoints (4):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/users` | GET | Return list of usernames (no passwords ever exposed) |
| `POST /api/users/add` | POST | Create new user or update if username exists |
| `POST /api/users/password` | POST | Change password for existing user |
| `POST /api/users/delete` | POST | Delete user; refuses to delete last user |

**Safety rules:**
- `users/add` rejects empty username or empty password
- `users/password` rejects empty new password, returns 404-style error if user not found
- `users/delete` returns `{success: false}` if the user is the last one, preventing lockout
- Passwords are never returned in any response (only usernames)

**New Pydantic models:** `UserCreateBody`, `UserPasswordBody`, `UserDeleteBody`

**Frontend — Settings → Users sub-tab:**

The Settings tab now has two sub-tabs: **Connections** (unchanged) and **Users**.

Users sub-tab layout:
- Left panel (40%): User list with "Change pw" and "✕ delete" per entry;
  delete is disabled when only one user remains; "+ Add user" button at bottom
- Right panel (60%): Context-sensitive form:
  - Add mode: Username + Password + Confirm password fields
  - Change password mode: Shows username (read-only), Password + Confirm fields
  - Validation errors / success messages shown inline (styled red ❌ / green ✅)

**Switching sub-tabs:**
```html
<button @click="settingsView='users'; loadUsers()">Users</button>
```
`loadUsers()` always fetches fresh from `GET /api/users` when switching to the
Users tab, ensuring the list is current after changes made via CLI.

---

### Item 9 — SQLite Demo Mode ✅

**New `--demo` CLI flag:**
```bash
dbviewer --demo
# Equivalent to: --no-auth + pre-seeded SQLite connection
```

**`_setup_demo_mode(data_dir)` in `server.py`:**

1. Checks if `connections.json` already exists; if so, skips (idempotent)
2. Creates a `demo.sqlite` file in `data_dir`
3. Writes a `connections.json` pointing to that file
4. Seeds two tables:

**`DEMO_USERS`** (5 rows):
| NAME | EMAIL | ROLE |
|------|-------|------|
| Alice Smith | alice@example.com | admin |
| Bob Jones | bob@example.com | editor |
| Carol White | carol@example.com | viewer |
| Dave Brown | dave@example.com | editor |
| Eve Davis | eve@example.com | viewer |

**`DEMO_ORDERS`** (5 rows):
| ID_USER | PRODUCT | TOTAL_VALUE | ORDER_DATE |
|---------|---------|-------------|------------|
| 1 | Widget A | 99.50 | 2024-06-01 |
| 1 | Widget B | 149.99 | 2024-06-15 |
| … | … | … | … |

All columns follow the system column conventions (UUID, GUID, CREATION_DATE,
etc.) so they are correctly handled by concept/structure/snippets endpoints.

`start_server()` automatically sets `no_auth=True` when `demo=True`, so the
login screen is skipped.

**Use cases:**
- UI development without a real database
- Quick demos to stakeholders
- Testing the frontend without configuring MySQL/PostgreSQL

---

### Item 10 — Schema Diff: PostgreSQL + MSSQL `copy_tables` / `clone_database` ✅

**New function: `_build_create_table_from_schema(table, handler)` in `schema_diff.py`**

Replaces the MySQL-only `SHOW CREATE TABLE` approach with a backend-aware DDL
reconstruction from the schema maps built by `_get_schema_*`:

**MySQL path (unchanged behaviour):**
```python
rows = handler.execute_query(f"SHOW CREATE TABLE `{table}`")
create_sql = rows[0]["Create Table"]  # exact DDL from MySQL
return ["DROP TABLE IF EXISTS `{table}`", create_sql, "INSERT INTO ..."]
```

**PostgreSQL path:**
- Reconstructs column definitions from `_get_schema_postgres()` output
- Column type string built from `udt_name` + precision/length
- NULL/NOT NULL from `is_nullable`
- DEFAULT from `column_default`
- Quoted identifiers: `"table"` and `"column"`
- Result:
```sql
DROP TABLE IF EXISTS "users"
CREATE TABLE IF NOT EXISTS "users" (
    "id" int4(32) NOT NULL,
    "name" varchar(255),
    ...
)
INSERT INTO "users" SELECT * FROM "users"
```

**MSSQL path:**
- Reconstructs from `_get_schema_mssql()` output
- Detects `IS_IDENTITY = 1` → appends `IDENTITY(1,1)`
- Bracket identifiers: `[table]` and `[column]`
- MSSQL-specific drop syntax: `IF OBJECT_ID(N'[table]', N'U') IS NOT NULL DROP TABLE [table]`
- Result:
```sql
IF OBJECT_ID(N'[users]', N'U') IS NOT NULL DROP TABLE [users]
CREATE TABLE [users] (
    [id] int IDENTITY(1,1) NOT NULL,
    [name] nvarchar(255) NULL,
    ...
)
INSERT INTO [users] SELECT * FROM [users]
```

`copy_tables()` and `clone_database()` both now route through
`_build_create_table_from_schema()`, making them backend-aware without any
changes to the calling code in `drivers/base.py` or `api.py`.

**Limitation:** The cross-database `INSERT INTO dest SELECT * FROM source.table`
idiom (which works natively in MySQL same-server cross-database scenarios) does
not work for PostgreSQL/MSSQL cross-server scenarios. For cross-server copy,
the data would need to be fetched and re-inserted row by row — this is noted as
a future improvement.

---

## 3. New Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/dbviewer/sql_tokenizer.py` | 199 | SQL statement splitter for multi-statement import |
| `tests/test_v102.py` | 642 | 55 tests for all v1.0.2 additions |

---

## 4. Modified Files

| File | v1.0.1 lines | v1.0.2 lines | Key changes |
|------|-------------|-------------|-------------|
| `src/dbviewer/static/index.html` | 1,079 | 1,311 | Dark mode CSS + toggle, sortable headers + `_sortTableDom`, Users sub-tab, port auto-fill watcher, `isDark` state + watchers |
| `src/dbviewer/server.py` | 84 | 185 | `generate_dev_cert()`, `_setup_demo_mode()`, `log_level` and `demo` params in `start_server()` |
| `src/dbviewer/cli.py` | 108 | 115 | `--log-level`, `--demo` flags |
| `src/dbviewer/api.py` | 889 | 960 | 4 user management endpoints, `UserCreateBody`/`UserPasswordBody`/`UserDeleteBody` models, EXPLAIN ANALYZE dispatch, `sql_tokenizer` in importSqlFile |
| `src/dbviewer/schema_diff.py` | 436 | 498 | `_build_create_table_from_schema()` with MySQL/PostgreSQL/MSSQL paths, `copy_tables` now routes through it |
| `src/dbviewer/drivers/base.py` | 653 | ~660 | `export_as_html_table` emits `th.sortable` + `data-col` + sort-arrow span |

---

## 5. Test Coverage

| File | Tests | Coverage focus |
|------|-------|---------------|
| `test_auth.py` | 9 | `auth.py` |
| `test_name_helper.py` | 25 | `name_helper.py` |
| `test_code_generator.py` | 20 | `code_generator.py` |
| `test_drivers.py` | 23 | `drivers/base.py` (via ConcreteDriver) |
| `test_excel_export.py` | 12 | `excel_export.py` |
| `test_schema_diff.py` | 11 | `schema_diff.py` (MySQL mock-based) |
| `test_api.py` | 13 | API routes, auth, safety |
| `test_integration_sqlite.py` | 47 | `SQLiteDriver` + full driver interface + API via SQLite |
| `test_v101.py` | 44 | v1.0.1 additions |
| `test_v102.py` | **55** | v1.0.2 additions (see below) |
| **Total** | **259** | |

**`test_v102.py` breakdown:**

| Class | Tests | What it covers |
|-------|-------|---------------|
| `TestSplitStatements` | 17 | Tokenizer: simple, quoted strings, comments, DELIMITER, BEGIN/END, dollar-quoting, edge cases |
| `TestExplainAnalyzeDispatch` | 3 | EXPLAIN ANALYZE for PostgreSQL, plain EXPLAIN for MySQL/MSSQL |
| `TestUserManagementEndpoints` | 13 | list, add, add-persisted, empty username/password, change-password, change-nonexistent, delete, delete-persisted, cannot-delete-last, delete-nonexistent, importSqlFile with tokenizer |
| `TestDemoMode` | 4 | creates connections.json, seeds tables, idempotent, app starts with demo connection |
| `TestAutoCert` | 3 | creates files, reuses on second call, files in correct directory |
| `TestBuildCreateTable` | 6 | MySQL uses SHOW CREATE TABLE, PG builds DDL, MSSQL builds DDL, missing table returns empty, varchar(255) in PG, IDENTITY in MSSQL |
| `TestSortableHeaders` | 4 | `sortable` class, `data-col` attribute, sort arrow, `#` not sortable |
| `TestLogLevel` | 2 | default is "warning", passed to Uvicorn |
| `TestServerSSLAuto` | 3 | `auto` value accepted, explicit cert requires both, nonexistent file raises |

---

## 6. Complete CLI Reference (v1.0.2)

```
dbviewer [OPTIONS]

Server options:
  --host HOST              Bind address (default: 0.0.0.0)
  --port PORT              Port number (default: 9876)
  --data-dir PATH          Data directory (default: ~/.dbviewer/data)
  --no-auth                Disable authentication
  --open                   Open browser on start
  --log-level LEVEL        Uvicorn log level: critical|error|warning|info|debug
                           (default: warning)                         [v1.0.2]
  --demo                   Start in demo mode with SQLite, no auth    [v1.0.2]

TLS options:
  --ssl-cert CERT_FILE     Path to SSL cert (.pem) or "auto" for dev cert
                           (added v1.0.1, "auto" added v1.0.2)
  --ssl-key  KEY_FILE      Path to SSL private key (.pem)             [v1.0.1]

User management:
  --create-user U P        Create user (used by installer)
  --change-password        Interactive password change

Service:
  --install-service        Write systemd user service file             [v1.0.1]
  --update                 Update from GitHub

Meta:
  --version                Show version and exit
```

---

## 7. Complete API Endpoint Reference (v1.0.2)

**Total: 37 endpoints** (28 from v1.0.0 + 5 from v1.0.1 + 4 from v1.0.2)

| Group | Endpoint | Added in |
|-------|----------|---------|
| **Auth** | `POST /api/login` | v1.0.0 |
| **Users** | `GET /api/users` | **v1.0.2** |
| | `POST /api/users/add` | **v1.0.2** |
| | `POST /api/users/password` | **v1.0.2** |
| | `POST /api/users/delete` | **v1.0.2** |
| **Connections** | `GET /api/connections` | v1.0.0 |
| | `POST /api/setActiveConnection` | v1.0.0 |
| | `POST /api/testConnection` | v1.0.1 |
| | `GET /api/connections/full` | v1.0.1 |
| | `POST /api/connections/add` | v1.0.1 |
| | `POST /api/connections/update` | v1.0.1 |
| | `POST /api/connections/delete` | v1.0.1 |
| **Schema** | `concept`, `structure`, `columnSearch`, `getColumnNames`, `indexes`, `describe`, `showSizes` | v1.0.0 |
| **Data** | `data`, `getTableColumns`, `insertTableRow` | v1.0.0 |
| **Query** | `executeQuery` (enhanced v1.0.2), `toString`, `snippets`, `vue` | v1.0.0 |
| **Destructive** | `truncateTables`, `dropTables`, `dropIndexes`, `insertFakeData`, `renameTable`, `cloneTable`, `alterColumn`, `insertAfterColumn`, `dropColumn` | v1.0.0 |
| **DB Ops** | `getPeerPatch`, `copyTables` (enhanced v1.0.2), `cloneDatabase` (enhanced v1.0.2) | v1.0.0 |
| **Export** | `exportQuickReportData` | v1.0.0 |
| **Import** | `importSqlFile` (enhanced v1.0.2) | v1.0.0 |
| **AI** | `sendChatMessage`, `generateCompactFormLayout` | v1.0.0 |

---

## 8. Remaining Roadmap

All items from v1.0.0 and v1.0.1 have now been implemented.

### New items identified during v1.0.2 work

- **[ ] `trustme` cert browser trust** — Browsers don't trust `trustme`
  auto-generated certs by default. Consider generating a root CA cert and
  prompting the user to add it to their OS trust store.

- **[ ] Cross-server `copy_tables` for PostgreSQL/MSSQL** — The current
  `INSERT INTO dest SELECT * FROM source` only works within the same server.
  For cross-server copy, implement row-fetch-and-insert using the source
  driver's `get_table_data()` and the peer's `insert_table_row()`.

- **[ ] Undo last SQL import** — After `importSqlFile`, store the executed
  statements so users can roll back by executing the inverse (DROP TABLE / DELETE).

- **[ ] User roles** — Currently all authenticated users have full access.
  Add a `role` field to `users.json` (`admin` / `readonly`) and enforce
  read-only restrictions on destructive endpoints.

- **[ ] Tokenizer DELIMITER persistence** — `split_statements()` resets the
  delimiter per call. Scripts that span multiple `importSqlFile` calls with
  custom delimiters would need stateful parsing — unlikely in practice but
  worth noting.

- **[ ] Dark mode for HTML response tables** — The returned HTML tables use
  hardcoded `border="1"` and `cellpadding` attributes which look fine in both
  modes because CSS overrides them via `.response-pane table`, but a
  full dark-mode audit should verify edge cases.

---

## 9. Dev Setup (v1.0.2)

```bash
git clone https://github.com/cloudpad9/db-viewer-python.git
cd db-viewer-python
pip install -e ".[dev]"
pip install trustme  # optional — for auto-cert feature

# Demo mode: no database required
python -m dbviewer --demo --open

# With real MySQL
python -m dbviewer --no-auth --open --data-dir /tmp/dv

# Debug logging
python -m dbviewer --no-auth --log-level debug

# HTTPS with auto-generated dev cert
python -m dbviewer --ssl-cert auto --no-auth

# Run all tests (no external DB needed)
pytest tests/ -v

# Run only v1.0.2 tests
pytest tests/test_v102.py -v

# Run only tokenizer tests
pytest tests/test_v102.py -k "TestSplitStatements" -v
```

---

*Generated: 2026-03-18 | db-viewer-python v1.0.2 | 259 tests ✅*
