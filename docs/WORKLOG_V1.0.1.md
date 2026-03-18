# WORKLOG — DB Viewer Python v1.0.1

**Date:** 2026-03-18
**Base version:** v1.0.0
**Status:** ✅ All items implemented, 204 tests passing

---

## 1. Summary

This worklog documents the implementation of all 10 backlog items selected from `WORKLOG_V1.0.0.md` sections 4.1 (High Priority) and 4.2 (Medium Priority).

**By the numbers:**

| Metric | v1.0.0 | v1.0.1 | Delta |
|--------|--------|--------|-------|
| Tests | 113 | 204 | +91 |
| Python lines (src + tests) | 3,943 | 5,723 | +1,780 |
| Frontend lines | 919 | 1,079 | +160 |
| New files | — | 4 | +4 |
| Modified files | — | 8 | — |
| API endpoints | 28 | 33 | +5 |

---

## 2. Items Implemented

### 4.1.1 — Real DB Integration Tests ✅

**Approach:** SQLite mock driver rather than `pytest-docker`. An in-process SQLite database gives full coverage of the `GenericDriver` interface without requiring any external service, making the tests trivially runnable on any machine.

**New file: `src/dbviewer/drivers/sqlite.py`** (191 lines)

`SQLiteDriver` implements the full `GenericDriver` interface against Python's built-in `sqlite3` module:
- `initialize()` — opens an in-memory or file-based SQLite connection
- All CRUD operations, pagination, column/index inspection, truncate, drop, rename, clone
- `execute_query()` — handles multi-statement queries by splitting on `;`
- Two test-only helpers: `create_table(ddl)` and `seed(table, rows)` for fixture setup

**New file: `tests/test_integration_sqlite.py`** (572 lines, 47 tests)

Test classes:
| Class | Tests | What it covers |
|-------|-------|---------------|
| `TestSQLiteDriverBasics` | 20 | initialize, get_table_names, get_table_columns, count, data, pagination, execute, column_exists, get_column_names, truncate, drop, rename, clone |
| `TestSQLiteDriverRowOps` | 2 | insert new row, update existing row (ID-keyed) |
| `TestSQLiteDriverSharedMethods` | 15 | All `GenericDriver` shared methods (concept, structure, normal columns, HTML table, counts, batch ops, alter, drop, indexes, snippets, toString) |
| `TestSQLiteAlterColumn` | 2 | insert_after_column dry-run, drop nonexistent column |
| `TestSQLiteDecimalColumns` | 1 | decimal column detection via `double` type |
| `TestAPIWithSQLite` | 7 | End-to-end API tests: concept, data, executeQuery SELECT, executeQuery DML, insertTableRow, getTableColumns, snippets, truncateTables dry-run |

**Key design decision:** The `TestAPIWithSQLite` tests patch `_build_driver` to return the pre-seeded `SQLiteDriver` instance. This exercises the full FastAPI → APIRouter → `_with_driver` → driver chain without needing network access.

---

### 4.1.2 — PostgreSQL Schema Diff ✅

**File modified: `src/dbviewer/schema_diff.py`** (+160 lines)

New function `_get_schema_postgres(handler)`:

1. Queries `information_schema.columns WHERE table_schema = 'public'` for column metadata
2. Builds `COLUMN_TYPE` string from `udt_name` + precision/scale/max_length (e.g. `varchar(255)`, `numeric(10,2)`)
3. Normalises to the same dict keys used by the MySQL schema map (`TABLE_NAME`, `COLUMN_NAME`, `COLUMN_TYPE`, `IS_NULLABLE`, `COLUMN_DEFAULT`, etc.) so `_diff_columns` / `_get_column_spec` work unchanged
4. Queries index data from `pg_class` + `pg_index` + `pg_attribute` + `pg_namespace` (the `pg_indexes` view doesn't give per-column detail needed for the diff)
5. Maps `indisunique` → `NON_UNIQUE = "0"` to match MySQL STATISTICS format

**Normalisation detail — column types:**
```
character_maximum_length present  →  udt_name(max_len)   e.g. varchar(255)
numeric_scale > 0                 →  udt_name(prec,scale) e.g. numeric(10,2)
numeric_precision present         →  udt_name(prec)       e.g. numeric(10)
otherwise                         →  udt_name             e.g. text, boolean
```

---

### 4.1.3 — MSSQL Schema Diff ✅

**File modified: `src/dbviewer/schema_diff.py`** (+120 lines)

New function `_get_schema_mssql(handler)`:

1. Queries `INFORMATION_SCHEMA.COLUMNS` joined with `INFORMATION_SCHEMA.TABLES` filtered to `TABLE_TYPE = 'BASE TABLE'` and `TABLE_SCHEMA = 'dbo'`
2. Uses `COLUMNPROPERTY(OBJECT_ID(TABLE_NAME), COLUMN_NAME, 'IsIdentity')` to detect `AUTO_INCREMENT` equivalent
3. Builds `COLUMN_TYPE` strings (e.g. `nvarchar(255)`, `decimal(18,4)`, `int`)
4. Queries indexes from `sys.tables` → `sys.indexes` → `sys.index_columns` → `sys.columns` → `sys.schemas`
5. Sets `COLUMN_KEY = 'PRI'` on primary key columns (detected via `is_primary_key`)

**Dispatch mechanism** — new `_detect_db_type(handler)` function inspects the handler's class name first (`MySQLDriver`, `PostgreSQLDriver`, `MSSQLDriver`), then falls back to `handler.settings['type']`. The top-level `_get_schema(handler)` now routes through this dispatcher:

```python
def _get_schema(handler):
    db_type = _detect_db_type(handler)
    if db_type in ("postgres", "postgresql"):  → _get_schema_postgres
    elif db_type == "mssql":                   → _get_schema_mssql
    else:                                      → _get_schema_mysql  (default)
```

This is fully backward-compatible — existing MySQL callers are unaffected.

---

### 4.1.4 — Pagination in Data View ✅

**Backend:** The existing `limitIdFrom` parameter already accepted `offset,count` format. No backend change required.

**Frontend** (`src/dbviewer/static/index.html`):

New state: `dataOffset = 0`, `dataLimit = 100`

New methods:
- `showData(isPeer, offset)` — rebuilt to compute `limitIdFrom = "${offset},${offset+limit}"` internally
- `prevPage()` — decrements `dataOffset` by `dataLimit`, calls `showData()`
- `nextPage()` — increments `dataOffset` by `dataLimit`, calls `showData()`

New UI in the Viewer toolbar (replaces the free-text `From,To` input):
```
[Data]  [New]  [100▕limit]  [◀ prev]  offset+  [▶ next]
```
- Limit input: numeric field, defaults to 100
- Offset display: shows current starting row
- Prev disabled when `dataOffset === 0`
- `dataOffset` resets to 0 on connection change

---

### 4.1.5 — Connection Diagnostics on `setActiveConnection` ✅

**New API endpoint: `POST /api/testConnection`**

Takes `{connection: int}` — same as `setActiveConnection` but does not set the connection active. Returns:
```json
{
  "success": true,
  "message": "Connected to mydb on localhost (42 tables, 38.2ms)",
  "elapsed_ms": 38.2,
  "table_count": 42
}
```
On failure:
```json
{
  "success": false,
  "message": "Connection refused to localhost:3306",
  "elapsed_ms": 5001.3,
  "diagnostics": {
    "host": "localhost", "port": 3306, "database": "mydb", "user": "root",
    "hint": "Host localhost:3306 is unreachable. Check the server address, port, and firewall rules."
  }
}
```

**New helper: `_connection_diagnostics(settings, error)`**

Classifies the error string into categories and returns a structured `diagnostics` dict with a human-readable `hint`:

| Error pattern | Hint |
|--------------|------|
| `connection refused`, `timed out`, `unreachable` | Host unreachable — check address, port, firewall |
| `access denied`, `authentication`, `login failed` | Auth failure — check username/password |
| `unknown database`, `does not exist`, `invalid catalog` | Database not found — check name |
| `ssl`, `certificate`, `tls` | SSL/TLS error |
| anything else | Generic: server running + settings correct |

**`setActiveConnection` also enhanced** — on driver build failure, includes `diagnostics` in the response so the connection dropdown shows a meaningful error.

---

### 4.2.1 — Multiple Simultaneous Users ✅

**Problem:** `active_connections` was keyed by `username` only. Two browser tabs logged in as the same user would overwrite each other's active database connection on every `setActiveConnection` call.

**Solution:** Key by `"{username}:{session_id}"` where `session_id` is a random token stored in `localStorage` on the client.

**Backend changes (`src/dbviewer/api.py`):**

New module-level function:
```python
def _conn_key(username: str, session_id: str | None) -> str:
    return f"{username}:{session_id}" if session_id else username
```

`auth()` now returns `(username, session_id)` — the session ID is read from the `X-Session-Id` request header.

`get_driver()` looks up `active_connections[_conn_key(username, session_id)]`, with a fallback to the bare username key for backward compatibility.

`_with_driver()` signature updated to `(username, session_id, get_driver_fn, fn)`.

**Frontend changes (`src/dbviewer/static/index.html`):**

- On first load and on login, a session ID is generated if not already present: `Math.random().toString(36).slice(2) + Date.now().toString(36)`
- Stored in `localStorage` as `dbviewer_session_id`
- Added to every API request as `X-Session-Id` header via `authHeader` computed property
- Session ID is intentionally **not** cleared on logout — the same tab reconnects with the same session on next login, preserving its active connection state

**Behaviour:** Two tabs with the same username now maintain independent active connections. Closing a tab and reopening it reconnects to the same session.

---

### 4.2.2 — Connection CRUD UI ✅

**New API endpoints (4):**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `GET /api/connections/full` | GET | Returns full connection objects with password masked as `••••••••` |
| `POST /api/connections/add` | POST | Appends a new connection, persists to `connections.json` |
| `POST /api/connections/update` | POST | Updates a connection by index, persists |
| `POST /api/connections/delete` | POST | Removes a connection by index, persists |

Password masking in `connections/full`: the password field is replaced with `••••••••` if non-empty, `""` if empty. This allows the UI to show which connections have passwords without exposing them.

**New Pydantic models:** `ConnectionBody`, `ConnectionUpdateBody`, `ConnectionDeleteBody`

**Frontend — new "Settings" tab:**

A new `settings` tab is added to the tab switcher. It has a two-panel layout:

Left panel (42%): Connection list
- Each connection shows name, type, host:port, database
- Edit button → loads into form on the right
- Delete button (with confirmation) → removes and refreshes

Right panel (58%): Connection form
- Fields: Name, Type (select: MySQL/PostgreSQL/MSSQL), Server, Port, Database, Username, Password
- Password field uses `type="password"` and is blank by default on edit (server never sends the real password back)
- Three actions: **Add/Update**, **Test connection**, **Cancel**
- Test result displayed in a monospace box below the form (✅ or ❌ with hint)

On save, the connection list and the sidebar connection dropdown both refresh automatically.

---

### 4.2.3 — HTTPS / TLS Support ✅

**CLI additions (`src/dbviewer/cli.py`):**
```
--ssl-cert CERT_FILE    Path to SSL certificate file (.pem) for HTTPS
--ssl-key  KEY_FILE     Path to SSL private key file (.pem) for HTTPS
```

Both must be provided together. Validation is done early in `start_server()` before Uvicorn starts.

**Server changes (`src/dbviewer/server.py`):**

`start_server()` now accepts `ssl_cert` and `ssl_key` parameters.

Validation:
1. If only one of cert/key is provided → `ValueError` with clear message
2. If either file doesn't exist → `FileNotFoundError`

URL scheme in the startup banner switches from `http://` to `https://` when TLS is active:
```
  DB Viewer  →  https://localhost:9876
  TLS cert   →  /path/to/cert.pem
```

Uvicorn is invoked with `ssl_certfile` and `ssl_keyfile` kwargs when TLS is configured:
```python
uvicorn_kwargs["ssl_certfile"] = ssl_cert
uvicorn_kwargs["ssl_keyfile"] = ssl_key
```

**Usage:**
```bash
# Generate a self-signed cert for local development
openssl req -x509 -newkey rsa:4096 -keyout key.pem -out cert.pem -days 365 -nodes

# Start with TLS
dbviewer --ssl-cert cert.pem --ssl-key key.pem
```

---

### 4.2.4 — Systemd Service Generator ✅

**New file: `src/dbviewer/service.py`** (88 lines)

`write_systemd_service(host, port, data_dir, no_auth)`:
1. Locates the `dbviewer` executable (checks `~/.dbviewer/bin/dbviewer`, then `shutil.which`, then falls back to `sys.executable -m dbviewer`)
2. Builds the `ExecStart` line with all provided CLI flags
3. Creates `~/.config/systemd/user/` if it doesn't exist
4. Writes `dbviewer.service` with `[Unit]`, `[Service]`, `[Install]` sections
5. Prints activation instructions

**Service file template:**
```ini
[Unit]
Description=DB Viewer — web-based database management tool
After=network.target

[Service]
Type=simple
ExecStart=/home/user/.dbviewer/bin/dbviewer --host 0.0.0.0 --port 9876 ...
Restart=on-failure
RestartSec=5
Environment=HOME=/home/user
WorkingDirectory=/home/user

[Install]
WantedBy=default.target
```

**CLI flag added (`src/dbviewer/cli.py`):**
```
--install-service    Write a systemd user service file and exit
```

**Usage:**
```bash
dbviewer --install-service
systemctl --user daemon-reload
systemctl --user enable --now dbviewer
```

---

### 4.2.5 — Export Column Auto-Detection ✅

**New helper: `_auto_detect_column_types(rows, columns)`** in `src/dbviewer/api.py`

When the user submits an export request without specifying `decimalColumns` or `textColumns`, this function samples up to 20 rows from the result set and infers column types:

| Detection rule | Action |
|---------------|--------|
| All sampled values are Python `float` | → `decimal_columns` |
| Strings starting with `0` that are all digits (e.g. `"00123"`) | → `text_columns` |
| All-digit strings with ≥ 8 digits (phone numbers, long IDs) | → `text_columns` |

Text columns are formatted with `number_format = "@"` in Excel, preventing auto-conversion of codes like `"00123"` → `123`.

**Integration in `/api/exportQuickReportData`:**
```python
# Auto-detect when user hasn't provided explicit values
auto_decimal, auto_text = _auto_detect_column_types(rows, columns)
decimal_columns = _split(body.decimalColumns) or auto_decimal
text_columns    = _split(body.textColumns)    or auto_text
```
Explicit user values always take precedence.

---

## 3. New Files

| File | Lines | Purpose |
|------|-------|---------|
| `src/dbviewer/drivers/sqlite.py` | 191 | SQLite driver for integration testing |
| `src/dbviewer/service.py` | 88 | Systemd user service file generator |
| `tests/test_integration_sqlite.py` | 572 | 47 SQLite integration tests |
| `tests/test_v101.py` | 476 | 44 unit/integration tests for v1.0.1 additions |

---

## 4. Modified Files

| File | Lines | Key changes |
|------|-------|-------------|
| `src/dbviewer/api.py` | 679 → 889 | `_conn_key`, session_id auth, 5 new endpoints, `_auto_detect_column_types`, `_connection_diagnostics` |
| `src/dbviewer/schema_diff.py` | 231 → 436 | `_detect_db_type`, `_get_schema_postgres`, `_get_schema_mssql`, dispatch in `_get_schema` |
| `src/dbviewer/server.py` | 66 → 84 | `ssl_cert`/`ssl_key` params, TLS validation, scheme-aware banner |
| `src/dbviewer/cli.py` | 90 → 108 | `--ssl-cert`, `--ssl-key`, `--install-service` flags |
| `src/dbviewer/static/index.html` | 919 → 1,079 | Settings tab, pagination controls, session_id, `loadFullConnections`, connection form/test methods |

---

## 5. Test Coverage

| File | Tests | Module(s) covered |
|------|-------|------------------|
| `test_auth.py` | 9 | `auth.py` |
| `test_name_helper.py` | 25 | `name_helper.py` |
| `test_code_generator.py` | 20 | `code_generator.py` |
| `test_drivers.py` | 23 | `drivers/base.py` (via ConcreteDriver) |
| `test_excel_export.py` | 12 | `excel_export.py` |
| `test_schema_diff.py` | 11 | `schema_diff.py` (MySQL, mock-based) |
| `test_api.py` | 13 | `api.py` (basic routes, auth, safety) |
| `test_integration_sqlite.py` | **47** | `drivers/sqlite.py` + full driver interface + API via SQLite |
| `test_v101.py` | **44** | `_auto_detect_column_types`, `_connection_diagnostics`, `_conn_key`, Connection CRUD endpoints, `testConnection`, schema diff dispatch, `service.py`, SSL validation, `setActiveConnection` diagnostics |
| **Total** | **204** | |

---

## 6. API Endpoint Summary (post v1.0.1)

| Group | Endpoint | Added in |
|-------|----------|---------|
| Auth | `POST /api/login` | v1.0.0 |
| Connections | `GET /api/connections` | v1.0.0 |
| | `POST /api/setActiveConnection` | v1.0.0 (enhanced v1.0.1) |
| | `POST /api/testConnection` | **v1.0.1** |
| | `GET /api/connections/full` | **v1.0.1** |
| | `POST /api/connections/add` | **v1.0.1** |
| | `POST /api/connections/update` | **v1.0.1** |
| | `POST /api/connections/delete` | **v1.0.1** |
| Schema | `concept`, `structure`, `columnSearch`, `getColumnNames`, `indexes`, `describe`, `showSizes` | v1.0.0 |
| Data | `data`, `getTableColumns`, `insertTableRow` | v1.0.0 |
| Query | `executeQuery`, `toString`, `snippets`, `vue` | v1.0.0 |
| Destructive | `truncateTables`, `dropTables`, `dropIndexes`, `insertFakeData`, `renameTable`, `cloneTable`, `alterColumn`, `insertAfterColumn`, `dropColumn` | v1.0.0 |
| DB Ops | `getPeerPatch`, `copyTables`, `cloneDatabase` | v1.0.0 |
| Export | `exportQuickReportData` (enhanced v1.0.1) | v1.0.0 |
| Import | `importSqlFile` | v1.0.0 |
| AI | `sendChatMessage`, `generateCompactFormLayout` | v1.0.0 |

**Total: 33 endpoints** (28 from v1.0.0 + 5 new in v1.0.1)

---

## 7. Remaining Roadmap

Items not addressed in this release, carried forward to v1.0.2:

### High (from v1.0.0 list — now resolved)
All 5 high-priority items are complete.

### Medium (from v1.0.0 list — now resolved)
All 5 medium-priority items are complete.

### Remaining from v1.0.0 Low Priority
- **[ ] Dark mode** — CSS variable swap via `prefers-color-scheme`
- **[ ] Column ordering** — Client-side sort by clicking table headers
- **[ ] CSV export** — Alongside Excel
- **[ ] Row count badge refresh** — After INSERT/UPDATE/DELETE
- **[ ] Multi-statement import** — Proper SQL tokenizer for stored procedures
- **[ ] `--log-level` CLI flag**
- **[ ] PyPI publish** + Homebrew tap
- **[ ] `EXPLAIN ANALYZE` for PostgreSQL**

### New items identified during v1.0.1 work
- **[ ] HTTPS auto-certificate** — Use `trustme` or `mkcert` to generate a dev cert automatically when `--ssl-cert` is not provided but HTTPS is desired
- **[ ] Connection form port auto-fill** — When user selects a type (MySQL/PostgreSQL/MSSQL), auto-fill the port to the default for that type (3306 / 5432 / 1433)
- **[ ] Settings tab — user management** — Allow admin to add/change user passwords from the UI without CLI access
- **[ ] SQLiteDriver for local dev mode** — Optionally allow launching without any real database for UI development/demonstration
- **[ ] Schema diff for PostgreSQL/MSSQL: `copy_tables` and `clone_database`** — Currently these use `SHOW CREATE TABLE` which is MySQL-only; PostgreSQL/MSSQL need their own copy logic

---

## 8. Dev Setup (v1.0.1)

```bash
git clone https://github.com/cloudpad9/db-viewer-python.git
cd db-viewer-python
pip install -e ".[dev]"

# Create test user
python -m dbviewer --create-user admin admin123 --data-dir /tmp/dv

# Start (HTTP)
python -m dbviewer --no-auth --open --data-dir /tmp/dv

# Start (HTTPS with self-signed cert)
openssl req -x509 -newkey rsa:2048 -keyout /tmp/key.pem -out /tmp/cert.pem -days 30 -nodes -subj "/CN=localhost"
python -m dbviewer --ssl-cert /tmp/cert.pem --ssl-key /tmp/key.pem --data-dir /tmp/dv

# Install as systemd service
python -m dbviewer --install-service --data-dir /tmp/dv

# Run all tests (no external DB needed)
pytest tests/ -v

# Run only integration tests
pytest tests/test_integration_sqlite.py -v
```

---

*Generated: 2026-03-18 | db-viewer-python v1.0.1 | 204 tests ✅*
