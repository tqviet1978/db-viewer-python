# WORKLOG — DB Viewer Python v1.0.3

**Date:** 2026-03-18
**Base version:** v1.0.2
**Status:** ✅ All items implemented, 308 tests passing

---

## 1. Summary

Two targeted items from the v1.0.2 "new items identified" list were implemented
in this release. Despite the small item count, the work touched four source
files, required careful design of a new data-copy strategy, and resulted in a
thorough CSS audit that fixed every remaining dark-mode edge case.

**By the numbers:**

| Metric | v1.0.2 | v1.0.3 | Delta |
|--------|--------|--------|-------|
| Tests | 259 | 308 | +49 |
| Python lines (src + tests) | 6,805 | 7,487 | +682 |
| Frontend lines | 1,311 | 1,345 | +34 |
| `schema_diff.py` lines | 498 | 608 | +110 |
| New test file | — | 1 | — |
| New functions | — | 4 | — |

---

## 2. Items Implemented

### Item 1 — Cross-Server `copy_tables` / `clone_database` for PostgreSQL & MSSQL ✅

**Problem:**
`copy_tables()` from v1.0.1 relied on:
```sql
INSERT INTO dest_table SELECT * FROM source_db.source_table
```
This works only on MySQL when both source and destination databases live on the
**same server** — the `source_db.table` cross-database reference is a
MySQL-only concept. PostgreSQL and MSSQL have no equivalent syntax, and even
MySQL cross-server scenarios fail silently.

**Solution: strategy-based copy with row-fetch-and-insert fallback**

Four new functions were added to `schema_diff.py`:

---

#### `_build_insert_sql(table, columns, row, db_type) → str`

Constructs a single `INSERT` statement from a Python dict row, with
backend-appropriate identifier quoting:

| `db_type` | Table quoting | Column quoting | Example |
|-----------|--------------|----------------|---------|
| `"mysql"` | `` `table` `` | `` `col` `` | `` INSERT INTO `users` (`id`, `name`) VALUES ('1', 'Alice') `` |
| `"postgres"` / `"postgresql"` | `"table"` | `"col"` | `INSERT INTO "users" ("id", "name") VALUES ('1', 'Alice')` |
| `"mssql"` | `[table]` | `[col]` | `INSERT INTO [users] ([id], [name]) VALUES ('1', 'Alice')` |

Value handling:
- `None` → `SQL NULL`
- All other values → `str(value)` with single-quote doubling (`'` → `''`) for
  SQL injection safety
- Column order in `VALUES` matches the `columns` argument, not the row dict
  key order

---

#### `_copy_table_data(table, source, dest, batch_size=500) → (int, list[str])`

Copies all rows from `source` to `dest` using paginated reads and per-row
`INSERT` statements:

```
while True:
    rows = source.get_table_data(table, offset=offset, limit=batch_size)
    if not rows: break
    for row in rows:
        sql = _build_insert_sql(table, columns, row, dest_db_type)
        dest.execute_query(sql)
    if len(rows) < batch_size: break
    offset += batch_size
```

- **Pagination:** default `batch_size=500` prevents loading entire large
  tables into Python memory
- **Error tolerance:** individual row errors are collected in a list and
  returned — copy continues even if some rows fail (e.g. constraint violations)
- **Returns:** `(rows_copied, error_messages)` — callers decide what to do
  with partial errors

---

#### `_is_same_server(handler, peer_handler) → bool`

Checks whether both handlers point to the **same database server** by comparing
`settings["server"]`, `settings["port"]`, and `settings["type"]`. Port
comparison is type-flexible (`3306` == `"3306"`).

This is used exclusively to gate the MySQL fast-path optimisation.

---

#### Revised `copy_tables()` — strategy selection

```
src_type = _detect_db_type(handler)
use_same_server = (src_type == "mysql" and _is_same_server(handler, peer_handler))

for table in tables:
    ddl = _build_create_table_from_schema(table, handler)  # DROP + CREATE

    if dry_run:
        yield DDL + row-count comment
        continue

    execute DDL on peer

    if use_same_server:
        # Fast path: INSERT INTO dest SELECT * FROM src_db.table
        peer.execute_query(ddl[2])
    else:
        # Universal path: paginated row-fetch-and-insert
        copied, errors = _copy_table_data(table, handler, peer)
        summary_lines += f"-- Copied {copied} rows to {table!r}"
```

**Strategy matrix:**

| Source | Same server? | Strategy |
|--------|-------------|----------|
| MySQL | Yes | `INSERT INTO d SELECT * FROM s.table` (fast, single query) |
| MySQL | No | Row-fetch-and-insert via `_copy_table_data` |
| PostgreSQL | Any | Row-fetch-and-insert |
| MSSQL | Any | Row-fetch-and-insert |
| SQLite | Any | Row-fetch-and-insert |

**Return value changed:** `copy_tables()` now returns a list of human-readable
summary comment lines (e.g. `"-- Copied 42 rows to 'orders' (row-fetch-and-insert)"`)
rather than raw SQL statements. This is because the live-run path no longer
produces a list of SQL to show — the DDL is executed immediately and data is
copied row by row. The `gen_html` in `drivers/base.py` renders these as
preformatted text in the response pane, which is appropriate for operational
output.

**`clone_database()` is unchanged** — it simply calls `copy_tables()` with all
table names.

**Limitation (known, documented):**
The row-fetch-and-insert approach works correctly across servers, but for very
large tables (millions of rows) it will be slower than a native bulk-copy
operation. For production bulk migrations, a dedicated ETL tool is recommended.
There is no `BEGIN TRANSACTION` wrapping the batch inserts for PostgreSQL/MSSQL
at this time — this is a future improvement.

---

### Item 2 — Dark Mode: Full HTML Response Audit ✅

**Scope of the audit:**
All server-generated HTML (from `drivers/base.py` and `api.py`) and the
frontend's inline CSS were examined for hardcoded colour values that would
render incorrectly in dark mode.

#### 2.1 Changes to `drivers/base.py`

**`export_as_html_table`** — two fixes:

| Before | After | Reason |
|--------|-------|--------|
| `<table border="1" cellspacing="5" cellpadding="5">` | `<table class="result-table">` | HTML presentation attrs cannot be overridden by CSS `color` properties; removing them lets CSS fully control border colour, cell padding, and spacing |
| `<div style="white-space: pre-wrap;margin-bottom: 10px;">{query}</div>` | `<div class="query-label">{query}</div>` | Inline `style=` takes precedence over CSS variables; moving to a class allows dark-mode variable swapping |

#### 2.2 Changes to `api.py`

Two locations emitted `<span style="color:red">`:

| File | Before | After |
|------|--------|-------|
| `executeQuery` error path | `<span style="color:red">{error}</span>` | `<span class="query-error">{error}</span>` |
| `importSqlFile` error path | `<span style='color:red'>Error in:…</span>` | `<span class='query-error'>Error in:…</span>` |

Hardcoded `color:red` renders as bright red in dark mode with a dark background
— acceptable but glaring. The new `.query-error` class uses `var(--danger)`,
which is `#d1242f` in light mode and `#f85149` in dark mode (a softer, more
readable red on the dark background).

#### 2.3 New CSS classes in `static/index.html`

Three new CSS classes were added:

**`.result-table`** — replaces all visual styling previously delivered via HTML
presentation attributes. Uses CSS variables throughout so dark mode works
automatically:
```css
.result-table {
  border-collapse: collapse; font-size: 12px;
  color: var(--text); border-color: var(--border);
}
.result-table th, .result-table td {
  border: 1px solid var(--border); padding: 5px 10px;
  color: var(--text); background: var(--bg);
}
.result-table thead th {
  background: var(--bg2); font-weight: 600;
  position: sticky; top: 0;  /* bonus: sticky header */
}
.result-table tbody tr:nth-child(odd)  td { background: var(--bg); }
.result-table tbody tr:nth-child(even) td { background: var(--bg2); }
.result-table tbody tr:hover td {
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}
```

**`.query-label`** — styled query display above result tables:
```css
.query-label {
  white-space: pre-wrap; margin-bottom: 8px; padding: 6px 8px;
  background: var(--bg2); border-left: 3px solid var(--accent);
  font-family: var(--mono); font-size: 11px; color: var(--text2);
}
```

**`.query-error`** — inline error spans:
```css
.query-error {
  color: var(--danger); display: block; margin: 2px 0;
  font-family: var(--mono); font-size: 12px;
}
```

#### 2.4 Additional CSS fixes

Three other hardcoded values were fixed during the audit:

| Rule | Before | After | Issue |
|------|--------|-------|-------|
| `button.danger:hover` | `background: #fff0f0` | `background: color-mix(in srgb, var(--danger) 12%, var(--bg))` | `#fff0f0` is always near-white; in dark mode shows as bright blotch |
| `#inline-editor` | `background: #fff` | `background: var(--bg)` | White inline editor on dark background was jarring |
| `button.primary:hover` | `background: #157530` | `filter: brightness(0.9)` | Hardcoded green; brightness filter is theme-neutral |

#### 2.5 `.response-pane` improvements

The existing `.response-pane table` rules (fallback for any legacy HTML that
may not use `.result-table`) were updated to also explicitly set
`color: var(--text)` on `th` and `td`, and a hover state was added:
```css
.response-pane table tbody tr:hover td {
  background: color-mix(in srgb, var(--accent) 8%, var(--bg));
}
```

The `.response-pane` container itself received `color: var(--text)` to ensure
any plain-text content (concept output, structure output) renders correctly in
dark mode.

#### 2.6 Regression test: `test_no_hardcoded_hex_outside_variable_definitions`

A new test parses the `<style>` block from `index.html`, strips all `:root { }` and
`@media { }` blocks (where variable definitions live), and asserts zero hex
colour literals remain in the remaining CSS. This prevents future contributors
from accidentally introducing hardcoded colours.

---

## 3. New Functions

| Function | File | Description |
|----------|------|-------------|
| `_build_insert_sql(table, cols, row, db_type)` | `schema_diff.py` | Generates a backend-quoted INSERT SQL from a row dict |
| `_copy_table_data(table, src, dst, batch_size)` | `schema_diff.py` | Paginated row-fetch-and-insert with error collection |
| `_is_same_server(handler, peer)` | `schema_diff.py` | Checks if two handlers point to the same DB server |

---

## 4. Modified Files

| File | Before | After | Changes |
|------|--------|-------|---------|
| `src/dbviewer/schema_diff.py` | 498 | 608 | 4 new functions; `copy_tables` strategy rewrite |
| `src/dbviewer/drivers/base.py` | ~660 | 653 | HTML table uses `class="result-table"` + `class="query-label"` |
| `src/dbviewer/api.py` | 960 | 960 | Error spans use `class="query-error"` |
| `src/dbviewer/static/index.html` | 1,311 | 1,345 | 3 new CSS classes; 4 hardcoded colour fixes; `.response-pane` + `.response-pane table` improvements |

---

## 5. Test Coverage

| File | Tests | Focus |
|------|-------|-------|
| `test_v103.py` | **49** | See breakdown below |
| All other test files | 259 | Unchanged from v1.0.2 |
| **Total** | **308** | |

**`test_v103.py` breakdown:**

| Class | Tests | Coverage |
|-------|-------|---------|
| `TestBuildInsertSql` | 12 | MySQL/PG/MSSQL identifier quoting, NULL, string escaping, missing columns, column order, VALUES structure |
| `TestIsSameServer` | 6 | Same host+port, different host, different port, different type, port type coercion, cross-server PG |
| `TestCopyTableData` | 6 | Full copy, correct data, empty table, pagination batch size, error tolerance (no raise), NULL round-trip |
| `TestCopyTablesStrategy` | 7 | Dry run DDL, MySQL same-server SELECT path, MySQL cross-server row-fetch, PG row-fetch, missing table warning, success summary, clone_database calls all tables |
| `TestCrossDriverCopyEndToEnd` | 2 | Full SQLite→SQLite copy with data verification; type preservation (REAL, NULL) |
| `TestDarkModeHtmlOutput` | 6 | `result-table` class present, no `border=1`, no `cellspacing`, no `cellpadding`, `query-label` class, no inline style on query div, no hardcoded colours |
| `TestDarkModeApiOutput` | 1 | Error span uses `.query-error` class, not `style="color:red"` |
| `TestDarkModeCssCoverage` | 9 | `.result-table` has CSS var, cell rules have CSS vars, `.query-label` exists, `.query-error` exists, dark vars defined, no hardcoded hex outside var defs, no `#fff0f0`, inline editor uses `var(--bg)`, primary button |

---

## 6. Remaining Roadmap

### From v1.0.2 (now resolved)
Both items from the "new items identified during v1.0.2 work" list are complete.

### Carried forward from previous releases
- **[ ] Transactional batch insert for PG/MSSQL** — wrap `_copy_table_data`
  batches in a transaction so partial failures can be rolled back cleanly
- **[ ] `trustme` cert browser trust** — add root CA to OS trust store (see v1.0.2)
- **[ ] User roles** — `admin` vs `readonly` — enforce on destructive endpoints
- **[ ] Undo last SQL import** — store inverse statements for rollback
- **[ ] Dark mode: `color-mix()` browser support** — `color-mix(in srgb, ...)` requires
  Chrome 111+ / Firefox 113+ / Safari 16.2+. Add a fallback for older browsers using
  `@supports` or a JavaScript polyfill if needed

### New items identified during v1.0.3 work
- **[ ] `copy_tables` progress indicator** — for large tables the row-fetch loop
  can run for minutes without feedback. Add a streaming SSE endpoint or a
  WebSocket channel to report copy progress to the frontend.
- **[ ] Sticky table headers scroll glitch** — The new `position: sticky; top: 0`
  on `.result-table thead th` works correctly inside the `.response-pane`
  scrollable container, but needs browser testing on Safari where sticky
  inside overflow containers has historically been unreliable.
- **[ ] `_build_insert_sql` large BLOBs** — The current implementation
  stringifies all values. Binary column values that are Python `bytes` objects
  would produce garbled SQL. A `bytes` → hex literal encoding should be added
  for MySQL (`x'...'`) and PostgreSQL (`E'\\x...'`).

---

## 7. Dev Quickstart (v1.0.3)

```bash
# Run all tests
pytest tests/ -v

# Run only v1.0.3 tests
pytest tests/test_v103.py -v

# Demonstrate cross-server copy dry-run (SQLite demo)
python -m dbviewer --demo --no-auth
# In browser: select DEMO_USERS, go to Databases tab, Diff / Copy

# Dark mode
# Click the 🌙 Dark button in the sidebar, or set OS to dark mode
```

---

*Generated: 2026-03-18 | db-viewer-python v1.0.3 | 308 tests ✅*
