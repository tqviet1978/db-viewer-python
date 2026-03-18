"""Systemd user service file generator.

Writes a ready-to-use systemd user service to
~/.config/systemd/user/dbviewer.service and prints activation instructions.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_SERVICE_TEMPLATE = """\
[Unit]
Description=DB Viewer — web-based database management tool
After=network.target

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=5
Environment=HOME={home}
WorkingDirectory={home}

[Install]
WantedBy=default.target
"""


def _find_dbviewer_executable() -> str:
    """Locate the dbviewer executable, preferring the venv wrapper."""
    # 1. Installed via install.sh → ~/.dbviewer/bin/dbviewer
    wrapper = Path.home() / ".dbviewer" / "bin" / "dbviewer"
    if wrapper.exists():
        return str(wrapper)

    # 2. Current Python interpreter's bin directory
    import shutil
    found = shutil.which("dbviewer")
    if found:
        return found

    # 3. Fall back to "python -m dbviewer" with the current interpreter
    return f"{sys.executable} -m dbviewer"


def write_systemd_service(
    host: str = "0.0.0.0",
    port: int = 9876,
    data_dir: str | None = None,
    no_auth: bool = False,
) -> Path:
    """Generate and write a systemd user service file.

    Returns the path to the written file.
    """
    from .config import DATA_DIR
    data_dir = data_dir or DATA_DIR

    executable = _find_dbviewer_executable()
    args = f"--host {host} --port {port} --data-dir {data_dir}"
    if no_auth:
        args += " --no-auth"
    exec_start = f"{executable} {args}"

    service_dir = Path.home() / ".config" / "systemd" / "user"
    service_dir.mkdir(parents=True, exist_ok=True)
    service_path = service_dir / "dbviewer.service"

    content = _SERVICE_TEMPLATE.format(
        exec_start=exec_start,
        home=str(Path.home()),
    )

    service_path.write_text(content, encoding="utf-8")

    print(f"\n✅  Service file written to:\n    {service_path}\n")
    print("To activate the service, run:\n")
    print("    systemctl --user daemon-reload")
    print("    systemctl --user enable --now dbviewer")
    print("\nTo check status:")
    print("    systemctl --user status dbviewer")
    print("\nTo view logs:")
    print("    journalctl --user -u dbviewer -f\n")

    return service_path
