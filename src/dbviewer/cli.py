"""CLI entry point for DB Viewer."""

import argparse
import getpass
import os
import subprocess
import sys
from pathlib import Path

from . import __version__
from .config import DATA_DIR, DEFAULT_HOST, DEFAULT_PORT


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="dbviewer",
        description="DB Viewer — Web-based database management tool",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"Bind address (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"Port number (default: {DEFAULT_PORT})")
    parser.add_argument("--data-dir", default=DATA_DIR, help=f"Data directory (default: {DATA_DIR})")
    parser.add_argument("--no-auth", action="store_true", help="Disable authentication")
    parser.add_argument("--open", action="store_true", dest="open_browser", help="Open browser on start")
    parser.add_argument("--version", action="store_true", help="Show version and exit")
    parser.add_argument("--change-password", action="store_true", help="Change a user's password interactively")
    parser.add_argument("--create-user", nargs=2, metavar=("USERNAME", "PASSWORD"), help="Create a user (used by installer)")
    parser.add_argument("--update", action="store_true", help="Update to the latest version from GitHub")
    parser.add_argument("--ssl-cert", default=None, metavar="CERT_FILE",
                        help="Path to SSL certificate file (.pem) for HTTPS, or 'auto' to generate a dev cert with trustme")
    parser.add_argument("--ssl-key", default=None, metavar="KEY_FILE",
                        help="Path to SSL private key file (.pem) for HTTPS")
    parser.add_argument("--install-service", action="store_true",
                        help="Write a systemd user service file and exit")
    parser.add_argument("--log-level", default="warning",
                        choices=["critical", "error", "warning", "info", "debug"],
                        help="Uvicorn log level (default: warning)")
    parser.add_argument("--demo", action="store_true",
                        help="Start in demo mode with an in-process SQLite database (no real DB needed)")

    args = parser.parse_args()

    # --version
    if args.version:
        print(f"DB Viewer {__version__}")
        sys.exit(0)

    # --update
    if args.update:
        update_script = Path(__file__).parent.parent.parent / "update.sh"
        if update_script.exists():
            os.execv("/bin/bash", ["/bin/bash", str(update_script)])
        else:
            # Try looking relative to home
            alt = Path.home() / ".dbviewer" / "src" / "update.sh"
            if alt.exists():
                os.execv("/bin/bash", ["/bin/bash", str(alt)])
            else:
                print("update.sh not found")
                sys.exit(1)

    # --create-user (used by installer)
    if args.create_user:
        from .auth import create_user
        username, password = args.create_user
        create_user(args.data_dir, username, password)
        print(f"User '{username}' created.")
        sys.exit(0)

    # --change-password
    if args.change_password:
        from .auth import create_user, load_users
        users = load_users(args.data_dir)
        if users:
            print("Existing users: " + ", ".join(u["username"] for u in users))
        username = input("Username: ").strip()
        if not username:
            print("Username cannot be empty.")
            sys.exit(1)
        password = getpass.getpass("New password: ")
        if not password:
            print("Password cannot be empty.")
            sys.exit(1)
        confirm = getpass.getpass("Confirm password: ")
        if password != confirm:
            print("Passwords do not match.")
            sys.exit(1)
        create_user(args.data_dir, username, password)
        print(f"Password for '{username}' updated.")
        sys.exit(0)

    # --install-service
    if args.install_service:
        from .service import write_systemd_service
        write_systemd_service(
            host=args.host,
            port=args.port,
            data_dir=args.data_dir,
            no_auth=args.no_auth,
        )
        import sys; sys.exit(0)

    # Default: start the server
    from .server import start_server

    start_server(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        no_auth=args.no_auth,
        open_browser=args.open_browser,
        ssl_cert=args.ssl_cert,
        ssl_key=args.ssl_key,
        log_level=args.log_level,
        demo=args.demo,
    )
