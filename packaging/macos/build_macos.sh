#!/usr/bin/env bash
# Build macOS Release Packages: MediaManager-0.2.0-macOS.dmg and MediaManager-0.2.0-macOS-Installer.pkg
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ICONS_DIR="$DIST_DIR/icons"
STAGE_DIR="$DIST_DIR/stage_macos"
VERSION="0.2.0"

mkdir -p "$DIST_DIR" "$ICONS_DIR"
rm -rf "$STAGE_DIR"
mkdir -p "$STAGE_DIR/dmg_root"

echo "==> [1/4] Generating macOS icons (.icns & .png)..."
python3 "$REPO_ROOT/packaging/generate_icons.py" "$ICONS_DIR"

echo "==> [2/4] Building Media Manager.app bundle..."
APP_BUNDLE="$STAGE_DIR/dmg_root/Media Manager.app"
mkdir -p "$APP_BUNDLE/Contents/MacOS"
mkdir -p "$APP_BUNDLE/Contents/Resources/src/media_manager"

cp "$REPO_ROOT"/media_manager/*.py "$APP_BUNDLE/Contents/Resources/src/media_manager/"
cp "$REPO_ROOT/setup.py" "$REPO_ROOT/install.sh" "$REPO_ROOT/README.md" "$APP_BUNDLE/Contents/Resources/src/"
cp "$ICONS_DIR/media_manager.png" "$APP_BUNDLE/Contents/Resources/media_manager.png"
if [ -f "$ICONS_DIR/media_manager.icns" ]; then
    cp "$ICONS_DIR/media_manager.icns" "$APP_BUNDLE/Contents/Resources/media_manager.icns"
fi

cat << 'EOF' > "$APP_BUNDLE/Contents/MacOS/Media Manager"
#!/usr/bin/env bash
DIR="$(cd "$(dirname "$0")/../Resources" && pwd)"
VENV_DIR="$HOME/.local/share/media_manager/venv"
if [ -d "/Users/Shared/.local/share/media_manager/venv" ]; then
    VENV_DIR="/Users/Shared/.local/share/media_manager/venv"
elif [ ! -x "$VENV_DIR/bin/python" ]; then
    cd "$DIR/src" && ./install.sh --current-user
fi
exec "$VENV_DIR/bin/python" -m media_manager.gui "$@"
EOF
chmod 0755 "$APP_BUNDLE/Contents/MacOS/Media Manager"

cat << EOF > "$APP_BUNDLE/Contents/Info.plist"
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key>
    <string>Media Manager</string>
    <key>CFBundleDisplayName</key>
    <string>Media Manager</string>
    <key>CFBundleIdentifier</key>
    <string>org.mediamanager.app</string>
    <key>CFBundleVersion</key>
    <string>$VERSION</string>
    <key>CFBundleShortVersionString</key>
    <string>$VERSION</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleExecutable</key>
    <string>Media Manager</string>
    <key>CFBundleIconFile</key>
    <string>media_manager.icns</string>
    <key>NSHighResolutionCapable</key>
    <true/>
</dict>
</plist>
EOF

ln -s /Applications "$STAGE_DIR/dmg_root/Applications"

echo "==> [3/4] Creating macOS Disk Image (.dmg)..."
DMG_OUT="$DIST_DIR/MediaManager-${VERSION}-macOS.dmg"
rm -f "$DMG_OUT"
hdiutil create -volname "Media Manager" -srcfolder "$STAGE_DIR/dmg_root" -ov -format UDZO "$DMG_OUT"
echo "[OK] Created: $DMG_OUT"

echo "==> [4/4] Creating macOS System Installer (.pkg)..."
PKG_OUT="$DIST_DIR/MediaManager-${VERSION}-macOS-Installer.pkg"
rm -f "$PKG_OUT"
pkgbuild --root "$STAGE_DIR/dmg_root" \
         --identifier "org.mediamanager.app" \
         --version "$VERSION" \
         --install-location "/Applications" \
         "$PKG_OUT" || true

rm -rf "$STAGE_DIR"
echo "[OK] macOS build complete."
