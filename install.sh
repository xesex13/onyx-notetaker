#!/usr/bin/env bash
# ONYX installer (Linux/macOS).
# Downloads the repo, unpacks it into ~/.onyx, and wires a global `onyx` launcher.

set -euo pipefail

REPO_URL="https://github.com/xesex13/onyx-notetaker/archive/refs/heads/main.tar.gz"
ONYX_HOME="$HOME/.onyx"
TMP_TAR="$(mktemp -t onyx-notetaker.XXXXXX.tar.gz)"

echo "Downloading ONYX from $REPO_URL ..."
curl -fsSL "$REPO_URL" -o "$TMP_TAR"

echo "Installing to $ONYX_HOME ..."
rm -rf "$ONYX_HOME"
mkdir -p "$ONYX_HOME"
tar -xzf "$TMP_TAR" -C "$ONYX_HOME" --strip-components=1

rm -f "$TMP_TAR"

echo "Installing Python dependencies ..."
python3 -m pip install --upgrade -e "$ONYX_HOME"

BIN_DIR="/usr/local/bin"
if [ ! -w "$BIN_DIR" ]; then
    BIN_DIR="$HOME/.local/bin"
    mkdir -p "$BIN_DIR"
fi

cat > "$BIN_DIR/onyx" <<EOF
#!/usr/bin/env bash
exec python3 "$ONYX_HOME/src/onyx_vault/main.py" "\$@"
EOF
chmod +x "$BIN_DIR/onyx"

echo "ONYX installed. Run 'onyx' from any new terminal to start."
echo "(If 'onyx' isn't found, make sure $BIN_DIR is on your PATH.)"
