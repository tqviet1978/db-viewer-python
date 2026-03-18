"""Tests for auth module."""

import json
import os
import tempfile

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient
from starlette.requests import Request
from starlette.datastructures import Headers

from dbviewer.auth import hash_password, verify_password, create_user, load_users, verify_request


def test_hash_and_verify():
    pw = "MyS3cr3t!"
    hashed = hash_password(pw)
    assert hashed != pw
    assert hashed.startswith("$2b$")
    assert verify_password(pw, hashed) is True


def test_verify_wrong_password():
    hashed = hash_password("correct_password")
    assert verify_password("wrong_password", hashed) is False


def test_verify_empty_password():
    hashed = hash_password("password")
    assert verify_password("", hashed) is False


def test_verify_request_no_auth():
    """When no_auth=True, always returns 'anonymous'."""
    # Mock a request with no headers
    scope = {"type": "http", "headers": []}
    request = Request(scope)
    result = verify_request(request, "/tmp", no_auth=True)
    assert result == "anonymous"


def test_verify_request_valid():
    """Valid Basic credentials should return the username."""
    import base64
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "secret123")

        creds = base64.b64encode(b"admin:secret123").decode()
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Basic {creds}".encode())],
        }
        request = Request(scope)
        result = verify_request(request, tmpdir, no_auth=False)
        assert result == "admin"


def test_verify_request_invalid():
    """Invalid credentials should raise 401."""
    import base64
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "admin", "secret123")

        creds = base64.b64encode(b"admin:wrongpassword").decode()
        scope = {
            "type": "http",
            "headers": [(b"authorization", f"Basic {creds}".encode())],
        }
        request = Request(scope)
        with pytest.raises(HTTPException) as exc_info:
            verify_request(request, tmpdir, no_auth=False)
        assert exc_info.value.status_code == 401


def test_verify_request_no_header():
    """Missing Authorization header should raise 401."""
    with tempfile.TemporaryDirectory() as tmpdir:
        scope = {"type": "http", "headers": []}
        request = Request(scope)
        with pytest.raises(HTTPException) as exc_info:
            verify_request(request, tmpdir, no_auth=False)
        assert exc_info.value.status_code == 401


def test_create_and_load_users():
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "alice", "pw1")
        create_user(tmpdir, "bob", "pw2")
        users = load_users(tmpdir)
        usernames = [u["username"] for u in users]
        assert "alice" in usernames
        assert "bob" in usernames


def test_update_user_password():
    """Creating a user with same name should update their password."""
    with tempfile.TemporaryDirectory() as tmpdir:
        create_user(tmpdir, "alice", "old_pass")
        create_user(tmpdir, "alice", "new_pass")
        users = load_users(tmpdir)
        assert len([u for u in users if u["username"] == "alice"]) == 1
        alice = next(u for u in users if u["username"] == "alice")
        assert verify_password("new_pass", alice["password_hash"]) is True
        assert verify_password("old_pass", alice["password_hash"]) is False
