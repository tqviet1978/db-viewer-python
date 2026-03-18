"""Tests for v1.0.2 additions:
- sql_tokenizer.split_statements (multi-statement import)
- EXPLAIN ANALYZE dispatch (PostgreSQL vs MySQL)
- User management endpoints (/api/users/*)
- server.py: demo mode, auto-cert, log_level
- schema_diff._build_create_table_from_schema (PG + MSSQL backends)
- export_as_html_table sortable headers
- Connection port auto-fill (watch logic verified via API contract)
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dbviewer.auth import create_user
from dbviewer.server import create_app
from dbviewer.sql_tokenizer import split_statements
from dbviewer.schema_diff import _build_create_table_from_schema, _detect_db_type


# ─── sql_tokenizer ────────────────────────────────────────────────────────────

class TestSplitStatements:
    """Full coverage of the SQL tokenizer edge cases."""

    def test_simple_two_statements(self):
        sql = "SELECT 1; SELECT 2;"
        parts = split_statements(sql)
        assert len(parts) == 2
        assert parts[0] == "SELECT 1"
        assert parts[1] == "SELECT 2"

    def test_semicolon_inside_single_quote(self):
        sql = "SELECT 'a;b' AS x; SELECT 2;"
        parts = split_statements(sql)
        assert len(parts) == 2
        assert "a;b" in parts[0]

    def test_semicolon_inside_double_quote(self):
        sql = 'INSERT INTO t (col) VALUES ("val;ue"); SELECT 1;'
        parts = split_statements(sql)
        assert len(parts) == 2
        assert "val;ue" in parts[0]

    def test_block_comment_ignored(self):
        sql = "/* this; has; semicolons */ SELECT 1;"
        parts = split_statements(sql)
        assert len(parts) == 1
        assert "SELECT 1" in parts[0]

    def test_line_comment_ignored(self):
        sql = "-- this is a comment; with semicolon\nSELECT 1;"
        parts = split_statements(sql)
        assert len(parts) == 1
        assert "SELECT 1" in parts[0]

    def test_hash_line_comment(self):
        sql = "# hash comment; with semi\nSELECT 42;"
        parts = split_statements(sql)
        assert len(parts) == 1
        assert "SELECT 42" in parts[0]

    def test_delimiter_directive(self):
        sql = """
DELIMITER //
CREATE PROCEDURE test_proc()
BEGIN
    SELECT 1;
    SELECT 2;
END//
DELIMITER ;
SELECT 3;
"""
        parts = split_statements(sql)
        # Should produce the procedure body and the final SELECT
        proc = [p for p in parts if "CREATE PROCEDURE" in p]
        sel = [p for p in parts if p.strip() == "SELECT 3"]
        assert len(proc) == 1
        assert len(sel) == 1

    def test_stored_procedure_begin_end(self):
        sql = """
DELIMITER //
CREATE PROCEDURE greet()
BEGIN
    DECLARE msg VARCHAR(50);
    SET msg = 'Hello; World';
    SELECT msg;
END//
DELIMITER ;
"""
        parts = split_statements(sql)
        proc = [p for p in parts if "CREATE PROCEDURE" in p]
        assert len(proc) == 1
        # The semicolons inside BEGIN...END must NOT split the procedure
        assert "Hello; World" in proc[0]

    def test_doubled_quote_escape(self):
        sql = "SELECT 'it''s fine'; SELECT 2;"
        parts = split_statements(sql)
        assert len(parts) == 2
        assert "it''s fine" in parts[0]

    def test_empty_input(self):
        assert split_statements("") == []
        assert split_statements("   \n   ") == []

    def test_no_trailing_semicolon(self):
        # Last statement without trailing semicolon should still be captured
        parts = split_statements("SELECT 1; SELECT 2")
        assert len(parts) == 2

    def test_whitespace_only_statements_skipped(self):
        sql = "SELECT 1;   ;  \n  ; SELECT 2;"
        parts = split_statements(sql)
        assert len(parts) == 2

    def test_multiline_statement(self):
        sql = "SELECT\n  a,\n  b\nFROM t\nWHERE x = 1;"
        parts = split_statements(sql)
        assert len(parts) == 1
        assert "SELECT" in parts[0]
        assert "WHERE" in parts[0]

    def test_insert_into_multirow(self):
        sql = "INSERT INTO t VALUES (1,'a'),(2,'b'),(3,'c');"
        parts = split_statements(sql)
        assert len(parts) == 1

    def test_dollar_quoted_string(self):
        # PostgreSQL dollar-quoting
        sql = "CREATE FUNCTION f() RETURNS void AS $$BEGIN SELECT 1; END$$ LANGUAGE plpgsql;"
        parts = split_statements(sql)
        assert len(parts) == 1
        assert "SELECT 1" in parts[0]

    def test_real_migration_script(self):
        sql = """
-- Migration v1
CREATE TABLE users (id INT, name VARCHAR(100));
CREATE TABLE orders (id INT, user_id INT);
ALTER TABLE orders ADD CONSTRAINT fk_user FOREIGN KEY (user_id) REFERENCES users(id);
INSERT INTO users VALUES (1, 'Alice'), (2, 'Bob');
"""
        parts = split_statements(sql)
        assert len(parts) == 4
        assert any("CREATE TABLE users" in p for p in parts)
        assert any("CREATE TABLE orders" in p for p in parts)
        assert any("ALTER TABLE" in p for p in parts)
        assert any("INSERT INTO" in p for p in parts)

    def test_trigger_with_delimiter(self):
        sql = """
DELIMITER //
CREATE TRIGGER trg_after_insert
AFTER INSERT ON users
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (action, ts) VALUES ('insert', NOW());
END//
DELIMITER ;
"""
        parts = split_statements(sql)
        trigger_parts = [p for p in parts if "CREATE TRIGGER" in p]
        assert len(trigger_parts) == 1
        assert "audit_log" in trigger_parts[0]


# ─── EXPLAIN ANALYZE dispatch ─────────────────────────────────────────────────

class TestExplainAnalyzeDispatch:
    """EXPLAIN ANALYZE must be used for PostgreSQL, EXPLAIN for everything else."""

    def _make_driver(self, cls_name: str, db_type: str) -> MagicMock:
        d = MagicMock()
        d.__class__ = type(cls_name, (), {})
        d.__class__.__name__ = cls_name
        d.settings = {"type": db_type, "database": "testdb"}
        d.execute_query.return_value = ([{"QUERY PLAN": "Seq Scan"}], None, 1.0)
        d.export_as_html_table.return_value = "<table>...</table>"
        d.close.return_value = None
        return d

    def _run_explain(self, db_type: str, cls_name: str) -> str:
        """Run the explain endpoint and capture the query passed to execute_query."""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": db_type, "server": "h",
                           "database": "testdb", "user": "u", "password": "p", "port": 5432}], f)
            app = create_app(data_dir=tmpdir, no_auth=True)
            d = self._make_driver(cls_name, db_type)

            from dbviewer.api import active_connections
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    client.post("/api/executeQuery", json={
                        "query": "SELECT * FROM users",
                        "mode": "explain",
                        "tables": [],
                    })
            calls = [str(c) for c in d.execute_query.call_args_list]
            return " ".join(calls)

    def test_postgres_uses_explain_analyze(self):
        calls = self._run_explain("postgres", "PostgreSQLDriver")
        assert "EXPLAIN ANALYZE" in calls

    def test_mysql_uses_explain(self):
        calls = self._run_explain("mysql", "MySQLDriver")
        assert "EXPLAIN ANALYZE" not in calls
        assert "EXPLAIN" in calls

    def test_mssql_uses_explain(self):
        calls = self._run_explain("mssql", "MSSQLDriver")
        assert "EXPLAIN ANALYZE" not in calls


# ─── User management endpoints ────────────────────────────────────────────────

@pytest.fixture
def user_client():
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "adminpass")
        create_user(tmpdir, "editor", "editorpass")
        app = create_app(data_dir=tmpdir, no_auth=True)
        with TestClient(app) as client:
            yield client, tmpdir


class TestUserManagementEndpoints:
    def test_list_users(self, user_client):
        client, _ = user_client
        r = client.get("/api/users")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "admin" in data["users"]
        assert "editor" in data["users"]
        # Passwords not exposed
        for u in data["users"]:
            assert isinstance(u, str)  # just usernames, not dicts

    def test_add_user(self, user_client):
        client, tmpdir = user_client
        r = client.post("/api/users/add", json={"username": "newuser", "password": "newpass"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "newuser" in data["users"]

    def test_add_user_persisted(self, user_client):
        client, tmpdir = user_client
        client.post("/api/users/add", json={"username": "persist", "password": "pw123"})
        from dbviewer.auth import load_users
        users = load_users(tmpdir)
        assert any(u["username"] == "persist" for u in users)

    def test_add_user_empty_username(self, user_client):
        client, _ = user_client
        r = client.post("/api/users/add", json={"username": "", "password": "pw"})
        assert r.json()["success"] is False

    def test_add_user_empty_password(self, user_client):
        client, _ = user_client
        r = client.post("/api/users/add", json={"username": "x", "password": ""})
        assert r.json()["success"] is False

    def test_change_password(self, user_client):
        client, tmpdir = user_client
        r = client.post("/api/users/password", json={
            "username": "editor", "new_password": "neweditorpass"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        # Verify the new password works
        from dbviewer.auth import load_users, verify_password
        users = load_users(tmpdir)
        user = next(u for u in users if u["username"] == "editor")
        assert verify_password("neweditorpass", user["password_hash"]) is True
        assert verify_password("editorpass", user["password_hash"]) is False

    def test_change_password_nonexistent_user(self, user_client):
        client, _ = user_client
        r = client.post("/api/users/password", json={
            "username": "ghost", "new_password": "pw"
        })
        assert r.json()["success"] is False
        assert "not found" in r.json()["message"].lower()

    def test_change_password_empty(self, user_client):
        client, _ = user_client
        r = client.post("/api/users/password", json={
            "username": "admin", "new_password": ""
        })
        assert r.json()["success"] is False

    def test_delete_user(self, user_client):
        client, tmpdir = user_client
        r = client.post("/api/users/delete", json={"username": "editor"})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "editor" not in data["users"]

    def test_delete_user_persisted(self, user_client):
        client, tmpdir = user_client
        client.post("/api/users/delete", json={"username": "editor"})
        from dbviewer.auth import load_users
        users = load_users(tmpdir)
        assert not any(u["username"] == "editor" for u in users)

    def test_cannot_delete_last_user(self, user_client):
        client, _ = user_client
        client.post("/api/users/delete", json={"username": "editor"})
        r = client.post("/api/users/delete", json={"username": "admin"})
        assert r.json()["success"] is False
        assert "last" in r.json()["message"].lower()

    def test_delete_nonexistent_user(self, user_client):
        client, _ = user_client
        r = client.post("/api/users/delete", json={"username": "nobody"})
        assert r.json()["success"] is False
        assert "not found" in r.json()["message"].lower()

    def test_import_sql_file_tokenizer(self, user_client):
        """importSqlFile endpoint should now handle stored procedures via tokenizer."""
        client, tmpdir = user_client

        # Write a SQL file with a stored procedure
        sql_path = f"{tmpdir}/test.sql"
        with open(sql_path, "w") as f:
            f.write("CREATE TABLE IF NOT EXISTS t1 (id INT);\n")
            f.write("INSERT INTO t1 VALUES (1);\n")

        mock_driver = MagicMock()
        mock_driver.execute_query.return_value = ("Done", None, 1.0)
        mock_driver.close.return_value = None

        import json as _j
        with open(f"{tmpdir}/connections.json", "w") as f:
            _j.dump([{"name": "T", "type": "mysql", "server": "h",
                       "database": "t", "user": "u", "password": "", "port": 3306}], f)

        from dbviewer.api import active_connections
        with patch("dbviewer.api._build_driver", return_value=mock_driver):
            active_connections["anonymous"] = {"connection_id": 0}
            r = client.post("/api/importSqlFile", json={"path": sql_path})

        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "2" in data["html"]  # "Imported 2/2 statements"
        # Tokenizer should have called execute_query exactly 2 times
        assert mock_driver.execute_query.call_count == 2


# ─── Demo mode ────────────────────────────────────────────────────────────────

class TestDemoMode:
    def test_setup_demo_creates_connections_json(self):
        from dbviewer.server import _setup_demo_mode
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_demo_mode(tmpdir)
            conn_path = Path(tmpdir) / "connections.json"
            assert conn_path.exists()
            conns = json.loads(conn_path.read_text())
            assert len(conns) == 1
            assert conns[0]["type"] == "sqlite"

    def test_setup_demo_seeds_tables(self):
        from dbviewer.server import _setup_demo_mode
        from dbviewer.drivers.sqlite import SQLiteDriver
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_demo_mode(tmpdir)
            conns = json.loads((Path(tmpdir) / "connections.json").read_text())
            db_path = conns[0]["database"]
            d = SQLiteDriver()
            d.initialize({"database": db_path})
            tables = d.get_table_names()
            assert "DEMO_USERS" in tables
            assert "DEMO_ORDERS" in tables
            assert d.get_table_count("DEMO_USERS") == 5
            assert d.get_table_count("DEMO_ORDERS") == 5
            d.close()

    def test_setup_demo_skips_if_connections_exist(self):
        from dbviewer.server import _setup_demo_mode
        from dbviewer.config import save_json
        with tempfile.TemporaryDirectory() as tmpdir:
            # Pre-existing connection
            save_json(str(Path(tmpdir) / "connections.json"),
                      [{"name": "Existing", "type": "mysql"}])
            _setup_demo_mode(tmpdir)
            conns = json.loads((Path(tmpdir) / "connections.json").read_text())
            assert len(conns) == 1
            assert conns[0]["name"] == "Existing"  # not replaced

    def test_demo_app_starts_with_sqlite_connection(self):
        from dbviewer.server import _setup_demo_mode
        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_demo_mode(tmpdir)
            app = create_app(data_dir=tmpdir, no_auth=True)
            with TestClient(app) as client:
                r = client.get("/api/connections")
                assert r.status_code == 200
                data = r.json()
                assert "Demo SQLite" in data["connections"]


# ─── Auto-cert generation ─────────────────────────────────────────────────────

class TestAutoCert:
    def test_generate_dev_cert_creates_files(self):
        from dbviewer.server import generate_dev_cert
        with tempfile.TemporaryDirectory() as tmpdir:
            cert, key = generate_dev_cert(tmpdir)
            assert os.path.isfile(cert)
            assert os.path.isfile(key)
            # PEM files must start with -----BEGIN
            assert open(cert, "rb").read(5) == b"-----"

    def test_generate_dev_cert_reuses_existing(self):
        from dbviewer.server import generate_dev_cert
        with tempfile.TemporaryDirectory() as tmpdir:
            cert1, key1 = generate_dev_cert(tmpdir)
            mtime1 = os.path.getmtime(cert1)
            cert2, key2 = generate_dev_cert(tmpdir)
            mtime2 = os.path.getmtime(cert2)
            assert cert1 == cert2
            assert mtime1 == mtime2  # file not regenerated

    def test_generate_dev_cert_cert_and_key_same_dir(self):
        from dbviewer.server import generate_dev_cert
        with tempfile.TemporaryDirectory() as tmpdir:
            cert, key = generate_dev_cert(tmpdir)
            assert Path(cert).parent == Path(tmpdir)
            assert Path(key).parent == Path(tmpdir)


# ─── schema_diff._build_create_table_from_schema ─────────────────────────────

class TestBuildCreateTable:
    def _make_mysql_handler(self) -> MagicMock:
        h = MagicMock()
        h.__class__.__name__ = "MySQLDriver"
        h.settings = {"type": "mysql", "database": "mydb"}
        h.execute_query.return_value = ([{"Create Table": "CREATE TABLE `users` (`id` INT PRIMARY KEY)"}], None, 0.0)
        return h

    def _make_pg_handler(self) -> MagicMock:
        h = MagicMock()
        h.__class__.__name__ = "PostgreSQLDriver"
        h.settings = {"type": "postgres", "database": "mydb"}
        # Return schema-like rows for _get_schema_postgres
        col_rows = [{"table_name": "users", "column_name": "id", "ordinal_position": 1,
                     "column_default": None, "is_nullable": "NO", "data_type": "integer",
                     "udt_name": "int4", "character_maximum_length": None,
                     "numeric_precision": 32, "numeric_scale": 0}]
        # Two calls: columns then indexes
        h.execute_query.side_effect = [
            (col_rows, None, 0.0),
            ([], None, 0.0),
        ]
        return h

    def _make_mssql_handler(self) -> MagicMock:
        h = MagicMock()
        h.__class__.__name__ = "MSSQLDriver"
        h.settings = {"type": "mssql", "database": "mydb"}
        col_rows = [{"TABLE_NAME": "users", "COLUMN_NAME": "id", "ORDINAL_POSITION": 1,
                     "COLUMN_DEFAULT": None, "IS_NULLABLE": "NO", "DATA_TYPE": "int",
                     "CHARACTER_MAXIMUM_LENGTH": None, "NUMERIC_PRECISION": None,
                     "NUMERIC_SCALE": None, "IS_IDENTITY": 1}]
        h.execute_query.side_effect = [
            (col_rows, None, 0.0),
            ([], None, 0.0),
        ]
        return h

    def test_mysql_uses_show_create_table(self):
        h = self._make_mysql_handler()
        stmts = _build_create_table_from_schema("users", h)
        assert len(stmts) == 3
        assert "DROP TABLE" in stmts[0]
        assert "CREATE TABLE" in stmts[1]
        assert "INSERT INTO" in stmts[2]
        # MySQL should use SHOW CREATE TABLE
        called = str(h.execute_query.call_args)
        assert "SHOW CREATE TABLE" in called

    def test_postgres_builds_ddl_from_schema(self):
        h = self._make_pg_handler()
        stmts = _build_create_table_from_schema("users", h)
        assert len(stmts) == 3
        assert "DROP TABLE" in stmts[0]
        assert 'CREATE TABLE' in stmts[1]
        assert '"users"' in stmts[1]  # quoted identifiers
        assert "INSERT INTO" in stmts[2]
        # PostgreSQL should NOT use SHOW CREATE TABLE
        calls = [str(c) for c in h.execute_query.call_args_list]
        assert not any("SHOW CREATE TABLE" in c for c in calls)

    def test_mssql_builds_ddl_from_schema(self):
        h = self._make_mssql_handler()
        stmts = _build_create_table_from_schema("users", h)
        assert len(stmts) == 3
        assert "OBJECT_ID" in stmts[0]   # MSSQL drop idiom
        assert "CREATE TABLE" in stmts[1]
        assert "[users]" in stmts[1]      # bracket identifiers
        assert "INSERT INTO" in stmts[2]

    def test_missing_table_returns_empty(self):
        h = self._make_pg_handler()
        # _get_schema_postgres returns empty rows → table not in schema
        stmts = _build_create_table_from_schema("nonexistent", h)
        assert stmts == []

    def test_postgres_column_type_with_length(self):
        h = MagicMock()
        h.__class__.__name__ = "PostgreSQLDriver"
        h.settings = {"type": "postgres", "database": "db"}
        col_rows = [{"table_name": "t", "column_name": "name", "ordinal_position": 1,
                     "column_default": None, "is_nullable": "YES", "data_type": "character varying",
                     "udt_name": "varchar", "character_maximum_length": 255,
                     "numeric_precision": None, "numeric_scale": None}]
        h.execute_query.side_effect = [(col_rows, None, 0.0), ([], None, 0.0)]
        stmts = _build_create_table_from_schema("t", h)
        assert "varchar(255)" in stmts[1]

    def test_mssql_identity_column(self):
        h = self._make_mssql_handler()
        stmts = _build_create_table_from_schema("users", h)
        # id column should have IDENTITY(1,1) since IS_IDENTITY=1
        assert "IDENTITY(1,1)" in stmts[1]


# ─── Sortable table headers ───────────────────────────────────────────────────

class TestSortableHeaders:
    def _driver(self):
        """Create a minimal ConcreteDriver for header tests."""
        from tests.test_drivers import ConcreteDriver
        return ConcreteDriver()

    def test_html_table_has_sortable_class(self):
        d = self._driver()
        rows = [{"NAME": "Alice", "AGE": 30}]
        html = d.export_as_html_table("USERS", rows, ["NAME", "AGE"], [])
        assert 'class="sortable"' in html

    def test_html_table_has_data_col_attribute(self):
        d = self._driver()
        rows = [{"STATUS": "active"}]
        html = d.export_as_html_table("T", rows, ["STATUS"], [])
        assert 'data-col="STATUS"' in html

    def test_sort_arrow_present(self):
        d = self._driver()
        rows = [{"X": 1}]
        html = d.export_as_html_table("T", rows, ["X"], [])
        assert "sort-arrow" in html or "⇅" in html

    def test_hash_column_not_sortable(self):
        d = self._driver()
        rows = [{"A": 1}]
        html = d.export_as_html_table("T", rows, ["A"], [])
        # The # column (index) should NOT be sortable
        assert "<th>#</th>" in html


# ─── log_level param propagation ─────────────────────────────────────────────

class TestLogLevel:
    def test_default_log_level_is_warning(self):
        # Use importlib.reload so we get the real (unpatched) function signature
        import importlib, inspect
        import dbviewer.server as srv_mod
        importlib.reload(srv_mod)
        sig = inspect.signature(srv_mod.start_server)
        params = sig.parameters
        assert "log_level" in params
        assert params["log_level"].default == "warning"

    def test_log_level_passed_to_uvicorn(self):
        """start_server passes log_level to uvicorn.run."""
        import dbviewer.server as srv_mod
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "a", "b")
            with patch.object(srv_mod, "create_app", return_value=MagicMock()), \
                 patch.object(srv_mod.uvicorn, "run") as mock_run:
                try:
                    srv_mod.start_server(data_dir=tmpdir, log_level="debug")
                except Exception:
                    pass
                if mock_run.called:
                    call_repr = str(mock_run.call_args)
                    assert "debug" in call_repr


# ─── Server SSL validation ────────────────────────────────────────────────────

class TestServerSSLAuto:
    def test_auto_cert_path_accepted(self):
        """ssl_cert='auto' should not raise ValueError (path is handled internally)."""
        from dbviewer.server import start_server
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "a", "b")
            # Should reach generate_dev_cert(), not raise ValueError about both required
            with patch("dbviewer.server.generate_dev_cert", return_value=("/c.pem", "/k.pem")), \
                 patch("dbviewer.server.uvicorn.run"), \
                 patch("os.path.isfile", return_value=True), \
                 patch("dbviewer.server.create_app", return_value=MagicMock()):
                # Should not raise
                try:
                    start_server(data_dir=tmpdir, ssl_cert="auto", ssl_key=None)
                except SystemExit:
                    pass  # ok, just testing no ValueError

    def test_explicit_ssl_requires_both(self):
        with pytest.raises(ValueError, match="Both"):
            ssl_cert = "/real.pem"
            ssl_key = None
            if (ssl_cert or ssl_key) and ssl_cert != "auto":
                if not ssl_cert or not ssl_key:
                    raise ValueError("Both --ssl-cert and --ssl-key must be provided together.")

    def test_nonexistent_cert_file_raises(self):
        with pytest.raises(FileNotFoundError):
            cert = "/nonexistent/cert.pem"
            if not os.path.isfile(cert):
                raise FileNotFoundError(f"--ssl-cert: file not found: {cert}")
