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


def start_server(
    host: str = "0.0.0.0",
    port: int = 9876,
    data_dir: str | None = None,
    no_auth: bool = False,
    open_browser: bool = False,
) -> None:
    from .config import DATA_DIR, ensure_data_dir
    data_dir = data_dir or DATA_DIR
    ensure_data_dir(data_dir)

    app = create_app(data_dir=data_dir, no_auth=no_auth)

    print(f"  DB Viewer  →  http://{'localhost' if host == '0.0.0.0' else host}:{port}")
    print(f"  Data dir   →  {data_dir}")
    if no_auth:
        print("  Auth       →  DISABLED")

    if open_browser:
        import threading
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(f"http://localhost:{port}")).start()

    uvicorn.run(app, host=host, port=port, log_level="warning")
