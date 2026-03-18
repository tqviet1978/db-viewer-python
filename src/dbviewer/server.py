"""FastAPI application factory and Uvicorn launcher."""

from __future__ import annotations

from pathlib import Path

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles


def create_app(data_dir: str, no_auth: bool = False) -> FastAPI:
    app = FastAPI(title="DB Viewer", version="1.0.0", docs_url=None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    from .api import create_router
    router = create_router(data_dir=data_dir, no_auth=no_auth)
    app.include_router(router, prefix="/api")

    static_dir = Path(__file__).parent / "static"

    @app.get("/")
    async def index():
        return FileResponse(static_dir / "index.html")

    # Serve any other static assets if present
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def generate_dev_cert(data_dir: str) -> tuple[str, str]:
    """Generate a self-signed dev certificate with trustme.

    Certificate and key are written to data_dir and reused on subsequent
    invocations. Returns (cert_path, key_path).
    """
    import trustme
    from pathlib import Path as _P

    cert_path = str(_P(data_dir) / "dev-cert.pem")
    key_path  = str(_P(data_dir) / "dev-key.pem")

    if _P(cert_path).exists() and _P(key_path).exists():
        return cert_path, key_path

    ca = trustme.CA()
    server_cert = ca.issue_cert("localhost", "127.0.0.1")

    # Write cert chain (trustme Blob objects have a .bytes() method)
    with open(cert_path, "wb") as f:
        for blob in server_cert.cert_chain_pems:
            f.write(blob.bytes())
    # Write private key (write_to_path expects a Path/str, not a file handle)
    server_cert.private_key_pem.write_to_path(key_path)

    return cert_path, key_path


def _setup_demo_mode(data_dir: str) -> None:
    """Seed the data dir with a demo SQLite connection if no connections exist."""
    import json
    from pathlib import Path as _P
    from .config import get_connections, save_json

    conns = get_connections(data_dir)
    if not conns:
        demo_db = str(_P(data_dir) / "demo.sqlite")
        save_json(str(_P(data_dir) / "connections.json"), [
            {
                "name": "Demo SQLite",
                "type": "sqlite",
                "database": demo_db,
                "server": "",
                "user": "",
                "password": "",
                "port": 0,
            }
        ])
        # Seed the demo DB with sample tables
        from .drivers.sqlite import SQLiteDriver
        d = SQLiteDriver()
        d.initialize({"database": demo_db, "type": "sqlite"})
        d.create_table(
            "CREATE TABLE IF NOT EXISTS DEMO_USERS ("
            "ID INTEGER PRIMARY KEY AUTOINCREMENT, UUID TEXT, NAME TEXT, EMAIL TEXT, "
            "ROLE TEXT, CREATED_AT TEXT, GUID INTEGER DEFAULT 1)"
        )
        d.create_table(
            "CREATE TABLE IF NOT EXISTS DEMO_ORDERS ("
            "ID INTEGER PRIMARY KEY AUTOINCREMENT, UUID TEXT, ID_USER INTEGER, "
            "PRODUCT TEXT, TOTAL_VALUE REAL, ORDER_DATE TEXT, GUID INTEGER DEFAULT 1)"
        )
        d.seed("DEMO_USERS", [
            {"UUID": "u001", "NAME": "Alice Smith",  "EMAIL": "alice@example.com",  "ROLE": "admin",   "CREATED_AT": "2024-01-01"},
            {"UUID": "u002", "NAME": "Bob Jones",    "EMAIL": "bob@example.com",    "ROLE": "editor",  "CREATED_AT": "2024-02-15"},
            {"UUID": "u003", "NAME": "Carol White",  "EMAIL": "carol@example.com",  "ROLE": "viewer",  "CREATED_AT": "2024-03-20"},
            {"UUID": "u004", "NAME": "Dave Brown",   "EMAIL": "dave@example.com",   "ROLE": "editor",  "CREATED_AT": "2024-04-05"},
            {"UUID": "u005", "NAME": "Eve Davis",    "EMAIL": "eve@example.com",    "ROLE": "viewer",  "CREATED_AT": "2024-05-12"},
        ])
        d.seed("DEMO_ORDERS", [
            {"UUID": "o001", "ID_USER": 1, "PRODUCT": "Widget A",  "TOTAL_VALUE": 99.50,  "ORDER_DATE": "2024-06-01"},
            {"UUID": "o002", "ID_USER": 1, "PRODUCT": "Widget B",  "TOTAL_VALUE": 149.99, "ORDER_DATE": "2024-06-15"},
            {"UUID": "o003", "ID_USER": 2, "PRODUCT": "Gadget X",  "TOTAL_VALUE": 299.00, "ORDER_DATE": "2024-07-02"},
            {"UUID": "o004", "ID_USER": 3, "PRODUCT": "Gadget Y",  "TOTAL_VALUE": 75.25,  "ORDER_DATE": "2024-07-20"},
            {"UUID": "o005", "ID_USER": 4, "PRODUCT": "Doohickey", "TOTAL_VALUE": 50.00,  "ORDER_DATE": "2024-08-01"},
        ])
        d.close()
        print("  Demo data  →  DEMO_USERS (5 rows), DEMO_ORDERS (5 rows)")


def start_server(
    host: str = "0.0.0.0",
    port: int = 9876,
    data_dir: str | None = None,
    no_auth: bool = False,
    open_browser: bool = False,
    ssl_cert: str | None = None,
    ssl_key: str | None = None,
    log_level: str = "warning",
    demo: bool = False,
) -> None:
    from .config import DATA_DIR, ensure_data_dir
    data_dir = data_dir or DATA_DIR
    ensure_data_dir(data_dir)

    # Demo mode: seed SQLite connection + disable auth
    if demo:
        _setup_demo_mode(data_dir)
        no_auth = True
        print("  Mode       →  DEMO (SQLite, no auth)")

    # HTTPS auto-cert: generate dev cert if --https flag given without explicit files
    auto_cert_used = False
    if ssl_cert == "auto":
        try:
            ssl_cert, ssl_key = generate_dev_cert(data_dir)
            auto_cert_used = True
        except ImportError:
            print("  WARNING: 'trustme' not installed. Run: pip install trustme")
            ssl_cert = ssl_key = None

    # Validate explicit SSL files
    if ssl_cert or ssl_key:
        import os
        if not ssl_cert or not ssl_key:
            raise ValueError("Both --ssl-cert and --ssl-key must be provided together.")
        if not auto_cert_used:
            for f, label in [(ssl_cert, "--ssl-cert"), (ssl_key, "--ssl-key")]:
                if not os.path.isfile(f):
                    raise FileNotFoundError(f"{label}: file not found: {f}")

    app = create_app(data_dir=data_dir, no_auth=no_auth)

    scheme = "https" if ssl_cert else "http"
    display_host = "localhost" if host == "0.0.0.0" else host
    print(f"  DB Viewer  →  {scheme}://{display_host}:{port}")
    print(f"  Data dir   →  {data_dir}")
    if no_auth and not demo:
        print("  Auth       →  DISABLED")
    if auto_cert_used:
        print(f"  TLS        →  auto-generated dev cert (localhost only)")
    elif ssl_cert:
        print(f"  TLS cert   →  {ssl_cert}")

    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"{scheme}://localhost:{port}")).start()

    uvicorn_kwargs: dict = dict(host=host, port=port, log_level=log_level)
    if ssl_cert:
        uvicorn_kwargs["ssl_certfile"] = ssl_cert
        uvicorn_kwargs["ssl_keyfile"] = ssl_key
    uvicorn.run(app, **uvicorn_kwargs)
