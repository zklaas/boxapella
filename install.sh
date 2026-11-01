#!/usr/bin/env bash
# Install a `boxapella` launcher on your PATH (~/.local/bin by default).
# Boxapella runs from its own virtualenv (.venv, sharing the system PyQt6 and
# numpy) holding imageio-ffmpeg, whose bundled ffmpeg can record from cameras.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-$HOME/.local/bin}"
LAUNCHER="$BIN_DIR/boxapella"
VENV="$APP_DIR/.venv"

if [ ! -x "$VENV/bin/python" ]; then
  python3 -m venv --system-site-packages "$VENV"
fi
"$VENV/bin/python" -c "import imageio_ffmpeg, numpy" 2>/dev/null || \
  "$VENV/bin/pip" install --quiet numpy imageio-ffmpeg

mkdir -p "$BIN_DIR"
cat > "$LAUNCHER" <<EOT
#!/usr/bin/env bash
exec "$VENV/bin/python" "$APP_DIR/boxapella.py" "\$@"
EOT
chmod +x "$LAUNCHER"
echo "Installed: $LAUNCHER"

if [ -x "$APP_DIR/install-desktop.sh" ]; then
  "$APP_DIR/install-desktop.sh" "$BIN_DIR" || true
fi

python3 -c "import PyQt6.QtWidgets" 2>/dev/null || \
  echo "NOTE: Boxapella needs PyQt6:  sudo apt install python3-pyqt6"
command -v pw-record >/dev/null || echo "NOTE: Boxapella records audio with pw-record (PipeWire)."
command -v vocalfry >/dev/null || [ -x "$BIN_DIR/vocalfry" ] || \
  echo "NOTE: VocalFry isn't installed; the Voice column will be disabled."

if ! printf '%s' ":$PATH:" | grep -q ":$BIN_DIR:"; then
  echo "NOTE: $BIN_DIR is not on your PATH."
else
  echo "Run it with:  boxapella"
fi
