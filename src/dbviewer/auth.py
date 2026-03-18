"""Authentication — bcrypt password hashing and HTTP Basic verification."""

import base64
import json
from pathlib import Path

import bcrypt
from fastapi import HTTPException, Request


def hash_password(password: str) -> str:
    """Hash password with bcrypt, cost factor 12."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verify password against bcrypt hash."""
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except Exception:
        return False


def load_users(data_dir: str) -> list[dict]:
    """Load users from users.json."""
    path = Path(data_dir) / "users.json"
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_users(data_dir: str, users: list[dict]) -> None:
    """Save users list to users.json."""
    path = Path(data_dir) / "users.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(users, ensure_ascii=False, indent=2), encoding="utf-8")


def create_user(data_dir: str, username: str, password: str) -> None:
    """Create or update a user in users.json."""
    users = load_users(data_dir)
    # Remove existing user with same name
    users = [u for u in users if u.get("username") != username]
    users.append({"username": username, "password_hash": hash_password(password)})
    save_users(data_dir, users)


def verify_request(request: Request, data_dir: str, no_auth: bool = False) -> str:
    """
    Verify credentials from Authorization: Basic header.
    Returns username if valid, raises HTTPException(401) if not.
    If no_auth is True, always returns "anonymous".
    """
    if no_auth:
        return "anonymous"

    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Basic "):
        raise HTTPException(
            status_code=401,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic"},
        )

    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
        username, password = decoded.split(":", 1)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    users = load_users(data_dir)
    for user in users:
        if user.get("username") == username and verify_password(password, user.get("password_hash", "")):
            return username

    raise HTTPException(status_code=401, detail="Invalid credentials")
