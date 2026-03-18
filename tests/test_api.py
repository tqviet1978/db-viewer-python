"""Integration tests for API endpoints using FastAPI TestClient."""

import json
import tempfile
import base64

import pytest
from fastapi.testclient import TestClient

from dbviewer.server import create_app
from dbviewer.auth import create_user


@pytest.fixture
def app_client():
    """App with no_auth=True and a temp data dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "admin123")
        app = create_app(data_dir=tmpdir, no_auth=True)
        with TestClient(app) as client:
            yield client, tmpdir


@pytest.fixture
def auth_client():
    """App with auth enabled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "admin123")
        app = create_app(data_dir=tmpdir, no_auth=False)
        with TestClient(app, raise_server_exceptions=False) as client:
            yield client, tmpdir


class TestLogin:
    def test_valid_login(self, auth_client):
        client, tmpdir = auth_client
        r = client.post("/api/login", json={"username": "admin", "password": "admin123"})
        assert r.status_code == 200
        assert r.json()["success"] is True

    def test_invalid_login(self, auth_client):
        client, tmpdir = auth_client
        r = client.post("/api/login", json={"username": "admin", "password": "wrong"})
        assert r.status_code == 200
        assert r.json()["success"] is False

    def test_unknown_user(self, auth_client):
        client, tmpdir = auth_client
        r = client.post("/api/login", json={"username": "nobody", "password": "pw"})
        assert r.status_code == 200
        assert r.json()["success"] is False


class TestConnections:
    def test_get_connections_no_auth(self, app_client):
        client, tmpdir = app_client
        # Write a connections.json
        conn_file = f"{tmpdir}/connections.json"
        with open(conn_file, "w") as f:
            json.dump([{"name": "Test DB", "type": "mysql", "server": "localhost",
                        "database": "test", "user": "root", "password": ""}], f)

        r = client.get("/api/connections")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "Test DB" in data["connections"]

    def test_empty_connections(self, app_client):
        client, tmpdir = app_client
        r = client.get("/api/connections")
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert data["connections"] == []

    def test_set_active_connection_invalid_id(self, app_client):
        client, tmpdir = app_client
        r = client.post("/api/setActiveConnection", json={"connection": 999})
        assert r.status_code == 200
        assert r.json()["success"] is False


class TestAuth401:
    def test_no_credentials_returns_401(self, auth_client):
        client, tmpdir = auth_client
        r = client.get("/api/connections")
        assert r.status_code == 401

    def test_valid_credentials_allowed(self, auth_client):
        client, tmpdir = auth_client
        creds = base64.b64encode(b"admin:admin123").decode()
        r = client.get("/api/connections", headers={"Authorization": f"Basic {creds}"})
        assert r.status_code == 200


class TestNoActiveConnection:
    def test_concept_no_connection(self, app_client):
        client, _ = app_client
        r = client.post("/api/concept", json={"tables": ["USERS"]})
        assert r.status_code == 200
        assert r.json()["success"] is False
        assert "No active connection" in r.json()["message"]

    def test_execute_query_no_connection(self, app_client):
        client, _ = app_client
        r = client.post("/api/executeQuery", json={"query": "SELECT 1", "mode": "", "tables": []})
        assert r.status_code == 200
        assert r.json()["success"] is False


class TestFrontend:
    def test_root_returns_html(self, app_client):
        client, _ = app_client
        r = client.get("/")
        assert r.status_code == 200
        assert "text/html" in r.headers.get("content-type", "")
        assert "DB Viewer" in r.text


class TestExecuteQuery:
    """Test query safety rules using unit-level driver tests (no real DB needed)."""

    def test_destructive_blocked(self, app_client):
        """DELETE without //Confirmed should be blocked — tested via mock driver."""
        from unittest.mock import MagicMock, patch
        from dbviewer.api import active_connections
        import json as _json

        client, tmpdir = app_client

        mock_driver = MagicMock()
        mock_driver.execute_query.return_value = ([], None, 1.0)
        mock_driver.export_as_html_table.return_value = "(empty)"
        mock_driver.close.return_value = None

        conn_file = f"{tmpdir}/connections.json"
        with open(conn_file, "w") as f:
            _json.dump([{"name": "T", "type": "mysql", "server": "localhost",
                          "database": "t", "user": "r", "password": ""}], f)
        active_connections["anonymous"] = {"connection_id": 0}

        with patch("dbviewer.api._build_driver", return_value=mock_driver):
            r = client.post("/api/executeQuery", json={
                "query": "DELETE FROM USERS WHERE ID = 1",
                "mode": "", "tables": [],
            })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "not allowed" in data["html"].lower()

    def test_confirmed_destructive_passes(self, app_client):
        """DELETE with //Confirmed suffix should execute."""
        from unittest.mock import MagicMock, patch
        from dbviewer.api import active_connections
        import json as _json

        client, tmpdir = app_client

        mock_driver = MagicMock()
        mock_driver.execute_query.return_value = ("Done. Affected rows = 1 in 0.5ms", None, 0.5)
        mock_driver.close.return_value = None

        conn_file = f"{tmpdir}/connections.json"
        with open(conn_file, "w") as f:
            _json.dump([{"name": "T", "type": "mysql", "server": "localhost",
                          "database": "t", "user": "r", "password": ""}], f)
        active_connections["anonymous"] = {"connection_id": 0}

        with patch("dbviewer.api._build_driver", return_value=mock_driver):
            r = client.post("/api/executeQuery", json={
                "query": "DELETE FROM USERS WHERE ID = 1//Confirmed",
                "mode": "", "tables": [],
            })
        assert r.status_code == 200
        data = r.json()
        assert data["success"] is True
        assert "not allowed" not in data["html"].lower()
