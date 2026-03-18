#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.dbviewer"
REPO_URL="https://github.com/cloudpad9/db-viewer-python.git"

echo "==> Updating DB Viewer..."

if systemctl is-active --quiet dbviewer 2>/dev/null; then
    RESTART_SERVICE=1
    sudo systemctl stop dbviewer
else
    RESTART_SERVICE=0
fi

TMPDIR=$(mktemp -d)
git clone --depth 1 "$REPO_URL" "$TMPDIR/src"

source "$INSTALL_DIR/.venv/bin/activate"
pip install --quiet "$TMPDIR/src"

rm -rf "$TMPDIR"

if [ "$RESTART_SERVICE" = "1" ]; then
    sudo systemctl start dbviewer
fi

echo "==> Update complete!"
