#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$HOME/.dbviewer"
REPO_URL="https://github.com/cloudpad9/db-viewer-python.git"

echo "==> Installing DB Viewer..."

mkdir -p "$INSTALL_DIR"

TMPDIR=$(mktemp -d)
git clone --depth 1 "$REPO_URL" "$TMPDIR/src"

python3 -m venv "$INSTALL_DIR/.venv"
source "$INSTALL_DIR/.venv/bin/activate"

pip install --quiet "$TMPDIR/src"

mkdir -p "$INSTALL_DIR/bin"
cat > "$INSTALL_DIR/bin/dbviewer" << 'WRAPPER'
#!/usr/bin/env bash
source "$HOME/.dbviewer/.venv/bin/activate"
python -m dbviewer "$@"
WRAPPER
chmod +x "$INSTALL_DIR/bin/dbviewer"

for rc in "$HOME/.bashrc" "$HOME/.zshrc"; do
    if [ -f "$rc" ]; then
        grep -q '.dbviewer/bin' "$rc" || echo 'export PATH="$HOME/.dbviewer/bin:$PATH"' >> "$rc"
    fi
done

mkdir -p "$INSTALL_DIR/data"

if [ ! -f "$INSTALL_DIR/data/users.json" ]; then
    echo ""
    read -p "Admin username [admin]: " ADMIN_USER
    ADMIN_USER=${ADMIN_USER:-admin}
    read -sp "Admin password: " ADMIN_PASS
    echo ""
    "$INSTALL_DIR/bin/dbviewer" --create-user "$ADMIN_USER" "$ADMIN_PASS"
fi

if [ ! -f "$INSTALL_DIR/data/connections.json" ]; then
    cat > "$INSTALL_DIR/data/connections.json" << 'EOF'
[
    {
        "name": "Local MySQL",
        "type": "mysql",
        "server": "localhost",
        "port": 3306,
        "database": "mysql",
        "user": "root",
        "password": ""
    }
]
EOF
fi

rm -rf "$TMPDIR"

echo ""
echo "==> DB Viewer installed successfully!"
echo "    Open a new terminal and run: dbviewer"
