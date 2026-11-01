#!/usr/bin/env bash
# Register Boxapella with the desktop so it appears in GNOME's dash and
# "Show Applications" grid with the Boxapella icon.
#
# Installs, under ~/.local (no root needed):
#   - PNG icons into  ~/.local/share/icons/hicolor/<size>/apps/boxapella.png
#   - ~/.local/share/applications/boxapella.desktop
#
# Run install.sh first so the `boxapella` launcher exists on your PATH.  Re-run
# this after make_icon.py to refresh the icon.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN_DIR="${1:-$HOME/.local/bin}"
DATA_DIR="$HOME/.local/share"
ICON_ROOT="$DATA_DIR/icons/hicolor"
APPS_DIR="$DATA_DIR/applications"

mkdir -p "$APPS_DIR" "$ICON_ROOT"

# gtk-update-icon-cache refuses to run on a theme dir with no index.theme;
# borrow the system hicolor one so the per-user overlay is a valid theme.
if [ ! -e "$ICON_ROOT/index.theme" ] && [ -f /usr/share/icons/hicolor/index.theme ]; then
  cp /usr/share/icons/hicolor/index.theme "$ICON_ROOT/index.theme"
fi

for size in 512 256 128 64 48; do
  if [ "$size" = 512 ]; then src="$APP_DIR/icons/boxapella.png"; else src="$APP_DIR/icons/boxapella-$size.png"; fi
  [ -f "$src" ] || continue
  dst="$ICON_ROOT/${size}x${size}/apps"
  mkdir -p "$dst"
  cp "$src" "$dst/boxapella.png"
done
mkdir -p "$DATA_DIR/pixmaps"
cp "$APP_DIR/icons/boxapella.png" "$DATA_DIR/pixmaps/boxapella.png"

DESKTOP="$APPS_DIR/boxapella.desktop"
cat > "$DESKTOP" <<EOT
[Desktop Entry]
Type=Application
Version=1.0
Name=Boxapella
GenericName=Multitrack Video Recorder
Comment=Record yourself take after take into the insets of a screen layout and mix them into one master video
Keywords=video;a cappella;multitrack;camera;webcam;split screen;choir;
Exec=$BIN_DIR/boxapella
Icon=boxapella
Terminal=false
Categories=AudioVideo;Video;Audio;Recorder;
StartupNotify=true
StartupWMClass=boxapella
EOT
chmod 644 "$DESKTOP"
echo "Installed: $DESKTOP"

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "$APPS_DIR" || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "$ICON_ROOT" >/dev/null 2>&1 || true
fi

echo "Done. If the icon doesn't appear right away, log out and back in."
