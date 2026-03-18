# DB Viewer — Specification v1.0

A web-based database management and exploration tool for developers. Connects to MySQL, PostgreSQL, and MSSQL databases. Provides schema browsing, data viewing, SQL execution, schema comparison, Excel export, code generation, and AI-assisted query building — all from a single-page web interface.

This is a Python rewrite of the [original PHP version](https://github.com/cloudpad9/db-viewer). Same features, modern stack, simpler installation.

Built with **Python / FastAPI (backend)** and **Vue.js 3 (frontend)**.
Designed to be **self-hosted, simple, and fast**.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Backend — Python / FastAPI](#2-backend--python--fastapi)
3. [Frontend — Vue.js 3 SPA](#3-frontend--vuejs-3-spa)
4. [Database Drivers](#4-database-drivers)
5. [API Endpoints](#5-api-endpoints)
6. [Features — Detailed Specification](#6-features--detailed-specification)
7. [Authentication](#7-authentication)
8. [Configuration](#8-configuration)
9. [Installer & Updater](#9-installer--updater)
10. [CLI Interface](#10-cli-interface)
11. [Project Structure](#11-project-structure)
12. [Dependencies](#12-dependencies)
13. [UI Design Guidelines](#13-ui-design-guidelines)
14. [Testing](#14-testing)

---

## 1. Architecture Overview

```
Browser (Vue.js 3 SPA)
    ↓ HTTP / JSON
FastAPI Server (Python)
    ↓ Database drivers
MySQL / PostgreSQL / MSSQL
```

The application is a single FastAPI server that serves both the static frontend (a single `index.html` file with embedded Vue.js) and the JSON API. There is no separate build step for the frontend — the HTML file uses CDN-loaded Vue.js 3, Axios, and CSS.

All state is stored in:
- JSON files on disk (user accounts, connection configs)
- Browser localStorage (credentials, UI state, query history, report history)

---

## 2. Backend — Python / FastAPI

### 2.1 Server (`server.py`)

- FastAPI application with CORS middleware
- Serves the static `index.html` at the root path `/`
- Mounts all API routes under `/api`
- Runs via Uvicorn, configurable host/port
- Fully stateless — no server-side sessions

### 2.2 Module Layout

| Module | Responsibility |
|--------|---------------|
| `server.py` | FastAPI app creation, static file serving, Uvicorn launch |
| `config.py` | App-level configuration (data dir, version, defaults) |
| `auth.py` | User management, password hashing (bcrypt), credential verification |
| `api.py` | All API route handlers — the main controller |
| `drivers/base.py` | `GenericDriver` — abstract base class with shared logic |
| `drivers/mysql.py` | MySQL driver using `pymysql` |
| `drivers/postgres.py` | PostgreSQL driver using `psycopg2` |
| `drivers/mssql.py` | MSSQL driver using `pymssql` |
| `schema_diff.py` | Database schema comparison and patch generation |
| `excel_export.py` | Excel export using `openpyxl` |
| `code_generator.py` | Vue.js code generation, snippets, schema export |
| `name_helper.py` | Column/table name transformations (camelCase, friendly names, pluralization) |
| `cli.py` | CLI argument parsing and entry point |
| `__main__.py` | `python -m dbviewer` entry point |
| `__init__.py` | Package version |

### 2.3 Authentication Model

The server is **fully stateless** — there are no server-side sessions. Authentication works as follows:

1. Client sends `{username, password}` to `/api/login`
2. Server verifies against bcrypt hash in `users.json`, returns `{success: true}` or `{success: false}`
3. On success, client stores `base64(username:password)` in `localStorage`
4. Every subsequent API request includes an `Authorization: Basic <base64>` header
5. Server decodes and verifies credentials on **every request** (stateless)
6. Logout = client clears `localStorage`

This eliminates the need for session storage, token cleanup, and expiry management.

---

## 3. Frontend — Vue.js 3 SPA

### 3.1 Technology

- **Vue.js 3** loaded from CDN (Options API for simplicity)
- **Axios** for HTTP requests
- **No build step** — single `index.html` with embedded `<script>` and `<style>` blocks
- Served directly by FastAPI as a static file

### 3.2 Layout

The UI has a **two-column layout**:

**Left column (25% width):**
- Database connection selector (dropdown)
- Refresh button
- Table search/filter input
- Table list (multi-select `<select>` element showing table name + row count)

**Right column (75% width):**
- **Tab switcher** (vertical text, rotated 270°, positioned on the left edge):
  - AI Generator
  - Databases
  - Operations
  - Importer
  - Exporter
  - Viewer
- **Active tab content area** — each tab has its own toolbar buttons and a shared response pane

### 3.3 Tabs — Detailed Layout

#### 3.3.1 Viewer Tab

**Toolbar row 1:**
- Buttons: Concept, Structure, Describe, Data, New
- Input: `limitIdFrom` (text, placeholder "From,To", width 100px)
- Buttons: Indexes, Drop indexes, Truncate tables, To string, Snippets, Vue

**Toolbar row 2 (extra):**
- Column name input with autocomplete dropdown
- Column Search button
- SQL query input (wide, with autocomplete from table/column names)
- Buttons: Execute, Explain, Profiling, L (last row), LU (last update)
- Query history dropdown (appears on click, shows recent queries)

**Toolbar row 3:**
- AI chat input (wide text field, placeholder "Your question to AI chatbot...")
- Send button

**Response pane:**
- Scrollable area showing HTML tables, preformatted text, or textarea for snippets
- Inline cell editing: clicking on editable columns (NAME, TITLE, ALIAS, SHORT_NAME, ORDERING) shows an input field; on blur/enter, sends an update query

**Editor form (toggled by New button):**
- Dynamic form generated from table columns
- Shows input fields for each non-system column
- Insert/Update button (shows "Update" if ID is present)

#### 3.3.2 Operations Tab

**Toolbar row 1:**
- Buttons: Concept, Structure, Indexes, Sizes, Data
- SQL query input with autocomplete
- Execute button
- Dry-run checkbox (default: checked)
- Buttons: Truncate, Drop, Fake data
- Confirmation input

**Toolbar row 2:**
- "New name" input
- Buttons: Rename, Clone (disabled if not exactly 1 table selected)
- Confirmation input

**Toolbar row 3:**
- Column input with autocomplete
- Column Search button
- "New name" input, "New type" input
- Dry-run checkbox
- Buttons: Alter, Drop, Insert after
- Confirmation input

**Toolbar row 4 (Query Builder):**
- Operation selector: SELECT * FROM / UPDATE / DELETE FROM
- Table name (readonly, from selection)
- If UPDATE: SET column selector, = value input
- WHERE column selector, value input
- Execute button

#### 3.3.3 Databases Tab

**Toolbar:**
- Target connection selector (dropdown, same options as source)
- Buttons: Data, Diff
- Dry-run checkbox
- Buttons: Clone, Copy tables, Apply patch
- Confirmation input
- SQL query input + Execute button

#### 3.3.4 Exporter Tab

**Main form:**
- SQL query textarea (3-6 rows)
- Title input
- Columns input (comma-separated column names)
- Column titles input (comma-separated display names)
- Decimal columns input
- Text columns input
- Summable columns input
- Align center columns input
- Sheet separation column input
- Column widths input

**Actions:**
- Export button → triggers Excel file download
- "Recent history" toggle → shows saved report configs on the right side

**History panel (40% width, right side):**
- List of saved report configs
- Click to load config into form
- X button to delete

#### 3.3.5 Importer Tab

- SQL file path input
- Import button

#### 3.3.6 AI Generator Tab

**Toolbar:**
- Dry-run checkbox
- Generate Compact Form Layout button
- (Uses selected tables as context)

### 3.4 State Persistence (localStorage)

The following state is persisted in `localStorage`:
- `queryHistory` — array of recent SQL queries (deduplicated, max 50)
- `reportHistory` — array of saved export report configurations
- `activeView` — currently active tab name

### 3.5 Keyboard Shortcuts

| Key | Action |
|-----|--------|
| Enter (in query input) | Execute query |
| Enter (in AI chat input) | Send chat message |
| Up/Down (in query input) | Navigate query autocomplete suggestions |
| Escape | Close dropdowns/suggestions |

---

## 4. Database Drivers

### 4.1 Base Driver (`GenericDriver`)

All drivers inherit from `GenericDriver` and implement the following interface:

```python
class GenericDriver:
    def initialize(self, settings: dict) -> Optional[str]:
        """Connect to database. Returns error string or None on success."""

    def close(self):
        """Close connection."""

    def get_table_names(self) -> list[str]:
        """Return list of all table names."""

    def get_table_columns(self, table: str) -> dict[str, str]:
        """Return {column_name: column_type} for a table."""

    def get_column_names(self, tables: list[str]) -> list[str]:
        """Return sorted unique column names across given tables."""

    def column_exists(self, table: str, column: str) -> tuple[bool, str]:
        """Check if column exists in table. Returns (exists, existing_type)."""

    def get_table_indexes(self, table: str) -> dict[str, list[str]]:
        """Return {index_name: [column_names]} for a table."""

    def get_table_count(self, table: str) -> int:
        """Return row count for a table."""

    def get_table_data(self, table: str, offset: int = 0, limit: int = 100) -> list[dict]:
        """Return rows from a table with pagination."""

    def execute_query(self, query: str) -> tuple[Any, Optional[str], float]:
        """Execute SQL. Returns (result, error, elapsed_ms).
           result is list[dict] for SELECT, or status string for DML."""

    def truncate_table(self, table: str, dry_run: bool = False) -> str:
        """Truncate table. Returns SQL if dry_run."""

    def drop_table(self, table: str, dry_run: bool = False) -> str:
        """Drop table. Returns SQL if dry_run."""

    def rename_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        """Rename table."""

    def clone_table(self, table: str, new_name: str, dry_run: bool = False) -> str:
        """Clone table with data."""

    def insert_table_row(self, table: str, data: dict) -> int:
        """Insert or update a row. Returns row ID."""

    def alter_column(self, tables: list, column: str, new_name: str, new_type: str, dry_run: bool) -> str:
        """Alter column name/type across tables."""

    def insert_after_column(self, tables: list, column: str, new_name: str, new_type: str, dry_run: bool) -> str:
        """Add new column after existing column."""

    def drop_column(self, tables: list, column: str, dry_run: bool) -> str:
        """Drop column from tables."""

    def drop_index(self, index: str, table: str):
        """Drop a single index."""

    def insert_fake_data(self, table: str, n: int = 5):
        """Insert n rows of fake/random data."""
```

### 4.2 Shared Methods (implemented in GenericDriver)

These methods are implemented once in `GenericDriver` and work for all drivers:

| Method | Description |
|--------|-------------|
| `get_table_counts(tables)` | Batch row counts for multiple tables |
| `export_tables_as_concept(tables, search)` | Export table schemas in compact concept format |
| `export_table_structures(tables, search)` | Export detailed column types + PHP code snippets |
| `get_normal_table_columns(table, search)` | Filter columns, excluding system columns (ID, REFID, GUID, JSON, WFID, SSID, CREATION_DATE, LATEST_VIEW, LATEST_UPDATE, LATEST_UPDATE_GUID, IMPORT_REF, UDID, UUID) |
| `get_indexes_as_html(tables)` | Format indexes as preformatted text |
| `get_describe_as_html(tables)` | Run DESCRIBE for each table, return HTML tables |
| `get_sizes_as_html(tables)` | Query information_schema for table sizes |
| `get_peer_patch_as_html(tables, peer)` | Schema diff between two connections |
| `copy_tables(tables, peer, dry_run)` | Copy tables to peer database |
| `clone_database(peer, dry_run)` | Clone entire database to peer |
| `get_snippets_as_html(tables)` | Generate code snippets (PHP/Vue templates) |
| `export_as_html_table(table, rows, columns, decimal_columns, query)` | Render query results as an HTML table |
| `truncate_tables(tables, dry_run)` | Batch truncate |
| `drop_tables(tables, dry_run)` | Batch drop |
| `drop_indexes(tables)` | Drop all non-PRIMARY indexes |
| `get_normalized_column_name(column)` | Convert camelCase to UPPER_SNAKE_CASE |
| `get_decimal_columns(table)` | Find columns with double/decimal type |

### 4.3 MySQL Driver

- Uses `pymysql` library
- `SHOW TABLES` for table listing
- `SHOW COLUMNS FROM table` for columns
- `SHOW INDEX FROM table` for indexes
- UTF-8 charset on connection
- `LIMIT offset, count` for pagination

### 4.4 PostgreSQL Driver

- Uses `psycopg2` library
- `information_schema.tables WHERE table_schema = 'public'` for table listing
- `information_schema.columns` for columns
- `pg_indexes` for indexes
- `OFFSET / LIMIT` for pagination

### 4.5 MSSQL Driver

- Uses `pymssql` library
- `SYSOBJECTS WHERE xtype = 'U'` for table listing
- `INFORMATION_SCHEMA.COLUMNS` for columns
- `sys.indexes` for indexes
- `OFFSET ... ROWS FETCH NEXT ... ROWS ONLY` for pagination

---

## 5. API Endpoints

All API endpoints are under `/api`. All accept POST with JSON body and return JSON.

### 5.1 Authentication

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/login` | POST | `{username, password}` | Verifies credentials, returns `{success: true/false}` |

### 5.2 Connection Management

| Endpoint | Method | Body | Description |
|----------|--------|------|-------------|
| `/api/connections` | GET | — | Returns list of connection names |
| `/api/setActiveConnection` | POST | `{connection, reload}` | Sets active DB, returns table list |

### 5.3 Table Operations

All endpoints below require an active connection (set via `setActiveConnection`). Credentials are sent via `Authorization: Basic <base64(user:pass)>` header on every request.

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/concept` | `{tables}` | Export schema concept (column names only) |
| `/api/structure` | `{tables}` | Export schema structure (column names + types) |
| `/api/columnSearch` | `{tables, column}` | Search columns by name or type pattern |
| `/api/getColumnNames` | `{tables}` | Get unique column names across tables |
| `/api/indexes` | `{tables}` | Show indexes for selected tables |
| `/api/describe` | `{tables}` | Run DESCRIBE on selected tables |
| `/api/showSizes` | `{tables}` | Show table data/index sizes |
| `/api/data` | `{tables, limitIdFrom}` | View table data with pagination |
| `/api/getTableColumns` | `{table}` | Get non-system columns for a single table |
| `/api/executeQuery` | `{query, mode, tables}` | Execute SQL (modes: normal, explain, profiling, lastRow, lastUpdate) |
| `/api/toString` | `{tables}` | Convert table names to various string formats |
| `/api/snippets` | `{tables}` | Generate code snippets |
| `/api/vue` | `{tables}` | Generate Vue.js component code (single table) |

### 5.4 Destructive Operations

All require `confirmation` parameter. Destructive queries (DELETE, TRUNCATE, DROP) require appending `//Confirmed` in the SQL text.

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/truncateTables` | `{tables, dryRun, confirmation}` | Truncate selected tables |
| `/api/dropTables` | `{tables, dryRun, confirmation}` | Drop selected tables |
| `/api/insertFakeData` | `{table, confirmation}` | Insert 5 rows of random data |
| `/api/renameTable` | `{table, newTableName, confirmation}` | Rename a table |
| `/api/cloneTable` | `{table, newTableName, confirmation}` | Clone a table |
| `/api/alterColumn` | `{tables, column, newColumnName, newColumnType, dryRun}` | Alter column |
| `/api/insertAfterColumn` | `{tables, column, newColumnName, newColumnType, dryRun}` | Add column after |
| `/api/dropColumn` | `{tables, column, dryRun, confirmation}` | Drop column |
| `/api/dropIndexes` | `{tables}` | Drop all non-PRIMARY indexes |
| `/api/insertTableRow` | `{table, data}` | Insert/update a table row |

### 5.5 Database Comparison

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/getPeerPatch` | `{tables, peerConnection}` | Diff schema against peer DB |
| `/api/copyTables` | `{tables, peerConnection, dryRun, confirmation}` | Copy tables to peer DB |
| `/api/cloneDatabase` | `{peerConnection, dryRun, confirmation}` | Clone entire DB to peer |

### 5.6 Export

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/exportQuickReportData` | `{query, columns, columnTitles, decimalColumns, textColumns, summableColumns, alignCenterColumns, sheetSeparationColumn, columnWidths}` | Execute query and export results as Excel file |

### 5.7 Import

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/importSqlFile` | `{path}` | Import and execute SQL from a file on the server |

### 5.8 AI Features

| Endpoint | Body Parameters | Description |
|----------|----------------|-------------|
| `/api/sendChatMessage` | `{tables, message}` | AI-assisted SQL query generation (see section 6.7) |
| `/api/generateCompactFormLayout` | `{tables, dryRun}` | AI-generated form layout (see section 6.8) |

---

## 6. Features — Detailed Specification

### 6.1 Schema Exploration

**Concept view** (`concept` action):
- For each selected table, outputs `[TABLE_NAME]` followed by column names (one per line), excluding system columns
- If any column uses camelCase, all columns are normalized to UPPER_SNAKE_CASE
- Includes/excludes based on search keyword

**Structure view** (`structure` action):
- For each selected table, outputs `[TABLE_NAME]` then each column padded to 30 chars + ` | ` + column type
- Also generates a PHP array snippet showing table → column mappings
- Supports column search with include/exclude syntax (e.g., `name -ID` to find columns matching "name" but not "ID")
- Search by type: if search term looks like a type (contains `(`, or matches `date`, `datetime`, `text`), searches column types instead of names

**Describe** (`describe` action):
- Runs `DESCRIBE table` for each selected table and renders results as HTML tables

**Indexes** (`indexes` action):
- For each table, shows index name and constituent columns, formatted as preformatted text

**Sizes** (`showSizes` action):
- Queries `information_schema.tables` for data_size_kb and index_size_kb

### 6.2 Data Viewing & Editing

**Data view** (`data` action):
- For each selected table, fetches rows with pagination (default 100 rows)
- `limitIdFrom` parameter supports `offset` or `offset,end` format
- Renders as HTML tables with row numbers
- Decimal columns are auto-detected (columns with `double` type) and formatted with 6 decimal places
- Binary values are shown as `<BINARY>`
- DateTime values formatted as `dd/mm/yyyy`

**Inline cell editing:**
- Columns named NAME, TITLE, ALIAS, SHORT_NAME, ORDERING are editable
- Clicking a cell opens an inline text input
- On blur or Enter, sends an UPDATE query: `UPDATE table SET column = 'value' WHERE UUID = 'uuid'`

**New row form:**
- The "New" button toggles a dynamic form
- Form shows one text input per non-system column
- Submit calls `insertTableRow`:
  - If `ID` is present in data → UPDATE
  - If `ID` is absent → INSERT with auto-generated defaults (UUID, CREATION_DATE, etc.)

### 6.3 SQL Execution

**Query execution** (`executeQuery` action):
- Supports multiple queries separated by `;`
- Each query is executed independently
- SELECT/SHOW/DESCRIBE/EXPLAIN queries return HTML tables
- Non-SELECT queries return affected row count and elapsed time
- Destructive queries (DELETE, TRUNCATE, DROP) require `//Confirmed` suffix
- Special modes:
  - `explain` — prepends `EXPLAIN` to the query
  - `profiling` — wraps with `set profiling=1; query; show profile;`
  - `lastRow` — generates `SELECT * FROM table ORDER BY ID DESC LIMIT 5`
  - `lastUpdate` — generates `SELECT * FROM table ORDER BY LATEST_UPDATE DESC LIMIT 5`

**Query autocomplete:**
- As user types in the query input, suggestions appear from table names and column names
- Up/Down arrows navigate suggestions
- Click or Enter selects a suggestion

**Query history:**
- Stored in localStorage
- Shown as a dropdown when the query input is clicked
- Deduplicated, most recent first

### 6.4 Table Operations

All destructive operations support a `dryRun` mode that shows the SQL without executing.

| Operation | Confirmation Format |
|-----------|-------------------|
| Truncate | `truncate N` (where N = number of tables) |
| Drop tables | `drop N` |
| Insert fake data | `confirmed` |
| Rename table | `confirmed` |
| Clone table | `confirmed` |
| Drop column | `confirmed` |
| Copy tables | `copy N` |
| Clone database | `confirmed` |

**Column operations:**
- **Alter**: Change column name and/or type across multiple tables
- **Insert after**: Add a new column after an existing column
- **Drop**: Remove a column from multiple tables

**Query builder (Operations tab):**
- Visual query builder for SELECT/UPDATE/DELETE
- Dropdowns populated from table columns
- Generates and executes the query

### 6.5 Database Comparison & Sync

**Schema diff** (`getPeerPatch` action):
- Compares the schema of selected tables between the active connection and a peer connection
- Detects: new tables, deleted tables, new columns, deleted columns, modified columns, new indexes, deleted indexes, modified indexes
- Generates ALTER TABLE SQL statements to sync peer → local
- Prefixes destructive statements with `>>>` (drop table), `>>` (drop column), `>` (drop index) for visibility

**Schema comparison algorithm:**
1. Query `INFORMATION_SCHEMA.COLUMNS` and `INFORMATION_SCHEMA.STATISTICS` for both databases
2. Build a schema map: `{table: {columns: {col: settings}, indexes: {idx: settings}}}`
3. Compute set differences for tables, columns, and indexes
4. Generate appropriate ALTER/CREATE/DROP SQL

**Copy tables** (`copyTables` action):
- For each selected table: `SHOW CREATE TABLE`, then `DROP IF EXISTS` + `CREATE TABLE` + `INSERT INTO ... SELECT * FROM source.table` on the peer connection

**Clone database** (`cloneDatabase` action):
- Same as copy tables but for ALL tables in the source database

### 6.6 Excel Export

**Quick Report Export** (`exportQuickReportData` action):

Uses `openpyxl` to generate `.xlsx` files with the following features:

- Execute a SQL query to get data
- Map columns to custom titles
- Format decimal columns with 6 decimal places
- Mark text columns to prevent number auto-formatting
- Sum specified columns at the bottom
- Center-align specified columns
- Set custom column widths
- **Sheet separation**: if a separation column is specified, rows are grouped by that column's value into separate sheets, plus an "All" sheet with all data
- Auto-adds an index column (#) as the first column
- Returns the file as a downloadable response

### 6.7 AI Chat (SQL Generation)

**How it works:**
1. User selects tables and types a question in natural language
2. Server extracts the schema of selected tables in concept format
3. Builds a prompt with system messages instructing the AI to generate MySQL queries
4. Sends to an LLM API (configurable — OpenAI, Anthropic, or others)
5. Extracts the SQL query from the response (pattern: `Q: <query>`)
6. Executes the query and appends the results
7. Returns the AI response + query results as HTML

**System prompt context:**
- "You are a MySQL query expert"
- Schema is provided between triple backticks
- `ID_<ABC>` columns join to `CODE`, `DOCUMENT_NO`, or `ID` of table ABC
- Prefer LEFT JOIN, use A/B/C as aliases, use LIKE for NAME columns
- Database name and username are provided

**Configuration:**
- AI provider, API key, and model are configured via the config file or environment variables
- This feature is **optional** — if no API key is configured, the AI buttons are hidden

### 6.8 AI Form Layout Generation

**How it works:**
1. User selects tables
2. Server extracts schema and injects it into a prompt template
3. The prompt asks the AI to generate a PHP form layout array
4. If `dryRun` is true, returns the prompt itself (useful for debugging)
5. Otherwise sends to the AI and returns the response

### 6.9 Code Generation

**Snippets** (`snippets` action):
For each selected table, generates a comprehensive set of code templates:
- ALTER TABLE templates
- ADD INDEX / UNIQUE KEY templates
- SELECT / UPDATE / TRUNCATE / DROP templates
- Column list in various formats (comma-separated, quoted, PHP assignment, Vue columns)
- InsertOne / UpdateOne MongoDB-style templates
- naive-ui list column definitions

**Vue component generation** (`vue` action):
For a single table, generates two Vue 3 components:
- **Panel component**: List view with columns, data URL, formatted items
- **Form component**: Edit form with appropriate input types based on column analysis

Column type analysis:
- `ID_xxx` or `xxx_ID_xxx` → Reference select (links to another table)
- `gender` → Gender selector
- `is_` or `has_` prefix → Boolean checkbox
- `dob` or `date` type → Date picker
- `int` type → Number input
- `decimal`/`double` type → Number input (with percent if column ends in `_rate`)
- `code` column → Readonly input

---

## 7. Authentication

### 7.1 Login Flow

1. User opens the app — if not authenticated, a login form is displayed
2. User enters username and password, submits the form
3. Client sends `{username, password}` to `/api/login`
4. Server loads `users.json`, finds the user, verifies password against bcrypt hash
5. On success, returns `{success: true}`
6. Client stores `base64(username:password)` in `localStorage`
7. All subsequent API requests include `Authorization: Basic <base64>` header
8. Server decodes the header and verifies credentials on **every request**
9. If verification fails, server returns 401 — client clears localStorage and shows the login form

**The server is fully stateless.** There are no sessions, tokens, or expiry timers. This simplifies the codebase and eliminates the need for background cleanup tasks.

**Logout:** Client clears the stored credentials from `localStorage` and reloads the page.

### 7.2 No-Auth Mode

When started with `--no-auth`, all authentication checks are bypassed. The login form is hidden.

### 7.3 Data Files

| File | Format | Content |
|------|--------|---------|
| `users.json` | `[{username, password_hash}]` | User accounts |

### 7.4 Password Management

- Passwords hashed with bcrypt (cost factor 12)
- `--change-password` CLI flag prompts for username and new password interactively
- Default credentials created by installer: `admin` / `admin123`

---

## 8. Configuration

### 8.1 Database Connections File

Location: `~/.dbviewer/data/connections.json`

```json
[
    {
        "name": "Production MySQL",
        "type": "mysql",
        "server": "localhost",
        "port": 3306,
        "database": "mydb",
        "user": "root",
        "password": "secret"
    },
    {
        "name": "Dev PostgreSQL",
        "type": "postgres",
        "server": "localhost",
        "port": 5432,
        "database": "devdb",
        "user": "postgres",
        "password": "secret"
    },
    {
        "name": "Staging MSSQL",
        "type": "mssql",
        "server": "10.0.0.5",
        "port": 1433,
        "database": "staging",
        "user": "sa",
        "password": "secret"
    }
]
```

Supported `type` values: `mysql`, `postgres`, `mssql`

### 8.2 App Configuration

Location: `~/.dbviewer/data/config.json` (optional)

```json
{
    "ai_provider": "openai",
    "ai_api_key": "sk-...",
    "ai_model": "gpt-4-turbo",
    "ai_org_id": ""
}
```

Or via environment variables:
- `DBVIEWER_AI_PROVIDER`
- `DBVIEWER_AI_API_KEY`
- `DBVIEWER_AI_MODEL`

---

## 9. Installer & Updater

### 9.1 Installer (`install.sh`)

```bash
curl -fsSL https://raw.githubusercontent.com/cloudpad9/db-viewer-python/main/install.sh | bash
```

The installer:
1. Creates `~/.dbviewer/` directory
2. Clones the repository into a temp directory
3. Creates a Python virtual environment at `~/.dbviewer/.venv/`
4. Installs the package and all dependencies into the venv
5. Creates a wrapper script at `~/.dbviewer/bin/dbviewer` that activates the venv and runs the CLI
6. Adds `~/.dbviewer/bin` to PATH in `~/.bashrc` and `~/.zshrc`
7. Creates `~/.dbviewer/data/` directory
8. Prompts for admin username and password on first install
9. Creates `users.json` with bcrypt-hashed password
10. Creates a sample `connections.json`

### 9.2 Updater

```bash
dbviewer --update
```

Or:
```bash
curl -fsSL https://raw.githubusercontent.com/cloudpad9/db-viewer-python/main/update.sh | bash
```

The updater:
1. Stops the systemd service if running
2. Clones the latest code
3. Reinstalls the package into the existing venv
4. Preserves `~/.dbviewer/data/` entirely
5. Restarts the systemd service if it was running

---

## 10. CLI Interface

```
dbviewer [OPTIONS]

Options:
  --host HOST          Bind address (default: 0.0.0.0)
  --port PORT          Port number (default: 9876)
  --data-dir PATH      Data directory (default: ~/.dbviewer/data)
  --no-auth            Disable authentication
  --open               Open browser on start
  --version            Show version and exit
  --change-password    Change a user's password interactively
  --update             Update to the latest version from GitHub
```

---

## 11. Project Structure

```
db-viewer-python/
├── install.sh
├── update.sh
├── pyproject.toml
├── README.md
├── LICENSE
├── docs/
│   ├── SPECS_V1.0.md
│   ├── DEV_SETUP.md
│   └── PRODUCTION_SETUP.md
├── src/
│   └── dbviewer/
│       ├── __init__.py              # Package version
│       ├── __main__.py              # python -m dbviewer entry
│       ├── cli.py                   # CLI argument parsing
│       ├── server.py                # FastAPI app, Uvicorn launch
│       ├── config.py                # App configuration
│       ├── auth.py                  # Authentication, bcrypt verification
│       ├── api.py                   # All API route handlers
│       ├── name_helper.py           # Name transformations
│       ├── code_generator.py        # Vue/snippet code generation
│       ├── schema_diff.py           # Database schema comparison
│       ├── excel_export.py          # openpyxl Excel export
│       ├── drivers/
│       │   ├── __init__.py
│       │   ├── base.py              # GenericDriver base class
│       │   ├── mysql.py             # MySQL driver (pymysql)
│       │   ├── postgres.py          # PostgreSQL driver (psycopg2)
│       │   └── mssql.py             # MSSQL driver (pymssql)
│       └── static/
│           └── index.html           # Vue.js 3 SPA (single file)
└── tests/
    ├── test_auth.py
    ├── test_api.py
    ├── test_name_helper.py
    ├── test_code_generator.py
    ├── test_schema_diff.py
    ├── test_excel_export.py
    └── test_drivers.py
```

---

## 12. Dependencies

### 12.1 Runtime Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `fastapi` | >=0.104 | Web framework |
| `uvicorn[standard]` | >=0.24 | ASGI server |
| `bcrypt` | >=4.0 | Password hashing |
| `python-multipart` | >=0.0.6 | Form data parsing |
| `pymysql` | >=1.1 | MySQL driver |
| `psycopg2-binary` | >=2.9 | PostgreSQL driver |
| `pymssql` | >=2.2 | MSSQL driver |
| `openpyxl` | >=3.1 | Excel file generation |
| `httpx` | >=0.25 | HTTP client (for AI API calls) |

### 12.2 Dev Dependencies

| Package | Version | Purpose |
|---------|---------|---------|
| `pytest` | >=7.0 | Test framework |
| `pytest-asyncio` | >=0.21 | Async test support |
| `httpx` | >=0.25 | Test client for FastAPI |

### 12.3 Python Version

Python 3.10 or newer.

---

## 13. UI Design Guidelines

### 13.1 Design System

The UI follows a **GitHub-inspired light theme** with these characteristics:

**Typography:**
- Primary font: `-apple-system, BlinkMacSystemFont, "Segoe UI", "Noto Sans", Helvetica, Arial, sans-serif`
- Monospace font: `ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace`
- Base font size: 14px
- Response pane and SQL inputs use monospace font

**Colors:**
- Background: `#ffffff`
- Secondary background: `#f6f8fa`
- Border: `#d0d7de`
- Text primary: `#1f2328`
- Text secondary: `#656d76`
- Accent/link: `#0969da`
- Success: `#1a7f37`
- Danger: `#d1242f`
- Warning: `#9a6700`
- Button background: `#f6f8fa`
- Button border: `#1b1f2426`
- Button hover: `#f3f4f6`
- Selected/active tab: `#0969da` text with bottom border

**Icons:**
- Use inline SVG icons matching GitHub's Octicons style
- 16px default size
- Key icons needed: database, table, play (execute), refresh, download, copy, search, chevron-down, x-circle, check-circle, alert, plus, trash, pencil

**Buttons:**
- Border: 1px solid `#1b1f2426`
- Border-radius: 6px
- Padding: 5px 16px
- Font-size: 14px
- Primary buttons: green background (`#1a7f37`), white text
- Danger buttons: red border, red text (or red background for confirmed actions)
- Default: gray background (`#f6f8fa`)

**Inputs:**
- Border: 1px solid `#d0d7de`
- Border-radius: 6px
- Padding: 5px 12px
- Focus: border-color `#0969da`, box-shadow `0 0 0 3px rgba(9,105,218,0.3)`

**Tables (data display):**
- Border-collapse, 1px solid `#d0d7de`
- Header: background `#f6f8fa`, font-weight 600
- Alternating row colors: white / `#f6f8fa`
- Cell padding: 6px 13px
- Monospace font for data cells

**Layout:**
- Left panel: fixed 25% width with `#f6f8fa` background
- Right panel: 75% width
- Tab switcher: rotated text on the left edge
- Response pane: monospace font, pre-wrap, scrollable

### 13.2 Responsive Behavior

- Below 768px: stack columns vertically
- Table list becomes collapsible
- Tab switcher moves to horizontal position at top

---

## 14. Testing

### 14.1 Unit Tests

| Test File | Coverage |
|-----------|----------|
| `test_auth.py` | Password hashing, login verification, no-auth mode |
| `test_name_helper.py` | All name transformation functions |
| `test_code_generator.py` | Vue code generation, snippet generation, column type analysis |
| `test_schema_diff.py` | Schema comparison algorithm, SQL generation |
| `test_excel_export.py` | Excel file generation, formatting, multi-sheet |

### 14.2 Integration Tests

| Test File | Coverage |
|-----------|----------|
| `test_api.py` | All API endpoints via FastAPI TestClient |
| `test_drivers.py` | Driver interface tests (can use SQLite mock or real DB) |

### 14.3 Running Tests

```bash
pytest tests/ -v
```

---

## Appendix A — System Columns

The following columns are considered "system columns" and are excluded from concept/structure views and form generation:

```
ID, REFID, GUID, JSON, WFID, SSID, CREATION_DATE, LATEST_VIEW,
LATEST_UPDATE, LATEST_UPDATE_GUID, IMPORT_REF, UDID, UUID, ID_COMPANY
```

## Appendix B — Default Row Data for INSERT

When inserting a new row (without an ID), the following defaults are merged:

| Column | Default Value |
|--------|--------------|
| NOTE | `""` |
| GUID | `1` |
| JSON | `""` |
| CREATION_DATE | Current datetime |
| IMPORT_REF | `""` |
| LATEST_UPDATE | Current datetime |
| LATEST_UPDATE_GUID | `""` |
| SSID | `0` |
| UDID | `1` |
| UUID | Random 32-char hex string |

## Appendix C — Fake Data Generation Heuristics

When generating fake data, column names are matched against patterns:

| Pattern | Generated Value |
|---------|----------------|
| `uuid` | Random 32-char string |
| `udid` | `0` |
| `ID_xxx` or `xxx_ID_xxx` | Random value from referenced table |
| Contains `date` | Random date 2000–2022 |
| Ends with `no` or `number` | Random 6-char alphanumeric |
| Contains `name`, `code`, etc. | Random 10-char string |
| Contains `kgs` or `quantity` | Random int 1–100 |
| Contains `price` | Random int 20000–500000 |
| Contains `phone` | Random 10-digit number |
| Contains `time` | Random HH:MM |
| `enum` type | Random value from enum definition |
| `decimal` type | Random float 0.1–10.0 |
| Default | Random 16-char string |

## Appendix D — Query Safety Rules

- Queries containing DELETE, TRUNCATE, or DROP are blocked unless they end with `//Confirmed`
- The `//Confirmed` suffix is stripped before execution
- This applies to the `executeQuery` endpoint only
- Other dedicated endpoints (truncateTables, dropTables, etc.) use their own confirmation parameter
