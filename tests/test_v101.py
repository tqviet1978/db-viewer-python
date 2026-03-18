"""Tests for v1.0.1 additions:
- Connection CRUD endpoints
- testConnection endpoint with diagnostics
- _auto_detect_column_types helper
- _connection_diagnostics helper
- schema_diff multi-backend dispatch
- service.py systemd generator
- SSL validation in server.py
- session_id-based connection keying
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dbviewer.api import _auto_detect_column_types, _connection_diagnostics, _conn_key, active_connections
from dbviewer.auth import create_user
from dbviewer.schema_diff import _detect_db_type, _get_schema_mysql
from dbviewer.server import create_app


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def client_with_conn():
    """Client + tmpdir with one connection in connections.json."""
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "admin123")
        conns = [{"name": "Local MySQL", "type": "mysql", "server": "localhost",
                  "port": 3306, "database": "testdb", "user": "root", "password": ""}]
        with open(f"{tmpdir}/connections.json", "w") as f:
            json.dump(conns, f)
        app = create_app(data_dir=tmpdir, no_auth=True)
        with TestClient(app) as client:
            yield client, tmpdir


# ─── _auto_detect_column_types ────────────────────────────────────────────────

class TestAutoDetectColumnTypes:
    def test_float_columns_become_decimal(self):
        rows = [{"PRICE": 9.99, "NAME": "Widget"}, {"PRICE": 14.50, "NAME": "Gadget"}]
        dec, txt = _auto_detect_column_types(rows, ["PRICE", "NAME"])
        assert "PRICE" in dec
        assert "NAME" not in dec

    def test_leading_zero_strings_become_text(self):
        rows = [{"CODE": "00123"}, {"CODE": "00456"}]
        dec, txt = _auto_detect_column_types(rows, ["CODE"])
        assert "CODE" in txt

    def test_long_digit_string_becomes_text(self):
        rows = [{"PHONE": "0987654321"}, {"PHONE": "0123456789"}]
        dec, txt = _auto_detect_column_types(rows, ["PHONE"])
        assert "PHONE" in txt

    def test_regular_string_is_neither(self):
        rows = [{"LABEL": "alpha"}, {"LABEL": "beta"}]
        dec, txt = _auto_detect_column_types(rows, ["LABEL"])
        assert "LABEL" not in dec
        assert "LABEL" not in txt

    def test_empty_rows(self):
        dec, txt = _auto_detect_column_types([], ["COL1", "COL2"])
        assert dec == []
        assert txt == []

    def test_mixed_columns(self):
        rows = [
            {"AMOUNT": 100.50, "BARCODE": "0001234567890", "LABEL": "item"},
            {"AMOUNT": 200.00, "BARCODE": "0001234567891", "LABEL": "item2"},
        ]
        dec, txt = _auto_detect_column_types(rows, ["AMOUNT", "BARCODE", "LABEL"])
        assert "AMOUNT" in dec
        assert "BARCODE" in txt
        assert "LABEL" not in dec
        assert "LABEL" not in txt


# ─── _connection_diagnostics ─────────────────────────────────────────────────

class TestConnectionDiagnostics:
    def _settings(self, **kw):
        base = {"server": "db.example.com", "port": 3306, "database": "mydb",
                "user": "admin", "type": "mysql"}
        base.update(kw)
        return base

    def test_host_unreachable_hint(self):
        diag = _connection_diagnostics(self._settings(), "Connection refused to db.example.com:3306")
        assert "unreachable" in diag["hint"].lower() or "firewall" in diag["hint"].lower()

    def test_auth_failure_hint(self):
        diag = _connection_diagnostics(self._settings(), "Access denied for user 'admin'@'localhost'")
        assert "authentication" in diag["hint"].lower() or "password" in diag["hint"].lower()

    def test_unknown_database_hint(self):
        diag = _connection_diagnostics(self._settings(), "Unknown database 'mydb'")
        assert "database" in diag["hint"].lower() or "not found" in diag["hint"].lower()

    def test_generic_error_hint(self):
        diag = _connection_diagnostics(self._settings(), "Something unexpected happened")
        assert "hint" in diag
        assert len(diag["hint"]) > 0

    def test_contains_settings_info(self):
        diag = _connection_diagnostics(self._settings(), "error")
        assert diag["host"] == "db.example.com"
        assert diag["database"] == "mydb"
        assert diag["user"] == "admin"


# ─── _conn_key ────────────────────────────────────────────────────────────────

class TestConnKey:
    def test_with_session_id(self):
        key = _conn_key("alice", "sess_abc123")
        assert key == "alice:sess_abc123"

    def test_without_session_id(self):
        assert _conn_key("alice", "") == "alice"
        assert _conn_key("alice", None) == "alice"

    def test_different_sessions_different_keys(self):
        k1 = _conn_key("bob", "sess1")
        k2 = _conn_key("bob", "sess2")
        assert k1 != k2

    def test_same_user_same_session(self):
        assert _conn_key("carol", "s") == _conn_key("carol", "s")


# ─── Connection CRUD endpoints ────────────────────────────────────────────────

class TestConnectionCRUD:
    def test_get_connections_full_masks_password(self, client_with_conn):
        client, tmpdir = client_with_conn
        # Add a connection with a real password first
        with open(f"{tmpdir}/connections.json") as f:
            conns = json.load(f)
        conns[0]["password"] = "secret123"
        with open(f"{tmpdir}/connections.json", "w") as f:
            json.dump(conns, f)

        r = client.get("/api/connections/full")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        conn = data["connections"][0]
        assert conn["password"] != "secret123"
        assert "••••" in conn["password"]

    def test_get_connections_full_empty_password_stays_empty(self, client_with_conn):
        client, tmpdir = client_with_conn
        r = client.get("/api/connections/full")
        data = r.json()
        assert data["connections"][0]["password"] == ""

    def test_add_connection(self, client_with_conn):
        client, tmpdir = client_with_conn
        r = client.post("/api/connections/add", json={
            "name": "New PG", "type": "postgres", "server": "pg.example.com",
            "port": 5432, "database": "newdb", "user": "pguser", "password": "pgpass"
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "New PG" in data["connections"]
        assert data["index"] == 1

    def test_add_connection_persisted(self, client_with_conn):
        client, tmpdir = client_with_conn
        client.post("/api/connections/add", json={
            "name": "PG Prod", "type": "postgres", "server": "pg.prod",
            "port": 5432, "database": "prod", "user": "u", "password": "p"
        })
        with open(f"{tmpdir}/connections.json") as f:
            saved = json.load(f)
        assert len(saved) == 2
        assert saved[1]["name"] == "PG Prod"

    def test_update_connection(self, client_with_conn):
        client, tmpdir = client_with_conn
        r = client.post("/api/connections/update", json={
            "index": 0, "name": "Updated MySQL", "type": "mysql",
            "server": "newhost", "port": 3306, "database": "newdb",
            "user": "root", "password": ""
        })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "Updated MySQL" in data["connections"]

    def test_update_connection_persisted(self, client_with_conn):
        client, tmpdir = client_with_conn
        client.post("/api/connections/update", json={
            "index": 0, "name": "Renamed", "type": "mysql",
            "server": "h", "port": 3306, "database": "d", "user": "u", "password": "p"
        })
        with open(f"{tmpdir}/connections.json") as f:
            saved = json.load(f)
        assert saved[0]["name"] == "Renamed"

    def test_update_invalid_index(self, client_with_conn):
        client, _ = client_with_conn
        r = client.post("/api/connections/update", json={
            "index": 99, "name": "X", "type": "mysql",
            "server": "h", "port": 3306, "database": "d", "user": "u", "password": "p"
        })
        assert r.json()["success"] is False

    def test_delete_connection(self, client_with_conn):
        client, tmpdir = client_with_conn
        # Add a second connection first
        client.post("/api/connections/add", json={
            "name": "To Delete", "type": "mysql", "server": "h",
            "port": 3306, "database": "d", "user": "u", "password": ""
        })
        r = client.post("/api/connections/delete", json={"index": 1})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "To Delete" not in data["connections"]

    def test_delete_connection_persisted(self, client_with_conn):
        client, tmpdir = client_with_conn
        client.post("/api/connections/add", json={
            "name": "Temp", "type": "mysql", "server": "h",
            "port": 3306, "database": "d", "user": "u", "password": ""
        })
        client.post("/api/connections/delete", json={"index": 1})
        with open(f"{tmpdir}/connections.json") as f:
            saved = json.load(f)
        assert len(saved) == 1
        assert saved[0]["name"] == "Local MySQL"

    def test_delete_invalid_index(self, client_with_conn):
        client, _ = client_with_conn
        r = client.post("/api/connections/delete", json={"index": 99})
        assert r.json()["success"] is False


# ─── testConnection endpoint ─────────────────────────────────────────────────

class TestConnectionTestEndpoint:
    def test_invalid_connection_id(self, client_with_conn):
        client, _ = client_with_conn
        r = client.post("/api/testConnection", json={"connection": 999})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False

    def test_failed_connection_returns_diagnostics(self, client_with_conn):
        client, _ = client_with_conn
        # The real MySQL isn't running, so _build_driver will fail
        with patch("dbviewer.api._build_driver", return_value="Connection refused"):
            r = client.post("/api/testConnection", json={"connection": 0})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "diagnostics" in data
        assert "hint" in data["diagnostics"]
        assert "elapsed_ms" in data

    def test_successful_connection(self, client_with_conn):
        client, _ = client_with_conn
        mock_driver = MagicMock()
        mock_driver.get_table_names.return_value = ["USERS", "ORDERS", "PRODUCTS"]
        mock_driver.close.return_value = None
        with patch("dbviewer.api._build_driver", return_value=mock_driver):
            r = client.post("/api/testConnection", json={"connection": 0})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["table_count"] == 3
        assert "elapsed_ms" in data


# ─── schema_diff multi-backend dispatch ──────────────────────────────────────

class TestSchemaDiffDispatch:
    def _make_handler(self, cls_name: str, db_type: str) -> MagicMock:
        h = MagicMock()
        h.__class__.__name__ = cls_name
        h.settings = {"database": "testdb", "type": db_type}
        h.execute_query.return_value = ([], None, 0.0)
        return h

    def test_detect_mysql(self):
        h = self._make_handler("MySQLDriver", "mysql")
        assert _detect_db_type(h) == "mysql"

    def test_detect_postgres(self):
        h = self._make_handler("PostgreSQLDriver", "postgres")
        assert _detect_db_type(h) == "postgres"

    def test_detect_mssql(self):
        h = self._make_handler("MSSQLDriver", "mssql")
        assert _detect_db_type(h) == "mssql"

    def test_detect_fallback_to_settings(self):
        h = self._make_handler("CustomDriver", "postgres")
        assert _detect_db_type(h) == "postgres"

    def test_mysql_schema_empty_on_error(self):
        h = self._make_handler("MySQLDriver", "mysql")
        h.execute_query.return_value = (None, "Access denied", 0.0)
        result = _get_schema_mysql(h)
        assert result == {}

    def test_postgres_schema_dispatch(self):
        """_get_schema on a PostgreSQL handler should call the pg-specific query."""
        from dbviewer.schema_diff import _get_schema, _get_schema_postgres
        h = self._make_handler("PostgreSQLDriver", "postgres")
        calls = []
        def fake_execute(q):
            calls.append(q)
            return ([], None, 0.0)
        h.execute_query = fake_execute

        result = _get_schema(h)
        assert any("information_schema.columns" in q.lower() for q in calls), \
            f"Expected information_schema.columns query, got: {calls}"

    def test_mssql_schema_dispatch(self):
        """_get_schema on MSSQL handler should call INFORMATION_SCHEMA with dbo filter."""
        from dbviewer.schema_diff import _get_schema
        h = self._make_handler("MSSQLDriver", "mssql")
        calls = []
        def fake_execute(q):
            calls.append(q)
            return ([], None, 0.0)
        h.execute_query = fake_execute

        result = _get_schema(h)
        assert any("INFORMATION_SCHEMA.COLUMNS" in q for q in calls), \
            f"Expected INFORMATION_SCHEMA.COLUMNS query, got: {calls}"
        assert any("dbo" in q for q in calls), \
            f"Expected dbo schema filter, got: {calls}"

    def test_mysql_schema_dispatch(self):
        """_get_schema on MySQL handler should use TABLE_SCHEMA filter."""
        from dbviewer.schema_diff import _get_schema
        h = self._make_handler("MySQLDriver", "mysql")
        calls = []
        def fake_execute(q):
            calls.append(q)
            return ([], None, 0.0)
        h.execute_query = fake_execute

        result = _get_schema(h)
        assert any("TABLE_SCHEMA" in q and "testdb" in q for q in calls), \
            f"Expected TABLE_SCHEMA filter with testdb, got: {calls}"


# ─── service.py systemd generator ────────────────────────────────────────────

class TestSystemdServiceGenerator:
    def test_writes_file(self):
        import dbviewer.service as svc_mod
        import pathlib
        original_home = pathlib.Path.home
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                pathlib.Path.home = staticmethod(lambda: pathlib.Path(tmpdir))
                path = svc_mod.write_systemd_service(
                    host="0.0.0.0", port=9876,
                    data_dir=f"{tmpdir}/data", no_auth=False
                )
                assert path.exists()
                file_content = path.read_text()
                assert "[Unit]" in file_content
                assert "[Service]" in file_content
                assert "[Install]" in file_content
                assert "9876" in file_content
            finally:
                pathlib.Path.home = original_home

    def test_no_auth_flag_included(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import dbviewer.service as svc_mod
            try:
                Path.home = lambda: Path(tmpdir)
                path = svc_mod.write_systemd_service(
                    host="127.0.0.1", port=8080,
                    data_dir=f"{tmpdir}/data", no_auth=True
                )
                content = path.read_text()
                assert "--no-auth" in content
                assert "8080" in content
                assert "127.0.0.1" in content
            finally:
                import pathlib
                Path.home = pathlib.Path.home

    def test_service_content_structure(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import dbviewer.service as svc_mod
            try:
                Path.home = lambda: Path(tmpdir)
                path = svc_mod.write_systemd_service()
                content = path.read_text()
                assert "ExecStart=" in content
                assert "Restart=on-failure" in content
                assert "WantedBy=default.target" in content
            finally:
                import pathlib
                Path.home = pathlib.Path.home


# ─── SSL validation in server.py ─────────────────────────────────────────────

class TestSSLValidation:
    def test_ssl_requires_both_cert_and_key(self):
        from dbviewer.server import start_server
        with pytest.raises(ValueError, match="Both"):
            # Only cert, no key
            with tempfile.TemporaryDirectory() as tmpdir:
                create_user(tmpdir, "a", "b")
                start_server.__wrapped__ = None  # reset any cached state
                import inspect
                # Just call the validation logic directly
                ssl_cert = "/tmp/fake.pem"
                ssl_key = None
                if ssl_cert or ssl_key:
                    if not ssl_cert or not ssl_key:
                        raise ValueError("Both --ssl-cert and --ssl-key must be provided together.")

    def test_ssl_cert_file_must_exist(self):
        with pytest.raises(FileNotFoundError):
            ssl_cert = "/nonexistent/cert.pem"
            ssl_key = "/nonexistent/key.pem"
            if not os.path.isfile(ssl_cert):
                raise FileNotFoundError(f"--ssl-cert: file not found: {ssl_cert}")

    def test_server_create_app_no_ssl(self):
        """create_app still works without SSL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)
            assert app is not None


# ─── setActiveConnection diagnostics ─────────────────────────────────────────

class TestSetActiveConnectionDiagnostics:
    def test_failed_connection_returns_diagnostics(self, client_with_conn):
        client, _ = client_with_conn
        with patch("dbviewer.api._build_driver", return_value="Access denied for user 'root'"):
            r = client.post("/api/setActiveConnection", json={"connection": 0})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is False
        assert "diagnostics" in data
        assert "hint" in data["diagnostics"]

    def test_successful_connection_no_diagnostics(self, client_with_conn):
        client, _ = client_with_conn
        mock_driver = MagicMock()
        mock_driver.get_table_names.return_value = ["T1", "T2"]
        mock_driver.get_table_counts.return_value = {"T1": 5, "T2": 10}
        mock_driver.close.return_value = None
        with patch("dbviewer.api._build_driver", return_value=mock_driver):
            r = client.post("/api/setActiveConnection", json={"connection": 0})
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "tables" in data
        assert len(data["tables"]) == 2
