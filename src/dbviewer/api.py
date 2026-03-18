"""All API route handlers."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .auth import verify_request
from .config import get_ai_config, get_connections
from .drivers.base import GenericDriver

# In-memory active connection store.
# Key: "{username}:{session_id}" — session_id is a random token stored in
# the client's localStorage alongside the Basic auth credentials.
# This allows the same username to have independent connections across
# multiple browser tabs or devices.
active_connections: dict[str, dict] = {}


def _conn_key(username: str, session_id: str | None) -> str:
    """Stable connection key for a user+session pair."""
    return f"{username}:{session_id}" if session_id else username

# ─── Pydantic models at module level (Pydantic v2 requires this) ──────────────

class LoginBody(BaseModel):
    username: str
    password: str

class SetActiveConnectionBody(BaseModel):
    connection: int = 0
    reload: bool = False

class TablesBody(BaseModel):
    tables: list[str] = []

class ColumnSearchBody(BaseModel):
    tables: list[str] = []
    column: str = ""

class DataBody(BaseModel):
    tables: list[str] = []
    limitIdFrom: str = ""

class TableBody(BaseModel):
    table: str = ""

class InsertRowBody(BaseModel):
    table: str = ""
    data: dict = {}

class ExecuteQueryBody(BaseModel):
    query: str = ""
    mode: str = ""
    tables: list[str] = []

class TruncateDropBody(BaseModel):
    tables: list[str] = []
    dryRun: bool = True
    confirmation: str = ""

class InsertFakeBody(BaseModel):
    table: str = ""
    confirmation: str = ""

class RenameBody(BaseModel):
    table: str = ""
    newTableName: str = ""
    confirmation: str = ""

class AlterColumnBody(BaseModel):
    tables: list[str] = []
    column: str = ""
    newColumnName: str = ""
    newColumnType: str = ""
    dryRun: bool = True

class DropColumnBody(BaseModel):
    tables: list[str] = []
    column: str = ""
    dryRun: bool = True
    confirmation: str = ""

class PeerBody(BaseModel):
    tables: list[str] = []
    peerConnection: int = 0

class CopyTablesBody(BaseModel):
    tables: list[str] = []
    peerConnection: int = 0
    dryRun: bool = True
    confirmation: str = ""

class CloneDatabaseBody(BaseModel):
    peerConnection: int = 0
    dryRun: bool = True
    confirmation: str = ""

class ExportBody(BaseModel):
    query: str = ""
    columns: str = ""
    columnTitles: str = ""
    decimalColumns: str = ""
    textColumns: str = ""
    summableColumns: str = ""
    alignCenterColumns: str = ""
    sheetSeparationColumn: str = ""
    columnWidths: str = ""

class ImportBody(BaseModel):
    path: str = ""

class ChatBody(BaseModel):
    tables: list[str] = []
    message: str = ""

class CompactFormBody(BaseModel):
    tables: list[str] = []
    dryRun: bool = False

class VueBody(BaseModel):
    tables: list[str] = []


class UserCreateBody(BaseModel):
    username: str
    password: str

class UserPasswordBody(BaseModel):
    username: str
    new_password: str

class UserDeleteBody(BaseModel):
    username: str


class ConnectionBody(BaseModel):
    name: str = ""
    type: str = "mysql"
    server: str = "localhost"
    port: int = 3306
    database: str = ""
    user: str = ""
    password: str = ""


class ConnectionUpdateBody(BaseModel):
    index: int
    name: str = ""
    type: str = "mysql"
    server: str = "localhost"
    port: int = 3306
    database: str = ""
    user: str = ""
    password: str = ""


class ConnectionDeleteBody(BaseModel):
    index: int


# ─── Router factory ───────────────────────────────────────────────────────────

def create_router(data_dir: str, no_auth: bool = False) -> APIRouter:
    router = APIRouter()

    def auth(request: Request) -> tuple[str, str]:
        """Returns (username, session_id). session_id may be empty string."""
        username = verify_request(request, data_dir, no_auth)
        session_id = request.headers.get("X-Session-Id", "")
        return username, session_id

    def get_driver(username: str, session_id: str = "") -> tuple[GenericDriver | None, str]:
        key = _conn_key(username, session_id)
        # Fall back to username-only key for backward compatibility
        info = active_connections.get(key) or active_connections.get(username)
        if not info:
            return None, "No active connection. Please select a connection first."
        conn_id = info.get("connection_id")
        connections = get_connections(data_dir)
        if conn_id is None or conn_id >= len(connections):
            return None, "Invalid connection ID."
        driver = _build_driver(connections[conn_id])
        if isinstance(driver, str):
            return None, driver
        return driver, ""

    def get_peer_driver(peer_id: int) -> tuple[GenericDriver | None, str]:
        connections = get_connections(data_dir)
        if peer_id >= len(connections):
            return None, "Invalid peer connection ID."
        driver = _build_driver(connections[peer_id])
        if isinstance(driver, str):
            return None, driver
        return driver, ""

    # ── Auth ──────────────────────────────────────────────────────────────────

    @router.post("/login")
    async def login(body: LoginBody):
        from .auth import load_users, verify_password
        users = load_users(data_dir)
        for user in users:
            if user.get("username") == body.username and verify_password(body.password, user.get("password_hash", "")):
                return {"success": True}
        return {"success": False, "message": "Invalid credentials"}

    # ── User management ──────────────────────────────────────────────────────

    @router.get("/users")
    async def list_users(request: Request):
        """Return list of usernames (no passwords)."""
        auth(request)
        from .auth import load_users
        users = load_users(data_dir)
        return {"success": True, "users": [u["username"] for u in users]}

    @router.post("/users/add")
    async def add_user(request: Request, body: UserCreateBody):
        """Create a new user or overwrite if the username already exists."""
        auth(request)
        body.username = body.username.strip()
        if not body.username:
            return {"success": False, "message": "Username cannot be empty"}
        if not body.password:
            return {"success": False, "message": "Password cannot be empty"}
        from .auth import create_user, load_users
        create_user(data_dir, body.username, body.password)
        users = load_users(data_dir)
        return {"success": True, "users": [u["username"] for u in users]}

    @router.post("/users/password")
    async def change_user_password(request: Request, body: UserPasswordBody):
        """Change the password for an existing user."""
        auth(request)
        body.username = body.username.strip()
        if not body.new_password:
            return {"success": False, "message": "New password cannot be empty"}
        from .auth import load_users, create_user
        users = load_users(data_dir)
        if not any(u["username"] == body.username for u in users):
            return {"success": False, "message": f"User '{body.username}' not found"}
        create_user(data_dir, body.username, body.new_password)
        return {"success": True, "message": f"Password updated for '{body.username}'"}

    @router.post("/users/delete")
    async def delete_user(request: Request, body: UserDeleteBody):
        """Delete a user. Cannot delete the last user."""
        auth(request)
        from .auth import load_users, save_users
        users = load_users(data_dir)
        remaining = [u for u in users if u["username"] != body.username]
        if len(remaining) == len(users):
            return {"success": False, "message": f"User '{body.username}' not found"}
        if not remaining:
            return {"success": False, "message": "Cannot delete the last user"}
        save_users(data_dir, remaining)
        return {"success": True, "users": [u["username"] for u in remaining]}

    # ── Connections ───────────────────────────────────────────────────────────

    @router.get("/connections")
    async def get_connections_list(request: Request):
        auth(request)   # raises HTTPException(401) if invalid — let it propagate
        connections = get_connections(data_dir)
        return {"success": True, "connections": [c.get("name", "") for c in connections]}

    @router.post("/connections/add")
    async def add_connection(request: Request, body: ConnectionBody):
        """Add a new connection to connections.json."""
        auth(request)
        from .config import get_connections as _gc, save_json
        import os
        connections = _gc(data_dir)
        new_conn = {k: v for k, v in body.model_dump().items()}
        connections.append(new_conn)
        save_json(os.path.join(data_dir, "connections.json"), connections)
        return {"success": True, "index": len(connections) - 1, "connections": [c.get("name", "") for c in connections]}

    @router.post("/connections/update")
    async def update_connection(request: Request, body: ConnectionUpdateBody):
        """Update an existing connection by index."""
        auth(request)
        from .config import get_connections as _gc, save_json
        import os
        connections = _gc(data_dir)
        if body.index < 0 or body.index >= len(connections):
            return {"success": False, "message": "Invalid connection index"}
        updated = {k: v for k, v in body.model_dump().items() if k != "index"}
        connections[body.index] = updated
        save_json(os.path.join(data_dir, "connections.json"), connections)
        return {"success": True, "connections": [c.get("name", "") for c in connections]}

    @router.post("/connections/delete")
    async def delete_connection(request: Request, body: ConnectionDeleteBody):
        """Delete a connection by index."""
        auth(request)
        from .config import get_connections as _gc, save_json
        import os
        connections = _gc(data_dir)
        if body.index < 0 or body.index >= len(connections):
            return {"success": False, "message": "Invalid connection index"}
        connections.pop(body.index)
        save_json(os.path.join(data_dir, "connections.json"), connections)
        return {"success": True, "connections": [c.get("name", "") for c in connections]}

    @router.get("/connections/full")
    async def get_connections_full(request: Request):
        """Return full connection objects (with password masked) for the settings UI."""
        auth(request)
        connections = get_connections(data_dir)
        masked = []
        for c in connections:
            entry = dict(c)
            if entry.get("password"):
                entry["password"] = "••••••••"
            masked.append(entry)
        return {"success": True, "connections": masked}

    @router.post("/setActiveConnection")
    async def set_active_connection(request: Request, body: SetActiveConnectionBody):
        username, session_id = auth(request)
        connections = get_connections(data_dir)
        conn_id = body.connection
        if conn_id >= len(connections):
            return {"success": False, "message": "Invalid connection ID"}
        settings = connections[conn_id]
        driver = _build_driver(settings)
        if isinstance(driver, str):
            # Return structured diagnostics to help the user understand what went wrong
            return {
                "success": False,
                "message": driver,
                "diagnostics": _connection_diagnostics(settings, driver),
            }
        try:
            tables = driver.get_table_names()
            counts = driver.get_table_counts(tables)
            table_options = [
                {
                    "table": t,
                    "title": f"{t} ({counts[t]})" if counts.get(t, 0) > 0 else t,
                    "count": counts.get(t, 0),
                }
                for t in tables
            ]
        except Exception as e:
            return {"success": False, "message": str(e), "diagnostics": _connection_diagnostics(settings, str(e))}
        finally:
            driver.close()

        key = _conn_key(username, session_id)
        active_connections[key] = {"connection_id": conn_id}
        return {"success": True, "tables": table_options}

    @router.post("/testConnection")
    async def test_connection(request: Request, body: SetActiveConnectionBody):
        """Test a connection and return detailed diagnostics without setting it active."""
        auth(request)
        connections = get_connections(data_dir)
        conn_id = body.connection
        if conn_id >= len(connections):
            return {"success": False, "message": "Invalid connection ID"}
        settings = connections[conn_id]
        import time as _time
        t0 = _time.time()
        driver = _build_driver(settings)
        elapsed = round((_time.time() - t0) * 1000, 1)
        if isinstance(driver, str):
            return {
                "success": False,
                "message": driver,
                "elapsed_ms": elapsed,
                "diagnostics": _connection_diagnostics(settings, driver),
            }
        try:
            table_count = len(driver.get_table_names())
            elapsed = round((_time.time() - t0) * 1000, 1)
            return {
                "success": True,
                "message": f"Connected to {settings.get('database','?')} on {settings.get('server','?')} "
                           f"({table_count} tables, {elapsed}ms)",
                "elapsed_ms": elapsed,
                "table_count": table_count,
            }
        except Exception as e:
            return {"success": False, "message": str(e), "elapsed_ms": elapsed,
                    "diagnostics": _connection_diagnostics(settings, str(e))}
        finally:
            driver.close()

    # ── Schema exploration ────────────────────────────────────────────────────

    @router.post("/concept")
    async def concept(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.export_tables_as_concept(body.tables)
        })

    @router.post("/structure")
    async def structure(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.export_table_structures(body.tables)
        })

    @router.post("/columnSearch")
    async def column_search(request: Request, body: ColumnSearchBody):
        username, session_id = auth(request)
        def run(d):
            tables = body.tables or d.get_table_names()
            return {"success": True, "html": d.export_table_structures(tables, body.column)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/getColumnNames")
    async def get_column_names_route(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "columnNames": d.get_column_names(body.tables)
        })

    @router.post("/indexes")
    async def indexes(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.get_indexes_as_html(body.tables)
        })

    @router.post("/describe")
    async def describe(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.get_describe_as_html(body.tables)
        })

    @router.post("/showSizes")
    async def show_sizes(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.get_sizes_as_html(body.tables)
        })

    @router.post("/data")
    async def data(request: Request, body: DataBody):
        username, session_id = auth(request)
        def run(d):
            offset, limit = _parse_limit(body.limitIdFrom)
            content = ""
            for table in body.tables:
                rows = d.get_table_data(table, offset=offset, limit=limit)
                if not rows:
                    continue
                decimal_cols = d.get_decimal_columns(table)
                content += d.export_as_html_table(table, rows, [], decimal_cols) + "\n"
            return {"success": True, "html": content}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/getTableColumns")
    async def get_table_columns_route(request: Request, body: TableBody):
        username, session_id = auth(request)
        def run(d):
            from .drivers.base import SYSTEM_COLUMNS
            cols = d.get_table_columns(body.table)
            filtered = [c for c in cols if c.upper() not in SYSTEM_COLUMNS]
            return {"success": True, "columns": filtered}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/insertTableRow")
    async def insert_table_row(request: Request, body: InsertRowBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "id": d.insert_table_row(body.table, body.data)
        })

    @router.post("/toString")
    async def to_string(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.get_toString_as_html(body.tables)
        })

    @router.post("/snippets")
    async def snippets(request: Request, body: TablesBody):
        username, session_id = auth(request)
        return _with_driver(username, session_id, get_driver, lambda d: {
            "success": True, "html": d.get_snippets_as_html(body.tables), "isSnippet": True
        })

    @router.post("/vue")
    async def vue(request: Request, body: VueBody):
        username, session_id = auth(request)
        def run(d):
            from .code_generator import generate_vue_code
            if not body.tables:
                return {"success": False, "message": "No table selected"}
            cols = d.get_table_columns(body.tables[0])
            return {"success": True, "html": generate_vue_code(body.tables[0], cols), "isSnippet": True}
        return _with_driver(username, session_id, get_driver, run)

    # ── Execute query ─────────────────────────────────────────────────────────

    @router.post("/executeQuery")
    async def execute_query_route(request: Request, body: ExecuteQueryBody):
        username, session_id = auth(request)
        def run(d):
            query = body.query
            output_query = True
            if body.mode == "explain":
                # Use EXPLAIN ANALYZE for PostgreSQL, plain EXPLAIN for MySQL/others
                from .schema_diff import _detect_db_type
                explain_kw = "EXPLAIN ANALYZE" if _detect_db_type(d) in ("postgres", "postgresql") else "EXPLAIN"
                query = f"{explain_kw} {query}"; output_query = False
            elif body.mode == "profiling":
                query = f"set profiling=1; {query}; show profile;"; output_query = False
            elif body.mode == "lastRow":
                if body.tables: query = f"SELECT * FROM `{body.tables[0]}` ORDER BY ID DESC LIMIT 5"
                output_query = False
            elif body.mode == "lastUpdate":
                if body.tables: query = f"SELECT * FROM `{body.tables[0]}` ORDER BY LATEST_UPDATE DESC LIMIT 5"
                output_query = False

            htmls = []
            for part in [q.strip() for q in re.split(r";", query) if q.strip()]:
                is_confirmed = False
                m = re.match(r"^(.+?)\s*//\s*Confirmed\s*;?\s*$", part, re.I | re.S)
                if m:
                    is_confirmed = True
                    part = m.group(1).strip()

                if re.match(r"^(DELETE|TRUNCATE|DROP)", part.strip(), re.I) and not is_confirmed:
                    htmls.append("Query not allowed"); continue

                tm = re.search(r"SELECT .+? FROM\s+[`\"']?(\w+)[`\"']?", part, re.I | re.S)
                tname = tm.group(1) if tm else ""
                rows, error, elapsed_ms = d.execute_query(part)
                if error:
                    htmls.append(f'<span style="color:red">{error}</span>')
                elif isinstance(rows, str):
                    htmls.append(rows)
                else:
                    dcols = [c for c in (rows[0].keys() if rows else [])
                             if re.search(r"(^value$|_quantity$|_value$|^debit$|^credit$|_debit$|_credit$)", c, re.I)]
                    q_label = f"[{elapsed_ms:.1f}ms] {part}" if output_query else None
                    htmls.append(d.export_as_html_table(tname, rows, [], dcols, q_label))
            return {"success": True, "html": "<br/>".join(htmls)}
        return _with_driver(username, session_id, get_driver, run)

    # ── Destructive operations ────────────────────────────────────────────────

    @router.post("/truncateTables")
    async def truncate_tables(request: Request, body: TruncateDropBody):
        username, session_id = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != f"truncate {len(body.tables)}":
                return {"success": False, "message": "Invalid confirmation, expect = `truncate <table_count>`"}
            return {"success": True, "html": d.truncate_tables(body.tables, body.dryRun)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/dropTables")
    async def drop_tables(request: Request, body: TruncateDropBody):
        username, session_id = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != f"drop {len(body.tables)}":
                return {"success": False, "message": "Invalid confirmation, expect = `drop <table_count>`"}
            return {"success": True, "html": d.drop_tables(body.tables, body.dryRun)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/dropIndexes")
    async def drop_indexes(request: Request, body: TablesBody):
        username, session_id = auth(request)
        def run(d):
            d.drop_indexes(body.tables)
            return {"success": True, "html": d.get_indexes_as_html(body.tables)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/insertFakeData")
    async def insert_fake_data(request: Request, body: InsertFakeBody):
        username, session_id = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation, expect = `confirmed`"}
            d.insert_fake_data(body.table, 5)
            return {"success": True, "html": "Done."}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/renameTable")
    async def rename_table(request: Request, body: RenameBody):
        username, session_id = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            d.rename_table(body.table, body.newTableName)
            return {"success": True, "html": "Done."}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/cloneTable")
    async def clone_table(request: Request, body: RenameBody):
        username, session_id = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            d.clone_table(body.table, body.newTableName)
            return {"success": True, "html": "Done."}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/alterColumn")
    async def alter_column(request: Request, body: AlterColumnBody):
        username, session_id = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            return {"success": True, "html": d.alter_column(body.tables, body.column, body.newColumnName, body.newColumnType, body.dryRun)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/insertAfterColumn")
    async def insert_after_column(request: Request, body: AlterColumnBody):
        username, session_id = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            return {"success": True, "html": d.insert_after_column(body.tables, body.column, body.newColumnName, body.newColumnType, body.dryRun)}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/dropColumn")
    async def drop_column(request: Request, body: DropColumnBody):
        username, session_id = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            if not body.dryRun and body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            return {"success": True, "html": d.drop_column(body.tables, body.column, body.dryRun)}
        return _with_driver(username, session_id, get_driver, run)

    # ── Database comparison ───────────────────────────────────────────────────

    @router.post("/getPeerPatch")
    async def get_peer_patch(request: Request, body: PeerBody):
        username, session_id = auth(request)
        def run(d):
            peer, err = get_peer_driver(body.peerConnection)
            if not peer:
                return {"success": False, "message": err}
            try:
                return {"success": True, "html": d.get_peer_patch_as_html(body.tables, peer)}
            finally:
                peer.close()
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/copyTables")
    async def copy_tables_endpoint(request: Request, body: CopyTablesBody):
        username, session_id = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != f"copy {len(body.tables)}":
                return {"success": False, "message": "Invalid confirmation, expect = `copy <table_count>`"}
            peer, err = get_peer_driver(body.peerConnection)
            if not peer:
                return {"success": False, "message": err}
            try:
                return {"success": True, "html": d.copy_tables(body.tables, peer, body.dryRun)}
            finally:
                peer.close()
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/cloneDatabase")
    async def clone_database_endpoint(request: Request, body: CloneDatabaseBody):
        username, session_id = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation, expect = `confirmed`"}
            peer, err = get_peer_driver(body.peerConnection)
            if not peer:
                return {"success": False, "message": err}
            try:
                return {"success": True, "html": d.clone_database(peer, body.dryRun)}
            finally:
                peer.close()
        return _with_driver(username, session_id, get_driver, run)

    # ── Export ────────────────────────────────────────────────────────────────

    @router.post("/exportQuickReportData")
    async def export_quick_report(request: Request, body: ExportBody):
        username, session_id = auth(request)
        driver, err = get_driver(username, session_id)
        if not driver:
            return {"success": False, "message": err}
        try:
            if not body.query:
                return {"success": False, "message": "Query is required"}
            if not re.match(r"^SELECT", body.query.strip(), re.I):
                return {"success": False, "message": "Only SELECT queries are allowed"}
            rows, error, _ = driver.execute_query(body.query)
            if error:
                return {"success": False, "message": error}

            def _split(s: str) -> list[str]:
                s = re.sub(r"\b[a-z0-9_]+\.", "", s, flags=re.I)
                return [x.strip() for x in re.split(r"[\s,]+", s) if x.strip()]

            columns = _split(body.columns) or (list(rows[0].keys()) if rows else [])
            # Auto-detect decimal and text columns from the actual query result
            # when the user hasn't specified them explicitly
            auto_decimal, auto_text = _auto_detect_column_types(rows, columns)
            decimal_columns = _split(body.decimalColumns) or auto_decimal
            text_columns_list = _split(body.textColumns) or auto_text

            from .excel_export import export_to_excel
            buf = export_to_excel(
                rows=rows, columns=columns,
                column_titles=[x.strip() for x in body.columnTitles.split(",") if x.strip()],
                decimal_columns=decimal_columns,
                text_columns=text_columns_list,
                summable_columns=_split(body.summableColumns),
                align_center_columns=_split(body.alignCenterColumns),
                sheet_separation_column=body.sheetSeparationColumn.strip(),
                column_widths=_split(body.columnWidths),
            )
            return StreamingResponse(
                buf,
                media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                headers={"Content-Disposition": "attachment; filename=DATA.xlsx"},
            )
        except Exception as e:
            return {"success": False, "message": str(e)}
        finally:
            driver.close()

    # ── Import ────────────────────────────────────────────────────────────────

    @router.post("/importSqlFile")
    async def import_sql_file(request: Request, body: ImportBody):
        username, session_id = auth(request)
        def run(d):
            import os
            if not body.path:
                return {"success": False, "message": "File path is required"}
            if not os.path.isfile(body.path):
                return {"success": False, "message": f"File not found: {body.path}"}
            try:
                sql = open(body.path, encoding="utf-8").read()
            except Exception as e:
                return {"success": False, "message": f"Cannot read file: {e}"}
            from .sql_tokenizer import split_statements
            parts = split_statements(sql)
            ok, errors = 0, []
            for part in parts:
                _, error, _ = d.execute_query(part)
                if error:
                    errors.append(f"<span style='color:red'>Error in: {part[:80]}…<br/>{error}</span>")
                else:
                    ok += 1
            note = "<br/>".join(errors)
            summary = f"Imported {ok}/{len(parts)} statements."
            return {"success": True, "html": f"{summary}<br/>{note}" if note else summary}
        return _with_driver(username, session_id, get_driver, run)

    # ── AI ────────────────────────────────────────────────────────────────────

    @router.post("/sendChatMessage")
    async def send_chat_message(request: Request, body: ChatBody):
        username, session_id = auth(request)
        def run(d):
            if not body.message:
                return {"success": False, "message": "Message is required"}
            if not body.tables:
                return {"success": False, "message": "Select at least one table"}
            ai_cfg = get_ai_config(data_dir)
            if not ai_cfg.get("api_key"):
                return {"success": False, "message": "AI not configured (no api_key in config.json)"}
            schema = d.export_tables_as_concept(body.tables)
            html = _call_ai_chat(ai_cfg, schema, d.settings.get("database", ""), d.settings.get("user", ""), body.message)
            m = re.search(r"Q:\s*(.+?);?\s*$", html, re.I | re.S)
            if m:
                rows, error, _ = d.execute_query(m.group(1).strip())
                if error:
                    html += f"<br/>{error}"
                elif isinstance(rows, str):
                    html += f"<br/>{rows}"
                else:
                    html += "\n\n" + d.export_as_html_table("", rows, [], [])
            return {"success": True, "html": html}
        return _with_driver(username, session_id, get_driver, run)

    @router.post("/generateCompactFormLayout")
    async def generate_compact_form_layout(request: Request, body: CompactFormBody):
        username, session_id = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "Select at least one table"}
            ai_cfg = get_ai_config(data_dir)
            schema = d.export_tables_as_concept(body.tables)
            prompt = f"Given the following schema, generate a compact PHP form layout array:\n\n```\n{schema}\n```\n\nReturn a PHP array $layout = [...] with field names, labels, and types."
            if body.dryRun:
                return {"success": True, "html": prompt}
            if not ai_cfg.get("api_key"):
                return {"success": False, "message": "AI not configured"}
            return {"success": True, "html": _call_ai_generic(ai_cfg, prompt, 2000)}
        return _with_driver(username, session_id, get_driver, run)

    return router


# ─── Private helpers ──────────────────────────────────────────────────────────

def _auto_detect_column_types(rows: list[dict], columns: list[str]) -> tuple[list[str], list[str]]:
    """Infer decimal and text column types from actual query result values.

    Returns (decimal_columns, text_columns).
    - decimal_columns: numeric columns whose values contain a decimal point
    - text_columns: columns whose values look like numeric strings that Excel
      would auto-convert (e.g. leading-zero codes like "00123", long digit
      strings, phone numbers)
    """
    if not rows:
        return [], []

    decimal_cols: list[str] = []
    text_cols: list[str] = []

    for col in columns:
        sample_vals = [r.get(col) for r in rows[:20] if r.get(col) is not None]
        if not sample_vals:
            continue

        is_float = all(isinstance(v, float) for v in sample_vals)
        is_int_type = all(isinstance(v, int) for v in sample_vals)
        is_string = all(isinstance(v, str) for v in sample_vals)

        if is_float:
            decimal_cols.append(col)
        elif is_string:
            # Detect strings that look numeric but should stay as text
            numeric_str_count = sum(
                1 for v in sample_vals
                if isinstance(v, str) and v.strip().lstrip("-").replace(".", "", 1).isdigit()
            )
            leading_zero_count = sum(
                1 for v in sample_vals
                if isinstance(v, str) and len(v) > 1 and v.startswith("0") and v.isdigit()
            )
            long_digit_count = sum(
                1 for v in sample_vals
                if isinstance(v, str) and v.isdigit() and len(v) >= 8
            )
            if leading_zero_count > 0 or long_digit_count > 0:
                text_cols.append(col)

    return decimal_cols, text_cols


def _build_driver(settings: dict):
    db_type = settings.get("type", "mysql").lower()
    if db_type == "mysql":
        from .drivers.mysql import MySQLDriver; driver = MySQLDriver()
    elif db_type in ("postgres", "postgresql"):
        from .drivers.postgres import PostgreSQLDriver; driver = PostgreSQLDriver()
    elif db_type == "mssql":
        from .drivers.mssql import MSSQLDriver; driver = MSSQLDriver()
    else:
        return f"Unknown database type: {db_type}"
    error = driver.initialize(settings)
    return error if error else driver


def _with_driver(username: str, session_id: str, get_driver_fn, fn):
    driver, err = get_driver_fn(username, session_id)
    if not driver:
        return {"success": False, "message": err}
    try:
        return fn(driver)
    except HTTPException:
        raise
    except Exception as e:
        return {"success": False, "message": str(e)}
    finally:
        try:
            driver.close()
        except Exception:
            pass


def _parse_limit(limit_str: str) -> tuple[int, int]:
    parts = str(limit_str).split(",")
    try:
        offset = int(parts[0]) if parts[0].strip() else 0
    except ValueError:
        offset = 0
    try:
        to_val = int(parts[1]) if len(parts) > 1 and parts[1].strip() else None
        limit = (to_val - offset) if to_val is not None else 100
    except (ValueError, IndexError):
        limit = 100
    return max(0, offset), max(1, limit)


def _call_ai_chat(ai_cfg: dict, schema: str, db_name: str, db_user: str, message: str) -> str:
    messages = [
        {"role": "system", "content": "You are a MySQL query expert. Schema is in triple backticks."},
        {"role": "system", "content": "Return queries as `Q: <query>`. No explanation."},
        {"role": "system", "content": f"ID_<ABC> joins CODE/DOCUMENT_NO/ID of ABC. Prefer LEFT JOIN. A/B/C aliases. LIKE for NAME cols."},
        {"role": "system", "content": f"Database: `{db_name}`, user: `{db_user}`."},
        {"role": "user", "content": f"```\n{schema}\n```"},
        {"role": "user", "content": message},
    ]
    return _call_openai_compatible(ai_cfg, messages, 300)


def _call_ai_generic(ai_cfg: dict, prompt: str, max_tokens: int = 1000) -> str:
    return _call_openai_compatible(ai_cfg, [{"role": "user", "content": prompt}], max_tokens)


def _connection_diagnostics(settings: dict, error: str) -> dict:
    """Return structured diagnostics to help diagnose connection failures."""
    diag = {
        "host": settings.get("server", "?"),
        "port": settings.get("port", "?"),
        "database": settings.get("database", "?"),
        "user": settings.get("user", "?"),
        "type": settings.get("type", "?"),
        "error_lower": error.lower() if error else "",
    }
    msg = error.lower() if error else ""
    if any(k in msg for k in ("connection refused", "can't connect", "timed out", "timeout", "unreachable", "network")):
        diag["hint"] = f"Host {diag['host']}:{diag['port']} is unreachable. Check the server address, port, and firewall rules."
    elif any(k in msg for k in ("access denied", "authentication", "password", "login failed", "invalid password")):
        diag["hint"] = f"Authentication failed for user '{diag['user']}'. Check username and password."
    elif any(k in msg for k in ("unknown database", "does not exist", "database", "invalid catalog")):
        diag["hint"] = f"Database '{diag['database']}' not found. Check the database name."
    elif any(k in msg for k in ("ssl", "certificate", "tls")):
        diag["hint"] = "SSL/TLS error. Try disabling SSL or providing the correct certificates."
    else:
        diag["hint"] = "Check that the database server is running and the connection settings are correct."
    return diag


def _call_openai_compatible(ai_cfg: dict, messages: list, max_tokens: int = 1000) -> str:
    import httpx
    api_key = ai_cfg.get("api_key", "")
    model = ai_cfg.get("model", "gpt-4-turbo")
    if ai_cfg.get("provider") == "anthropic":
        system_text = "\n".join(m["content"] for m in messages if m["role"] == "system")
        user_msgs = [m for m in messages if m["role"] != "system"]
        resp = httpx.post("https://api.anthropic.com/v1/messages",
            headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            json={"model": model, "max_tokens": max_tokens, "system": system_text, "messages": user_msgs}, timeout=30)
        data = resp.json()
        return data["content"][0].get("text", "") if "content" in data else data.get("error", {}).get("message", "Error")
    else:
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        if ai_cfg.get("org_id"):
            headers["OpenAI-Organization"] = ai_cfg["org_id"]
        resp = httpx.post("https://api.openai.com/v1/chat/completions",
            headers=headers, json={"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 1}, timeout=30)
        data = resp.json()
        return data["choices"][0]["message"]["content"] if "choices" in data else data.get("error", {}).get("message", "Error")
