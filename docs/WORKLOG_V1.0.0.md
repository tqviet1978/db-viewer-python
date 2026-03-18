# WORKLOG — DB Viewer Python v1.0.0

**Date:** 2026-03-18
**Type:** Full port — PHP → Python
**Status:** ✅ Implementation complete, all tests passing

---

## 1. Project Overview

DB Viewer is a self-hosted web-based database management tool for developers. This worklog documents the complete port of the original PHP codebase (`db-viewer.php`, `DataHelper.php`, `ExcelHelper.php`) to a modern Python/FastAPI stack.

**Original codebase:** PHP monolith (~3,900 lines across 4 files), no framework, session-based auth, `mysqli`/`sqlsrv`/`pg_connect` native drivers

**New stack:**
- Backend: Python 3.10+ / FastAPI / Uvicorn
- Frontend: Vue.js 3 (CDN) + Axios — single `index.html`, no build step
- Auth: HTTP Basic, bcrypt, fully stateless (no sessions)
- Packaging: `pyproject.toml` (setuptools), installable via `pip install`

---

## 2. Implementation Record

### Phase 1 — Project Scaffolding ✅

**Files created:**
- `pyproject.toml` — package manifest with all runtime and dev dependencies
- `README.md` — installation, usage, configuration docs
- `LICENSE` — MIT
- `install.sh` — automated installer (venv, user creation, PATH setup)
- `update.sh` — updates package and restarts systemd service if running
- Full directory structure: `src/dbviewer/`, `src/dbviewer/drivers/`, `src/dbviewer/static/`, `tests/`

**Notable decisions:**
- Used `src/` layout (PEP 517) to keep package root clean
- `install.sh` prompts for admin credentials on first install; subsequent runs skip this
- `update.sh` detects and temporarily stops a running systemd service before reinstalling

---

### Phase 2 — Config, CLI, Auth ✅

**`config.py`**
- `DATA_DIR` defaults to `~/.dbviewer/data`
- `load_json` / `save_json` — safe file I/O helpers used throughout
- `get_connections()` — reads `connections.json`
- `get_config()` — reads optional `config.json`, returns `{}` if missing
- `get_ai_config()` — merges `config.json` with `DBVIEWER_AI_*` environment variables

**`auth.py`**
- `hash_password` / `verify_password` — bcrypt, cost factor 12
- `create_user` — upsert: updates existing user or appends new one
- `verify_request(request, data_dir, no_auth)` — decodes `Authorization: Basic` header, verifies against `users.json` on every request; returns username string or raises `HTTPException(401)`
- Fully stateless: no sessions, no tokens, no expiry

**`cli.py`**
- `argparse` CLI with: `--host`, `--port`, `--data-dir`, `--no-auth`, `--open`, `--version`, `--change-password`, `--update`, `--create-user` (used by installer)
- `--change-password`: interactive prompt with confirmation
- `--create-user USERNAME PASSWORD`: non-interactive, used by `install.sh`
- `--update`: exec's `update.sh`

**Differences from PHP:**
- PHP used `$_SESSION` to track active connection — replaced with in-memory dict `active_connections[username]` in `api.py`
- PHP stored DB credentials in `database_config.php` — replaced with `connections.json`

---

### Phase 3 — Database Drivers ✅

**`drivers/base.py` — `GenericDriver` (abstract)**

All shared logic lives here (~650 lines). Key methods ported from PHP `GenericDriver` class:

| Method | Notes |
|--------|-------|
| `get_normal_table_columns(table, search)` | Excludes system columns when no search term; parses `-EXCLUDE` syntax; detects type search vs name search using extended regex (date, datetime, text, int, varchar, decimal, double, bigint, tinyint, float, char, blob, enum, timestamp) |
| `get_normalized_column_name(column)` | camelCase → UPPER_SNAKE_CASE, handles VAT/IP acronyms |
| `export_tables_as_concept(tables, search)` | Auto-normalizes if any column has mixed case |
| `export_table_structures(tables, search)` | Generates column list + Python dict snippet |
| `export_as_html_table(table, rows, cols, decimal_cols, query)` | Row index `#`, decimal formatting `f"{v:,.6f}"`, binary detection, editable cells get `data-table`/`data-column`/`data-uuid` attributes |
| `get_snippets_as_html(tables)` | Full PHP/Vue template output (ALTER, INDEX, SELECT, UPDATE, TRUNCATE, DROP, InsertOne, UpdateOne, naive-ui columns) |
| `insert_table_row(table, data)` | Detects `ID` key → UPDATE; else INSERT with default system column values (UUID, GUID, CREATION_DATE, etc.) |
| `insert_fake_data(table, n)` | Heuristic-based fake value generation by column name patterns |
| `alter_column`, `drop_column`, `insert_after_column` | Dry-run aware |
| `truncate_tables`, `drop_tables`, `drop_indexes` | Batch operations |
| `get_peer_patch_as_html`, `copy_tables`, `clone_database` | Delegate to `schema_diff.py` |

**`drivers/mysql.py`** — `pymysql`, DictCursor, utf8mb4, autocommit
**`drivers/postgres.py`** — `psycopg2`, RealDictCursor, autocommit, rollback on error
**`drivers/mssql.py`** — `pymssql`, as_dict=True, explicit commit

**SYSTEM_COLUMNS constant:**
```
ID, REFID, GUID, JSON, WFID, SSID, CREATION_DATE, LATEST_VIEW,
LATEST_UPDATE, LATEST_UPDATE_GUID, IMPORT_REF, UDID, UUID, ID_COMPANY
```

---

### Phase 4 — API Routes ✅

**`api.py`** — FastAPI `APIRouter` with 28 endpoints

All Pydantic models defined at module level (required for Pydantic v2 compatibility — models defined inside functions fail validation in v2).

**Active connection tracking:**
```python
active_connections: dict[str, dict] = {}  # {username: {connection_id: int}}
```
Per-request driver instantiation — no persistent DB connections held between requests. Every endpoint that needs a DB connection calls `_build_driver(settings)` and closes it in a `finally` block via `_with_driver()`.

**Query safety (Appendix D of SPECS):**
- Queries matching `^(DELETE|TRUNCATE|DROP)` are blocked unless the query ends with `//Confirmed`
- The suffix is stripped before execution
- Applied only in `/api/executeQuery` — dedicated endpoints (`truncateTables`, `dropTables`, etc.) use their own `confirmation` parameter

**Endpoint groups:**

| Group | Endpoints |
|-------|-----------|
| Auth | `POST /login` |
| Connections | `GET /connections`, `POST /setActiveConnection` |
| Schema | `concept`, `structure`, `columnSearch`, `getColumnNames`, `indexes`, `describe`, `showSizes` |
| Data | `data`, `getTableColumns`, `insertTableRow` |
| Query | `executeQuery`, `toString`, `snippets`, `vue` |
| Destructive | `truncateTables`, `dropTables`, `dropIndexes`, `insertFakeData`, `renameTable`, `cloneTable`, `alterColumn`, `insertAfterColumn`, `dropColumn` |
| DB Ops | `getPeerPatch`, `copyTables`, `cloneDatabase` |
| Export | `exportQuickReportData` → `StreamingResponse` (.xlsx) |
| Import | `importSqlFile` |
| AI | `sendChatMessage`, `generateCompactFormLayout` |

**AI support:** OpenAI-compatible and Anthropic API. Feature silently disabled if no `ai_api_key` in config. System prompt follows the PHP original: schema in triple backticks, `Q: <query>` response pattern, result appended as HTML table.

---

### Phase 5 — Schema Diff ✅

**`schema_diff.py`** — port of PHP `DatabaseHelper` class

`get_diff(handler, peer_handler, tables=[])`:
1. Queries `INFORMATION_SCHEMA.COLUMNS` and `INFORMATION_SCHEMA.STATISTICS` on both sides
2. Builds schema maps `{table: {columns: {...}, indexes: {...}}}`
3. Computes: new tables (→ `CREATE TABLE`), deleted tables (→ `>>> DROP TABLE`), modified tables (column and index diffs)
4. Column diffs: new (→ `ADD COLUMN`), deleted (→ `>> DROP COLUMN`), modified (→ `MODIFY COLUMN`)
5. Index diffs: new (→ `ADD INDEX`), deleted (→ `> DROP INDEX`), modified (→ `MODIFY INDEX`)

`_get_column_spec(column, settings)` — builds full column definition string with COLLATE, DEFAULT, NOT NULL, AUTO_INCREMENT, PRIMARY KEY

`copy_tables` / `clone_database` — uses `SHOW CREATE TABLE` → `DROP IF EXISTS` → create → `INSERT INTO dest SELECT * FROM source.table`

**Note:** Schema diff is MySQL-specific (uses `INFORMATION_SCHEMA` and `STATISTICS`). PostgreSQL/MSSQL would need separate implementations.

---

### Phase 6 — Excel Export ✅

**`excel_export.py`** — port of PHP `ExcelHelper` using `openpyxl`

Features:
- First column is always `#` (row index)
- `decimal_columns` → `number_format = "#,##0.000000"`
- `text_columns` → `number_format = "@"` (prevents Excel auto-conversion)
- `summable_columns` → SUM formula row at bottom
- `align_center_columns` → `Alignment(horizontal="center")`
- Custom `column_widths`
- **Sheet separation**: if `sheet_separation_column` is set, rows grouped by that column's value into named sheets + an "All" sheet
- Column width prepends index column (width 8) automatically
- Returns `BytesIO` buffer; served via `StreamingResponse` in the API

---

### Phase 7 — Name Helper & Code Generator ✅

**`name_helper.py`** — port of PHP `NameHelper`

| Function | Example |
|----------|---------|
| `friendly_name("ORDER_DATE", keep_spaces=True)` | `"Order Date"` |
| `camel_name("ORDER_DATE")` | `"OrderDate"` |
| `camel_name("ORDER_DATE", lcfirst=True)` | `"orderDate"` |
| `friendly_module("ORDER_STATUS")` | `"orderstatus"` |
| `friendly_module("ORDER_STATUS", force_hyphenated=True)` | `"order-status"` |
| `plural("Country")` | `"Countries"` |
| `plural("Status")` | `"Statuses"` |
| `plural("Items")` | `"Items"` (already plural) |
| `plural("Branch")` | `"Branches"` |

Plural logic revised from PHP original to correctly handle already-plural words (e.g. `Statuses → Statuses`, not `Statuseses`).

**`code_generator.py`** — port of PHP `VueGenerator`

`analyze_column_type(column, dbtype)` → flags dict:
- `ID_xxx` or `xxx_ID_xxx` → `is_ref=True, ref_module="xxx"`
- `gender` → `is_gender=True`
- `is_` / `has_` prefix → `is_bool=True`
- `dob` or `date` dbtype → `is_date=True`
- `int` dbtype → `is_int=True`
- `decimal`/`double` dbtype → `is_decimal=True` (+ `is_percent=True` if column ends in `_rate`)
- `code` column name → `is_readonly=True`

`generate_vue_code(table, columns)` → two Vue 3 components (Form + Panel) as a single formatted string with separator headers, ready to copy-paste.

---

### Phase 8 — FastAPI Server ✅

**`server.py`** — `create_app(data_dir, no_auth)` factory + `start_server()` launcher

- CORS middleware (all origins — intended for localhost/LAN use)
- `GET /` → serves `static/index.html`
- `StaticFiles` mounted at `/static` for any additional assets
- Browser auto-open via `threading.Timer` (1.2s delay to let Uvicorn bind first)
- `log_level="warning"` — keeps console clean; only warnings and above shown

---

### Phase 9 — Frontend ✅

**`static/index.html`** — 919-line single-file Vue.js 3 SPA

Design system: GitHub-inspired light theme (`#fff` background, `#0969da` accent, `#1a7f37` success, `#d1242f` danger, `#f6f8fa` secondary, `d0d7de` borders). Monospace font for SQL and data cells.

**Layout:**
- Left sidebar (25%): connection dropdown, refresh, table filter, multi-select table list
- Right panel (75%): vertical tab switcher (rotated 270°) + tab content area

**Tabs:**
1. **Viewer** — concept/structure/describe/data/indexes buttons, SQL query input with autocomplete and history, AI chat input, inline cell editor, New row form
2. **Operations** — query builder (SELECT/UPDATE/DELETE), column alter/drop/insert, table rename/clone, truncate/drop, fake data
3. **Databases** — peer connection selector, diff/copy/clone operations
4. **Exporter** — full Excel export form, report history panel (40% right sidebar)
5. **Importer** — SQL file path + import button
6. **AI Generator** — compact form layout generation

**Notable frontend behaviors:**
- `localStorage` persistence: `dbviewer_auth` (base64 creds), `dbviewer_activeView`, `dbviewer_queryHistory` (max 50, deduplicated), `dbviewer_reportHistory` (max 20)
- Query autocomplete: suggests table names, column names, and SQL keywords from the current word prefix
- Query history: dropdown on `▾` button; click to restore
- Inline cell editor: `click` event delegation on `.editable-cell` elements in the response pane; floating `<input id="inline-editor">` positioned over the cell; commits via UPDATE query with `//Confirmed` suffix on blur/enter
- Report history: saves full export config; click to restore all form fields at once
- 401 handling: auto-clears localStorage and shows login form

---

### Phase 10 — Tests ✅

**113 tests, 100% passing**

| File | Tests | Coverage |
|------|-------|---------|
| `test_auth.py` | 9 | hash/verify, create/load users, request verification, no-auth mode, 401 |
| `test_name_helper.py` | 25 | all name transformation functions, pluralization edge cases |
| `test_code_generator.py` | 20 | all column type flags, Vue form/panel generation, system column exclusion |
| `test_drivers.py` | 22 | system columns, normal columns filter, concept/structure export, HTML table, batch ops, alter/drop dry-run |
| `test_excel_export.py` | 12 | BytesIO output, valid XLSX, header row, index column, sum row, decimal format, sheet separation |
| `test_schema_diff.py` | 11 | column spec generation, new/deleted/modified tables and columns, index diffs, table filter |
| `test_api.py` | 14 | login success/fail, connections list, 401 enforcement, no-connection errors, frontend route, query safety (blocked + confirmed) |

---

## 3. Known Issues & Limitations

### 3.1 Current Limitations

| Issue | Impact | Notes |
|-------|--------|-------|
| Schema diff is MySQL-only | Medium | `_get_schema()` queries `INFORMATION_SCHEMA` using MySQL column names. PostgreSQL/MSSQL need separate implementations. |
| `active_connections` is in-memory | Medium | Restarting the server clears active connections for all users. In practice this is fine for single-user/small-team use. |
| No real-DB integration tests | Medium | `test_drivers.py` uses a `ConcreteDriver` mock, not a real database. MySQL/PostgreSQL/MSSQL drivers are only exercised against live DBs. |
| MSSQL `insert_table_row` uses `SCOPE_IDENTITY()` | Low | Works for most cases but may fail in edge cases involving triggers. |
| `insert_fake_data` doesn't respect column constraints | Low | Random values may violate NOT NULL, UNIQUE, or FK constraints in real tables. |
| Frontend response pane XSS | Low | `v-html` renders server-returned HTML directly. Since the server runs locally and users are authenticated, this is acceptable but worth noting. |
| No `pyproject.toml` pytest asyncio config | Low | `asyncio_mode = strict` is set in pyproject but the API tests are sync (using `TestClient`). If async tests are added later, fixtures will need `@pytest.mark.asyncio`. |
| `pymssql` install may fail on some platforms | Low | `pymssql` requires FreeTDS headers. On macOS this requires `brew install freetds`; on some Linux systems `libsybase-dev`. |

### 3.2 PHP Features Not Ported

| PHP Feature | Reason Not Ported |
|-------------|-------------------|
| `DataHelper` class (grouping, subtotals, CSV encoding, Roman numerals, Vietnamese number-words) | Not used by `db-viewer.php`; utility class for a different application |
| `openai-prompt-layout.tpl` prompt template file | Template content inlined into `generateCompactFormLayout` handler |
| `exportTableData()` writes to `mysql.html` file | Debug/batch export utility; not part of the web UI flow |
| `generateRandomRefValue()` (queries random row for FK fake data) | Replaced with random string generation to avoid circular dependencies |
| Session-based connection caching (`$_SESSION[$cachekey]`) | Replaced with in-memory dict; cache is per-process not per-session |

---

## 4. Future Work & Roadmap

### 4.1 High Priority

- **[ ] Real DB integration tests** — `pytest-docker` or test fixtures with SQLite mock driver. At minimum, spin up MySQL in CI and run the full test suite against it.
- **[ ] PostgreSQL schema diff** — Implement `_get_schema_postgres()` in `schema_diff.py` using `information_schema` and `pg_indexes` for proper cross-DB diff support.
- **[ ] MSSQL schema diff** — Implement `_get_schema_mssql()` using `sys.columns` and `sys.indexes`.
- **[ ] Pagination in data view** — Currently `limitIdFrom` accepts `offset,count` but the frontend input is a single text field. Add proper Previous/Next navigation buttons.
- **[ ] Connection test on save** — `setActiveConnection` should return a clear error with connection diagnostics (host unreachable, bad credentials, unknown database, etc.).

### 4.2 Medium Priority

- **[ ] Multiple simultaneous users** — `active_connections` is a module-level dict; concurrent users sharing a username (e.g. two browsers) will clobber each other's active connection. Consider keying by `username + session_id` or moving to a proper session store.
- **[ ] Connection CRUD UI** — Currently connections are edited by hand in `connections.json`. Add a Connections settings tab in the frontend where users can add, edit, delete, and test connections.
- **[ ] HTTPS / TLS support** — Add `--ssl-cert` and `--ssl-key` CLI options for production deployments without a reverse proxy.
- **[ ] Systemd service generator** — `dbviewer --install-service` that writes a ready-to-use `.service` file to `~/.config/systemd/user/`.
- **[ ] Export column auto-detection** — When `columns` is empty in `exportQuickReportData`, auto-detect decimal/text columns from the query result types instead of relying on user input.
- **[ ] Query syntax highlighting** — Replace the plain `<input>` query field with a lightweight code editor (e.g. CodeMirror loaded from CDN) for SQL syntax highlighting.
- **[ ] Keyboard shortcut documentation** — Add a `?` help overlay listing all keyboard shortcuts.

### 4.3 Low Priority / Nice to Have

- **[ ] Dark mode** — CSS variable swap using `prefers-color-scheme` media query.
- **[ ] Column ordering in data view** — Click column headers to sort the in-memory result set client-side.
- **[ ] Export to CSV** — Add a CSV export option alongside the Excel export.
- **[ ] Row count badge refresh** — After INSERT/UPDATE/DELETE operations, refresh the row count badge in the table list sidebar.
- **[ ] Multi-statement import** — `importSqlFile` currently splits on `;` which breaks for stored procedures and trigger definitions containing semicolons. Use a proper SQL tokenizer or delimiters.
- **[ ] `--log-level` CLI flag** — Expose Uvicorn log level as a CLI option.
- **[ ] Brew formula / pip publish** — Publish to PyPI as `dbviewer` and optionally create a Homebrew tap for macOS.
- **[ ] `EXPLAIN ANALYZE` support** — Add a dedicated button for PostgreSQL `EXPLAIN ANALYZE` (currently Explain uses MySQL syntax `EXPLAIN`).

---

## 5. File Inventory

```
db-viewer-python/
├── pyproject.toml                   # Package manifest
├── README.md                        # User documentation
├── LICENSE                          # MIT
├── install.sh                       # One-command installer
├── update.sh                        # Updater script
├── src/dbviewer/
│   ├── __init__.py                  # __version__ = "1.0.0"
│   ├── __main__.py                  # python -m dbviewer entry point
│   ├── cli.py                       # argparse CLI (9 options)
│   ├── server.py                    # FastAPI factory + Uvicorn launcher
│   ├── config.py                    # Data dir, JSON helpers, AI config
│   ├── auth.py                      # bcrypt auth, verify_request
│   ├── api.py                       # 28 API endpoints (679 lines)
│   ├── name_helper.py               # Name transformations (93 lines)
│   ├── code_generator.py            # Vue codegen (254 lines)
│   ├── schema_diff.py               # MySQL schema diff (231 lines)
│   ├── excel_export.py              # openpyxl export (153 lines)
│   ├── drivers/
│   │   ├── __init__.py
│   │   ├── base.py                  # GenericDriver (653 lines)
│   │   ├── mysql.py                 # pymysql driver
│   │   ├── postgres.py              # psycopg2 driver
│   │   └── mssql.py                 # pymssql driver
│   └── static/
│       └── index.html               # Vue.js 3 SPA (919 lines)
└── tests/
    ├── __init__.py
    ├── test_auth.py                 # 9 tests
    ├── test_name_helper.py          # 25 tests
    ├── test_code_generator.py       # 20 tests
    ├── test_drivers.py              # 22 tests
    ├── test_excel_export.py         # 12 tests
    ├── test_schema_diff.py          # 11 tests
    └── test_api.py                  # 14 tests
```

**Total:** 24 Python files, 3,943 lines of Python + 919-line frontend, 113 tests

---

## 6. Dev Setup Quickstart

```bash
git clone https://github.com/cloudpad9/db-viewer-python.git
cd db-viewer-python
pip install -e ".[dev]"

# Create a test user
python -m dbviewer --create-user admin admin123 --data-dir /tmp/dbviewer-dev

# Start without auth for development
python -m dbviewer --no-auth --port 9876 --data-dir /tmp/dbviewer-dev --open

# Run tests
pytest tests/ -v
```

**Sample `connections.json`** (`/tmp/dbviewer-dev/connections.json`):
```json
[
  {
    "name": "Local MySQL",
    "type": "mysql",
    "server": "localhost",
    "port": 3306,
    "database": "mydb",
    "user": "root",
    "password": ""
  }
]
```

**Optional AI** (`/tmp/dbviewer-dev/config.json`):
```json
{
  "ai_provider": "openai",
  "ai_api_key": "sk-...",
  "ai_model": "gpt-4-turbo"
}
```

---

*Generated: 2026-03-18 | db-viewer-python v1.0.0*
