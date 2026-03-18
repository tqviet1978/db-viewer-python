# Dev Setup Guide

This guide walks you through cloning the repo, installing dependencies, running the test suite, and manually testing all features in the browser.

## Requirements

- Git
- Python 3.10+
- pip
- A running MySQL, PostgreSQL, or MSSQL instance for integration testing

---

## Step 1 — Clone the repository

```bash
git clone https://github.com/cloudpad9/db-viewer-python.git
cd db-viewer-python
```

---

## Step 2 — Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate  # macOS / Linux
# .venv\Scripts\activate   # Windows
```

---

## Step 3 — Install dependencies

```bash
pip install -e ".[dev]"
```

This installs the package in editable mode along with all runtime and dev dependencies (`fastapi`, `uvicorn`, `bcrypt`, `pymysql`, `psycopg2-binary`, `pymssql`, `openpyxl`, `httpx`, `pytest`, `pytest-asyncio`).

---

## Step 4 — Configure a test database

Create a database connections file:

```bash
mkdir -p ~/.dbviewer/data
```

Edit `~/.dbviewer/data/connections.json`:

```json
[
    {
        "name": "Local MySQL",
        "type": "mysql",
        "server": "localhost",
        "port": 3306,
        "database": "test_db",
        "user": "root",
        "password": "yourpassword"
    }
]
```

Adjust the connection details to match your local database. You can add multiple connections for different database types.

---

## Step 5 — Run the test suite

```bash
pytest tests/ -v
```

To run a specific test file:

```bash
pytest tests/test_name_helper.py -v
pytest tests/test_auth.py -v
pytest tests/test_schema_diff.py -v
```

---

## Step 6 — Start the server

### No-auth mode (recommended for local development)

```bash
dbviewer --no-auth --open
```

The `--open` flag opens the browser automatically. If it doesn't open, navigate to:

```
http://localhost:9876
```

### Authenticated mode

```bash
dbviewer
```

Open http://localhost:9876 — a login dialog will appear. Use the default credentials:

```
Username: admin
Password: admin123
```

### Other options

```bash
# Use a different port if 9876 is already taken
dbviewer --no-auth --port 8080 --open

# Run without opening the browser
dbviewer --no-auth

# See all available options
dbviewer --help
```

If the `dbviewer` command is not found, run it directly with:

```bash
python -m dbviewer --no-auth --open
```

---

## Step 7 — Test in the browser

Work through the following flows in order to verify all features.

### 7.1 Connect to a database

1. Select a connection from the **Source** dropdown
2. The table list should populate with table names and row counts in parentheses
3. Use the **Search** input above the table list to filter tables by name

### 7.2 Viewer tab — Schema exploration

1. Select one or more tables in the list
2. Click **Concept** — the response pane should show column names grouped by table
3. Click **Structure** — should show column names + types, padded and formatted
4. Click **Describe** — should show DESCRIBE output as HTML tables
5. Click **Indexes** — should show index names and columns as preformatted text

### 7.3 Viewer tab — Data viewing

1. Select a table
2. Click **Data** — the response pane should show a formatted HTML table with row numbers
3. Enter `0,10` in the limit input → click **Data** — should show first 10 rows
4. Click an editable cell (NAME, TITLE, etc.) — an inline editor should appear
5. Change the value and press Enter or click away — the cell should update

### 7.4 Viewer tab — SQL execution

1. Type `SELECT * FROM your_table LIMIT 5` in the query input
2. Click **Execute** — results should appear as an HTML table with elapsed time
3. Click **Explain** — should show EXPLAIN output
4. Click **L** (last row) — should show last 5 rows by ID
5. Click **LU** (last update) — should show last 5 rows by LATEST_UPDATE
6. Try a multi-query: `SELECT COUNT(*) FROM table1; SELECT COUNT(*) FROM table2` — both results should appear

### 7.5 Viewer tab — Query safety

1. Type `DELETE FROM test_table` and click Execute — should be blocked with "Query not allowed"
2. Type `DELETE FROM test_table//Confirmed` and click Execute — should execute (use a test table!)

### 7.6 Viewer tab — Code generation

1. Select a single table
2. Click **Snippets** — should show a textarea with ALTER/SELECT/INSERT code templates
3. Click **Vue** — should show generated Vue.js component code
4. Click **To string** — should show table names in various formats

### 7.7 Operations tab — Table operations

1. Switch to the **Operations** tab
2. Select a table → enter a new name → type `confirmed` in confirmation → click **Rename**
3. Verify the table appears with the new name (click Refresh on the connection)
4. Select the renamed table → enter original name → confirm → Rename back
5. Test **Clone**: select a table, enter a name like `test_clone`, confirm, click Clone
6. Test **Truncate** (dry-run): check dry-run, select the clone, click Truncate — should show SQL
7. Test **Drop** (dry-run): check dry-run, click Drop — should show SQL

### 7.8 Operations tab — Column operations

1. Select a table in the Operations tab
2. Enter a column name in the Column input (autocomplete should work)
3. Click **Search** — should show tables containing that column
4. Enter new name/type → check dry-run → click **Alter** — should show ALTER SQL
5. Test **Insert after** (dry-run): enter an existing column, new column name + type
6. Test **Drop column** (dry-run)

### 7.9 Operations tab — Query builder

1. Select a table
2. Set operation to `SELECT * FROM`, click Execute — should show results
3. Set operation to `UPDATE`, choose SET column/value, WHERE column/value, click Execute

### 7.10 Databases tab — Schema comparison

1. Switch to the **Databases** tab
2. Select a target connection from the dropdown
3. Select some tables → click **Diff** — should show ALTER TABLE statements for differences
4. Test **Copy tables** (dry-run): check dry-run, enter `copy N` confirmation
5. Test **Clone database** (dry-run): check dry-run, enter `confirmed`

### 7.11 Exporter tab — Excel export

1. Switch to the **Exporter** tab
2. Enter a SQL query: `SELECT * FROM your_table LIMIT 20`
3. Leave other fields empty → click **Export**
4. An `.xlsx` file should download
5. Open it — should have formatted columns with row numbers
6. Test with column titles, decimal columns, and sheet separation column

### 7.12 Importer tab

1. Switch to the **Importer** tab
2. Enter a path to a `.sql` file on the server
3. Click **Import** (use a test file!)

### 7.13 AI Generator tab (if configured)

1. Ensure AI API key is configured in `~/.dbviewer/data/config.json`
2. Select tables → type a question in the AI chat input (Viewer tab)
3. Click **Send** — should show the AI's query + results
4. Switch to AI Generator tab → check dry-run → click **Generate Compact Form Layout** — should show the prompt

---

## Step 8 — Change password

To change the admin password interactively:

```bash
dbviewer --change-password
```

Follow the prompts in the terminal. After changing, restart the server and verify login works with the new password.

---

## Step 9 — Test install.sh (optional)

It is recommended to test this on a clean machine or VM to avoid affecting your current environment.

```bash
# Check bash syntax without executing
bash -n install.sh

# Run the installer — creates ~/.dbviewer/
bash install.sh
```

After installation, open a new terminal and run:

```bash
dbviewer --no-auth --open
```

To uninstall:

```bash
rm -rf ~/.dbviewer
# Remove the PATH line from ~/.bashrc and/or ~/.zshrc
```

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `ModuleNotFoundError: pymysql` | Dependencies not installed | Run `pip install -e ".[dev]"` |
| `Address already in use` on port 9876 | Another process is using the port | Run `lsof -i :9876` and kill the PID, or use `--port 8080` |
| Login dialog persists after correct credentials | API call is failing | Open DevTools (F12) → Network tab → inspect the `/api/login` response |
| Table list is empty after selecting connection | Database connection failed | Check connection settings in `connections.json`; verify the database is reachable |
| `dbviewer: command not found` | Entry point not on PATH | Use `python -m dbviewer --no-auth` instead |
| Query returns no results | Table is empty or query is wrong | Try `SELECT COUNT(*) FROM table` to verify |
| Excel export fails | Missing `openpyxl` | Run `pip install openpyxl` |
| AI features not working | API key not configured | Add API key to `~/.dbviewer/data/config.json` |
| Column autocomplete not appearing | Column names not loaded | Click on a different connection and back, or reload the page |
| Inline cell editing not saving | UPDATE query failing | Check DevTools console for errors; verify the table has a UUID column |
