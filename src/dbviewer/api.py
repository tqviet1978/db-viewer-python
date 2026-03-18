"""All API route handlers."""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from .auth import verify_request
from .config import get_ai_config, get_connections
from .drivers.base import GenericDriver

# In-memory active connection store: {username: {connection_id: int}}
active_connections: dict[str, dict] = {}

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


# ─── Router factory ───────────────────────────────────────────────────────────

def create_router(data_dir: str, no_auth: bool = False) -> APIRouter:
    router = APIRouter()

    def auth(request: Request) -> str:
        return verify_request(request, data_dir, no_auth)

    def get_driver(username: str) -> tuple[GenericDriver | None, str]:
        info = active_connections.get(username)
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

    # ── Connections ───────────────────────────────────────────────────────────

    @router.get("/connections")
    async def get_connections_list(request: Request):
        auth(request)   # raises HTTPException(401) if invalid — let it propagate
        connections = get_connections(data_dir)
        return {"success": True, "connections": [c.get("name", "") for c in connections]}

    @router.post("/setActiveConnection")
    async def set_active_connection(request: Request, body: SetActiveConnectionBody):
        username = auth(request)
        connections = get_connections(data_dir)
        conn_id = body.connection
        if conn_id >= len(connections):
            return {"success": False, "message": "Invalid connection"}
        driver = _build_driver(connections[conn_id])
        if isinstance(driver, str):
            return {"success": False, "message": driver}
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
            return {"success": False, "message": str(e)}
        finally:
            driver.close()

        active_connections[username] = {"connection_id": conn_id}
        return {"success": True, "tables": table_options}

    # ── Schema exploration ────────────────────────────────────────────────────

    @router.post("/concept")
    async def concept(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.export_tables_as_concept(body.tables)
        })

    @router.post("/structure")
    async def structure(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.export_table_structures(body.tables)
        })

    @router.post("/columnSearch")
    async def column_search(request: Request, body: ColumnSearchBody):
        username = auth(request)
        def run(d):
            tables = body.tables or d.get_table_names()
            return {"success": True, "html": d.export_table_structures(tables, body.column)}
        return _with_driver(username, get_driver, run)

    @router.post("/getColumnNames")
    async def get_column_names_route(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "columnNames": d.get_column_names(body.tables)
        })

    @router.post("/indexes")
    async def indexes(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.get_indexes_as_html(body.tables)
        })

    @router.post("/describe")
    async def describe(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.get_describe_as_html(body.tables)
        })

    @router.post("/showSizes")
    async def show_sizes(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.get_sizes_as_html(body.tables)
        })

    @router.post("/data")
    async def data(request: Request, body: DataBody):
        username = auth(request)
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
        return _with_driver(username, get_driver, run)

    @router.post("/getTableColumns")
    async def get_table_columns_route(request: Request, body: TableBody):
        username = auth(request)
        def run(d):
            from .drivers.base import SYSTEM_COLUMNS
            cols = d.get_table_columns(body.table)
            filtered = [c for c in cols if c.upper() not in SYSTEM_COLUMNS]
            return {"success": True, "columns": filtered}
        return _with_driver(username, get_driver, run)

    @router.post("/insertTableRow")
    async def insert_table_row(request: Request, body: InsertRowBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "id": d.insert_table_row(body.table, body.data)
        })

    @router.post("/toString")
    async def to_string(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.get_toString_as_html(body.tables)
        })

    @router.post("/snippets")
    async def snippets(request: Request, body: TablesBody):
        username = auth(request)
        return _with_driver(username, get_driver, lambda d: {
            "success": True, "html": d.get_snippets_as_html(body.tables), "isSnippet": True
        })

    @router.post("/vue")
    async def vue(request: Request, body: VueBody):
        username = auth(request)
        def run(d):
            from .code_generator import generate_vue_code
            if not body.tables:
                return {"success": False, "message": "No table selected"}
            cols = d.get_table_columns(body.tables[0])
            return {"success": True, "html": generate_vue_code(body.tables[0], cols), "isSnippet": True}
        return _with_driver(username, get_driver, run)

    # ── Execute query ─────────────────────────────────────────────────────────

    @router.post("/executeQuery")
    async def execute_query_route(request: Request, body: ExecuteQueryBody):
        username = auth(request)
        def run(d):
            query = body.query
            output_query = True
            if body.mode == "explain":
                query = f"EXPLAIN {query}"; output_query = False
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
        return _with_driver(username, get_driver, run)

    # ── Destructive operations ────────────────────────────────────────────────

    @router.post("/truncateTables")
    async def truncate_tables(request: Request, body: TruncateDropBody):
        username = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != f"truncate {len(body.tables)}":
                return {"success": False, "message": "Invalid confirmation, expect = `truncate <table_count>`"}
            return {"success": True, "html": d.truncate_tables(body.tables, body.dryRun)}
        return _with_driver(username, get_driver, run)

    @router.post("/dropTables")
    async def drop_tables(request: Request, body: TruncateDropBody):
        username = auth(request)
        def run(d):
            if not body.dryRun and body.confirmation.lower() != f"drop {len(body.tables)}":
                return {"success": False, "message": "Invalid confirmation, expect = `drop <table_count>`"}
            return {"success": True, "html": d.drop_tables(body.tables, body.dryRun)}
        return _with_driver(username, get_driver, run)

    @router.post("/dropIndexes")
    async def drop_indexes(request: Request, body: TablesBody):
        username = auth(request)
        def run(d):
            d.drop_indexes(body.tables)
            return {"success": True, "html": d.get_indexes_as_html(body.tables)}
        return _with_driver(username, get_driver, run)

    @router.post("/insertFakeData")
    async def insert_fake_data(request: Request, body: InsertFakeBody):
        username = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation, expect = `confirmed`"}
            d.insert_fake_data(body.table, 5)
            return {"success": True, "html": "Done."}
        return _with_driver(username, get_driver, run)

    @router.post("/renameTable")
    async def rename_table(request: Request, body: RenameBody):
        username = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            d.rename_table(body.table, body.newTableName)
            return {"success": True, "html": "Done."}
        return _with_driver(username, get_driver, run)

    @router.post("/cloneTable")
    async def clone_table(request: Request, body: RenameBody):
        username = auth(request)
        def run(d):
            if body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            d.clone_table(body.table, body.newTableName)
            return {"success": True, "html": "Done."}
        return _with_driver(username, get_driver, run)

    @router.post("/alterColumn")
    async def alter_column(request: Request, body: AlterColumnBody):
        username = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            return {"success": True, "html": d.alter_column(body.tables, body.column, body.newColumnName, body.newColumnType, body.dryRun)}
        return _with_driver(username, get_driver, run)

    @router.post("/insertAfterColumn")
    async def insert_after_column(request: Request, body: AlterColumnBody):
        username = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            return {"success": True, "html": d.insert_after_column(body.tables, body.column, body.newColumnName, body.newColumnType, body.dryRun)}
        return _with_driver(username, get_driver, run)

    @router.post("/dropColumn")
    async def drop_column(request: Request, body: DropColumnBody):
        username = auth(request)
        def run(d):
            if not body.tables:
                return {"success": False, "message": "No table specified"}
            if not body.dryRun and body.confirmation.lower() != "confirmed":
                return {"success": False, "message": "Invalid confirmation"}
            return {"success": True, "html": d.drop_column(body.tables, body.column, body.dryRun)}
        return _with_driver(username, get_driver, run)

    # ── Database comparison ───────────────────────────────────────────────────

    @router.post("/getPeerPatch")
    async def get_peer_patch(request: Request, body: PeerBody):
        username = auth(request)
        def run(d):
            peer, err = get_peer_driver(body.peerConnection)
            if not peer:
                return {"success": False, "message": err}
            try:
                return {"success": True, "html": d.get_peer_patch_as_html(body.tables, peer)}
            finally:
                peer.close()
        return _with_driver(username, get_driver, run)

    @router.post("/copyTables")
    async def copy_tables_endpoint(request: Request, body: CopyTablesBody):
        username = auth(request)
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
        return _with_driver(username, get_driver, run)

    @router.post("/cloneDatabase")
    async def clone_database_endpoint(request: Request, body: CloneDatabaseBody):
        username = auth(request)
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
        return _with_driver(username, get_driver, run)

    # ── Export ────────────────────────────────────────────────────────────────

    @router.post("/exportQuickReportData")
    async def export_quick_report(request: Request, body: ExportBody):
        username = auth(request)
        driver, err = get_driver(username)
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
            from .excel_export import export_to_excel
            buf = export_to_excel(
                rows=rows, columns=columns,
                column_titles=[x.strip() for x in body.columnTitles.split(",") if x.strip()],
                decimal_columns=_split(body.decimalColumns),
                text_columns=_split(body.textColumns),
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
        username = auth(request)
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
            parts = [q.strip() for q in sql.split(";") if q.strip()]
            errors = []
            for part in parts:
                _, error, _ = d.execute_query(part)
                if error:
                    errors.append(f"Error: {error}")
            note = "<br/>" + "<br/>".join(errors) if errors else ""
            return {"success": True, "html": f"Imported {len(parts)} statements.{note}"}
        return _with_driver(username, get_driver, run)

    # ── AI ────────────────────────────────────────────────────────────────────

    @router.post("/sendChatMessage")
    async def send_chat_message(request: Request, body: ChatBody):
        username = auth(request)
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
        return _with_driver(username, get_driver, run)

    @router.post("/generateCompactFormLayout")
    async def generate_compact_form_layout(request: Request, body: CompactFormBody):
        username = auth(request)
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
        return _with_driver(username, get_driver, run)

    return router


# ─── Private helpers ──────────────────────────────────────────────────────────

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


def _with_driver(username: str, get_driver_fn, fn):
    driver, err = get_driver_fn(username)
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
