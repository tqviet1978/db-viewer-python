"""Integration tests using the SQLite driver.

These tests exercise the full GenericDriver interface (and through it,
api.py endpoints) against a real in-process SQLite database.  No external
services required.
"""

from __future__ import annotations

import json
import tempfile

import pytest
from fastapi.testclient import TestClient

from dbviewer.drivers.sqlite import SQLiteDriver
from dbviewer.server import create_app
from dbviewer.auth import create_user
from dbviewer.api import active_connections


# ─── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    """In-memory SQLite driver pre-populated with test schema."""
    driver = SQLiteDriver()
    err = driver.initialize({"database": ":memory:", "type": "sqlite"})
    assert err is None

    driver.create_table("""
        CREATE TABLE USERS (
            ID      INTEGER PRIMARY KEY AUTOINCREMENT,
            UUID    TEXT,
            NAME    TEXT,
            EMAIL   TEXT,
            GUID    INTEGER DEFAULT 1,
            SSID    INTEGER DEFAULT 0,
            UDID    INTEGER DEFAULT 1,
            CREATION_DATE TEXT,
            LATEST_UPDATE TEXT
        )
    """)
    driver.create_table("""
        CREATE TABLE ORDERS (
            ID          INTEGER PRIMARY KEY AUTOINCREMENT,
            UUID        TEXT,
            ID_USER     INTEGER,
            TOTAL_VALUE REAL,
            ORDER_DATE  TEXT,
            GUID        INTEGER DEFAULT 1,
            CREATION_DATE TEXT,
            LATEST_UPDATE TEXT
        )
    """)
    driver.seed("USERS", [
        {"UUID": "aaa111", "NAME": "Alice", "EMAIL": "alice@example.com"},
        {"UUID": "bbb222", "NAME": "Bob",   "EMAIL": "bob@example.com"},
        {"UUID": "ccc333", "NAME": "Carol", "EMAIL": "carol@example.com"},
    ])
    driver.seed("ORDERS", [
        {"UUID": "ord001", "ID_USER": 1, "TOTAL_VALUE": 150.50, "ORDER_DATE": "2024-01-15"},
        {"UUID": "ord002", "ID_USER": 1, "TOTAL_VALUE": 89.00,  "ORDER_DATE": "2024-02-20"},
        {"UUID": "ord003", "ID_USER": 2, "TOTAL_VALUE": 210.75, "ORDER_DATE": "2024-03-05"},
    ])
    yield driver
    driver.close()


@pytest.fixture
def api(db):
    """TestClient wired to a no-auth app with the SQLite driver injected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "admin123")

        # Write a connections.json pointing to :memory: — but we'll override
        # the driver at the API layer via active_connections injection
        conns = [{"name": "Test SQLite", "type": "sqlite", "database": ":memory:",
                  "server": "", "user": "", "password": ""}]
        with open(f"{tmpdir}/connections.json", "w") as f:
            json.dump(conns, f)

        app = create_app(data_dir=tmpdir, no_auth=True)

        with TestClient(app, raise_server_exceptions=False) as client:
            # Inject our pre-seeded driver instead of letting the API create a new one
            active_connections["anonymous"] = {"connection_id": 0, "_override_driver": db}
            yield client, tmpdir, db

        # Cleanup injection
        active_connections.pop("anonymous", None)


# ─── Driver-level integration tests ─────────────────────────────────────────

class TestSQLiteDriverBasics:
    def test_initialize(self):
        d = SQLiteDriver()
        err = d.initialize({"database": ":memory:"})
        assert err is None
        d.close()

    def test_bad_path_returns_error(self):
        d = SQLiteDriver()
        err = d.initialize({"database": "/nonexistent/path/db.sqlite"})
        assert err is not None

    def test_get_table_names(self, db):
        tables = db.get_table_names()
        assert "USERS" in tables
        assert "ORDERS" in tables

    def test_get_table_columns(self, db):
        cols = db.get_table_columns("USERS")
        assert "NAME" in cols
        assert "EMAIL" in cols
        assert "ID" in cols

    def test_get_table_count(self, db):
        assert db.get_table_count("USERS") == 3
        assert db.get_table_count("ORDERS") == 3

    def test_get_table_data_all(self, db):
        rows = db.get_table_data("USERS")
        assert len(rows) == 3
        assert rows[0]["NAME"] == "Alice"

    def test_get_table_data_pagination(self, db):
        rows = db.get_table_data("USERS", offset=1, limit=2)
        assert len(rows) == 2
        assert rows[0]["NAME"] == "Bob"

    def test_get_table_data_limit(self, db):
        rows = db.get_table_data("USERS", offset=0, limit=1)
        assert len(rows) == 1

    def test_execute_select(self, db):
        rows, error, elapsed = db.execute_query("SELECT * FROM USERS WHERE NAME='Alice'")
        assert error is None
        assert isinstance(rows, list)
        assert len(rows) == 1
        assert rows[0]["EMAIL"] == "alice@example.com"

    def test_execute_dml_returns_string(self, db):
        result, error, elapsed = db.execute_query(
            "UPDATE USERS SET NAME='Alicia' WHERE NAME='Alice'"
        )
        assert error is None
        assert isinstance(result, str)
        assert "Done" in result

    def test_execute_bad_query_returns_error(self, db):
        result, error, elapsed = db.execute_query("SELECT * FROM NONEXISTENT_TABLE")
        assert error is not None
        assert result is None

    def test_column_exists_true(self, db):
        exists, dtype = db.column_exists("USERS", "NAME")
        assert exists is True
        assert dtype == "TEXT"

    def test_column_exists_false(self, db):
        exists, dtype = db.column_exists("USERS", "GHOST_COL")
        assert exists is False
        assert dtype == ""

    def test_get_column_names_multi_table(self, db):
        names = db.get_column_names(["USERS", "ORDERS"])
        assert "NAME" in names
        assert "TOTAL_VALUE" in names
        # Sorted
        assert names == sorted(names)

    def test_truncate_table_dry_run(self, db):
        result = db.truncate_table("USERS", dry_run=True)
        assert "DELETE FROM" in result
        # Data not actually deleted
        assert db.get_table_count("USERS") == 3

    def test_truncate_table_live(self, db):
        db.truncate_table("ORDERS", dry_run=False)
        assert db.get_table_count("ORDERS") == 0

    def test_drop_table_dry_run(self, db):
        result = db.drop_table("ORDERS", dry_run=True)
        assert "DROP TABLE" in result
        assert "ORDERS" in db.get_table_names()

    def test_drop_table_live(self, db):
        db.drop_table("ORDERS", dry_run=False)
        assert "ORDERS" not in db.get_table_names()

    def test_rename_table_dry_run(self, db):
        result = db.rename_table("ORDERS", "ORDERS_NEW", dry_run=True)
        assert "RENAME" in result
        assert "ORDERS" in db.get_table_names()

    def test_clone_table_dry_run(self, db):
        result = db.clone_table("USERS", "USERS_BACKUP", dry_run=True)
        assert "CREATE TABLE" in result
        assert "USERS_BACKUP" not in db.get_table_names()


class TestSQLiteDriverRowOps:
    def test_insert_new_row(self, db):
        row_id = db.insert_table_row("USERS", {"NAME": "Dave", "EMAIL": "dave@example.com"})
        assert row_id > 0
        assert db.get_table_count("USERS") == 4

    def test_update_existing_row(self, db):
        db.insert_table_row("USERS", {"ID": 1, "NAME": "Alice Updated"})
        rows, _, _ = db.execute_query("SELECT NAME FROM USERS WHERE ID=1")
        assert rows[0]["NAME"] == "Alice Updated"


class TestSQLiteDriverSharedMethods:
    """Tests exercising GenericDriver shared logic via SQLiteDriver."""

    def test_export_tables_as_concept(self, db):
        result = db.export_tables_as_concept(["USERS"])
        assert "[USERS]" in result
        assert "NAME" in result
        assert "EMAIL" in result
        # System columns excluded
        assert "CREATION_DATE" not in result

    def test_export_table_structures(self, db):
        result = db.export_table_structures(["USERS"])
        assert "[USERS]" in result
        assert "NAME" in result
        assert "|" in result  # column | type

    def test_get_normal_columns_excludes_system(self, db):
        cols = db.get_normal_table_columns("USERS")
        assert "ID" not in cols
        assert "UUID" not in cols
        assert "NAME" in cols

    def test_get_normal_columns_search_name(self, db):
        cols = db.get_normal_table_columns("USERS", "EMAIL")
        assert "EMAIL" in cols
        assert "NAME" not in cols

    def test_get_normal_columns_exclude_syntax(self, db):
        cols = db.get_normal_table_columns("USERS", "-NAME")
        assert "NAME" not in cols
        assert "EMAIL" in cols

    def test_export_as_html_table(self, db):
        rows = db.get_table_data("USERS")
        html = db.export_as_html_table("USERS", rows, ["NAME", "EMAIL"], [])
        assert "<table" in html
        assert "NAME" in html and "sortable" in html
        assert "Alice" in html
        assert "<th>#</th>" in html

    def test_get_table_counts(self, db):
        counts = db.get_table_counts(["USERS", "ORDERS"])
        assert counts["USERS"] == 3
        assert counts["ORDERS"] == 3

    def test_truncate_tables_batch_dry(self, db):
        result = db.truncate_tables(["USERS", "ORDERS"], dry_run=True)
        assert "TRUNCATE" in result.upper() or "DELETE" in result.upper()

    def test_drop_tables_batch_dry(self, db):
        result = db.drop_tables(["USERS"], dry_run=True)
        assert "DROP" in result

    def test_alter_column_dry_run(self, db):
        result = db.alter_column(["USERS"], "NAME", "FULL_NAME", "", dry_run=True)
        assert "RENAME COLUMN" in result or "CHANGE" in result or "RENAME" in result

    def test_drop_column_dry_run(self, db):
        result = db.drop_column(["USERS"], "EMAIL", dry_run=True)
        assert "DROP COLUMN" in result

    def test_get_indexes_as_html(self, db):
        # SQLite returns no extra indexes for our test tables (just implicit rowid)
        result = db.get_indexes_as_html(["USERS"])
        assert "[USERS]" in result

    def test_get_snippets_contains_table(self, db):
        result = db.get_snippets_as_html(["USERS"])
        assert "USERS" in result
        assert "SELECT" in result

    def test_get_tostring_as_html(self, db):
        result = db.get_toString_as_html(["USERS", "ORDERS"])
        assert "USERS" in result
        assert "ORDERS" in result


class TestSQLiteAlterColumn:
    def test_insert_after_column_dry_run(self, db):
        result = db.insert_after_column(["USERS"], "NAME", "NICKNAME", "TEXT", dry_run=True)
        assert "ADD COLUMN" in result
        assert "NICKNAME" in result

    def test_drop_column_not_found(self, db):
        result = db.drop_column(["USERS"], "NONEXISTENT", dry_run=True)
        assert "not found" in result.lower()


class TestSQLiteDecimalColumns:
    def test_decimal_columns_detected(self, db):
        # ORDERS.TOTAL_VALUE is REAL — not 'double' so get_decimal_columns won't match
        # Add a 'double' column to test
        db.conn.execute("ALTER TABLE ORDERS ADD COLUMN TAX_RATE DOUBLE DEFAULT 0.0")
        db.conn.commit()
        cols = db.get_decimal_columns("ORDERS")
        assert "TAX_RATE" in cols


# ─── API integration tests via SQLite ────────────────────────────────────────

class TestAPIWithSQLite:
    """End-to-end tests through the FastAPI layer using the SQLite driver."""

    def _inject(self, db, tmpdir):
        """Patch _build_driver so the API uses our pre-seeded SQLite driver."""
        import json as _json
        conns = [{"name": "Test SQLite", "type": "sqlite",
                  "database": ":memory:", "server": "", "user": "", "password": ""}]
        with open(f"{tmpdir}/connections.json", "w") as f:
            _json.dump(conns, f)
        active_connections["anonymous"] = {"connection_id": 0}

    def test_concept_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE PRODUCTS (ID INTEGER PRIMARY KEY, NAME TEXT, PRICE REAL)")
            d.seed("PRODUCTS", [{"NAME": "Widget", "PRICE": 9.99}])

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/concept", json={"tables": ["PRODUCTS"]})

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "PRODUCTS" in data["html"]
            assert "NAME" in data["html"]
            d.close()

    def test_data_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE ITEMS (ID INTEGER PRIMARY KEY, NAME TEXT)")
            d.seed("ITEMS", [{"NAME": "Alpha"}, {"NAME": "Beta"}])

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/data", json={"tables": ["ITEMS"], "limitIdFrom": ""})

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "Alpha" in data["html"]
            assert "Beta" in data["html"]
            d.close()

    def test_execute_query_select(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE CATS (ID INTEGER PRIMARY KEY, NAME TEXT)")
            d.seed("CATS", [{"NAME": "Whiskers"}, {"NAME": "Mittens"}])

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/executeQuery", json={
                        "query": "SELECT * FROM CATS",
                        "mode": "",
                        "tables": ["CATS"],
                    })

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "Whiskers" in data["html"]
            d.close()

    def test_execute_query_dml(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE TAGS (ID INTEGER PRIMARY KEY, LABEL TEXT)")
            d.seed("TAGS", [{"LABEL": "old"}])

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/executeQuery", json={
                        "query": "UPDATE TAGS SET LABEL='new' WHERE ID=1",
                        "mode": "",
                        "tables": [],
                    })

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            # DML returns status string
            assert "Done" in data["html"] or "Affected" in data["html"]
            d.close()

    def test_insert_table_row(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE NOTES (ID INTEGER PRIMARY KEY, TITLE TEXT, UUID TEXT)")

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/insertTableRow", json={
                        "table": "NOTES",
                        "data": {"TITLE": "My Note"},
                    })

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "id" in data
            assert data["id"] > 0
            d.close()

    def test_get_table_columns_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE EVENTS (ID INTEGER PRIMARY KEY, TITLE TEXT, UUID TEXT, GUID INTEGER)")

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/getTableColumns", json={"table": "EVENTS"})

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "TITLE" in data["columns"]
            # System columns excluded
            assert "ID" not in data["columns"]
            assert "UUID" not in data["columns"]
            assert "GUID" not in data["columns"]
            d.close()

    def test_snippets_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE WIDGETS (ID INTEGER PRIMARY KEY, NAME TEXT, CODE TEXT)")

            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch
            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/snippets", json={"tables": ["WIDGETS"]})

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            assert "WIDGETS" in data["html"]
            assert "SELECT" in data["html"]
            d.close()

    def test_truncate_dry_run_endpoint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            create_user(tmpdir, "admin", "admin123")
            app = create_app(data_dir=tmpdir, no_auth=True)

            d = SQLiteDriver()
            d.initialize({"database": ":memory:", "type": "sqlite"})
            d.create_table("CREATE TABLE LOGS (ID INTEGER PRIMARY KEY, MSG TEXT)")
            d.seed("LOGS", [{"MSG": "test"}])

            # Count before the call — we verify dry-run doesn't delete rows
            # by checking count INSIDE the patch context (before driver is closed)
            import json as _j
            with open(f"{tmpdir}/connections.json", "w") as f:
                _j.dump([{"name": "T", "type": "sqlite", "database": ":memory:",
                           "server": "", "user": "", "password": ""}], f)

            from unittest.mock import patch, MagicMock

            # Wrap d so close() is a no-op inside the API call, letting us
            # verify the row count after the endpoint returns
            original_close = d.close
            d.close = lambda: None  # prevent the API from closing our driver

            with TestClient(app) as client:
                with patch("dbviewer.api._build_driver", return_value=d):
                    active_connections["anonymous"] = {"connection_id": 0}
                    r = client.post("/api/truncateTables", json={
                        "tables": ["LOGS"], "dryRun": True, "confirmation": ""
                    })

            assert r.status_code == 200
            data = r.json()
            assert data["success"] is True
            # dry run — data still present
            assert d.get_table_count("LOGS") == 1
            d.close = original_close
            d.close()
