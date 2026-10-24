#!/usr/bin/env bash
# Build Linux Release Packages: .deb (Debian/Ubuntu), .rpm (Fedora/RHEL/openSUSE), and .AppImage (Universal)
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
DIST_DIR="$REPO_ROOT/dist"
ICONS_DIR="$DIST_DIR/icons"
VERSION="0.2.0"
ARCH="amd64"
RPM_ARCH="x86_64"

mkdir -p "$DIST_DIR" "$ICONS_DIR"

echo "==> [1/4] Generating minimalist V icons..."
python3 "$REPO_ROOT/packaging/generate_icons.py" "$ICONS_DIR"

# ==============================================================================
# 1. Build .deb package (media-manager_0.2.0_amd64.deb)
# ==============================================================================
echo "==> [2/4] Building Debian/Ubuntu package (.deb)..."
DEB_STAGE="$DIST_DIR/stage_deb/media-manager_${VERSION}_${ARCH}"
rm -rf "$DEB_STAGE"
mkdir -p "$DEB_STAGE/DEBIAN"
mkdir -p "$DEB_STAGE/opt/media_manager/src/media_manager"
mkdir -p "$DEB_STAGE/usr/share/applications"
mkdir -p "$DEB_STAGE/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$DEB_STAGE/usr/share/icons/hicolor/512x512/apps"

cp "$REPO_ROOT"/media_manager/*.py "$DEB_STAGE/opt/media_manager/src/media_manager/"
cp "$REPO_ROOT/setup.py" "$REPO_ROOT/install.sh" "$REPO_ROOT/README.md" "$DEB_STAGE/opt/media_manager/src/"
cp "$ICONS_DIR/media_manager.png" "$DEB_STAGE/usr/share/icons/hicolor/256x256/apps/media-manager.png"
cp "$ICONS_DIR/media_manager_512.png" "$DEB_STAGE/usr/share/icons/hicolor/512x512/apps/media-manager.png"

cat << 'EOF' > "$DEB_STAGE/usr/share/applications/media-manager.desktop"
[Desktop Entry]
Version=1.0
Type=Application
Name=Media Manager
Comment=Busca, descarga y organiza películas y series
Exec=/usr/local/bin/media-manager-gui %U
Icon=media-manager
Terminal=false
Categories=AudioVideo;Video;Network;FileTransfer;P2P;
MimeType=application/x-bittorrent;x-scheme-handler/magnet;
StartupNotify=true
EOF

cat << EOF > "$DEB_STAGE/DEBIAN/control"
Package: media-manager
Version: $VERSION
Section: video
Priority: optional
Architecture: $ARCH
Depends: python3 (>= 3.8), python3-venv, aria2
Maintainer: ValeryJL <valeryjl@users.noreply.github.com>
Homepage: https://github.com/ValeryJL/media_manager
Description: Media Manager Desktop GUI (Flutter) & TUI/CLI
 Herramienta multiplataforma para buscar, descargar (via aria2c en segundo
 plano) y organizar peliculas y series automaticamente. Incluye aplicacion
 de escritorio nativa en Flutter (Flet) e interfaz interactiva de terminal.
EOF

cat << 'EOF' > "$DEB_STAGE/DEBIAN/postinst"
#!/usr/bin/env bash
set -e
cd /opt/media_manager/src
chmod +x ./install.sh
./install.sh --all-users
update-desktop-database /usr/share/applications 2>/dev/null || true
EOF
chmod 0755 "$DEB_STAGE/DEBIAN/postinst"

cat << 'EOF' > "$DEB_STAGE/DEBIAN/prerm"
#!/usr/bin/env bash
set -e
systemctl stop media-manager-aria2.service 2>/dev/null || true
systemctl disable media-manager-aria2.service 2>/dev/null || true
EOF
chmod 0755 "$DEB_STAGE/DEBIAN/prerm"

DEB_OUT="$DIST_DIR/media-manager_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$DEB_STAGE" "$DEB_OUT"
echo "[OK] Created: $DEB_OUT"

# ==============================================================================
# 2. Build .rpm package (media-manager-0.2.0-1.x86_64.rpm)
# ==============================================================================
echo "==> [3/4] Building Fedora/RHEL/openSUSE package (.rpm)..."
if command -v rpmbuild &> /dev/null; then
    RPM_TOP="$DIST_DIR/stage_rpm"
    rm -rf "$RPM_TOP"
    mkdir -p "$RPM_TOP"/{BUILD,RPMS,SOURCES,SPECS,SRPMS}

    cat << EOF > "$RPM_TOP/SPECS/media-manager.spec"
Name:           media-manager
Version:        $VERSION
Release:        1
Summary:        Media Manager Desktop GUI (Flutter) and TUI/CLI
License:        MIT
URL:            https://github.com/ValeryJL/media_manager
BuildArch:      $RPM_ARCH
Requires:       python3, aria2
AutoReqProv:    no

%description
Herramienta multiplataforma para buscar, descargar (via aria2c) y organizar
peliculas y series automaticamente con interfaz grafica Flutter y TUI/CLI.

%install
mkdir -p %{buildroot}/opt/media_manager/src/media_manager
mkdir -p %{buildroot}/usr/share/applications
mkdir -p %{buildroot}/usr/share/icons/hicolor/256x256/apps
cp -r "$DEB_STAGE/opt/media_manager/src/"* %{buildroot}/opt/media_manager/src/
cp "$DEB_STAGE/usr/share/applications/media-manager.desktop" %{buildroot}/usr/share/applications/
cp "$DEB_STAGE/usr/share/icons/hicolor/256x256/apps/media-manager.png" %{buildroot}/usr/share/icons/hicolor/256x256/apps/

%post
cd /opt/media_manager/src && chmod +x ./install.sh && ./install.sh --all-users || true

%files
/opt/media_manager/src
/usr/share/applications/media-manager.desktop
/usr/share/icons/hicolor/256x256/apps/media-manager.png
EOF

    rpmbuild --define "_topdir $RPM_TOP" -bb "$RPM_TOP/SPECS/media-manager.spec"
    find "$RPM_TOP/RPMS" -name "*.rpm" -exec cp {} "$DIST_DIR/media-manager-${VERSION}-1.${RPM_ARCH}.rpm" \;
    echo "[OK] Created: $DIST_DIR/media-manager-${VERSION}-1.${RPM_ARCH}.rpm"
else
    echo "[WARN] rpmbuild not found; skipping .rpm build."
fi

# ==============================================================================
# 3. Build Universal .AppImage (Media_Manager-0.2.0-x86_64.AppImage)
# ==============================================================================
echo "==> [4/4] Building Universal Linux AppImage (.AppImage)..."
APPDIR="$DIST_DIR/stage_appimage/Media_Manager.AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/python" "$APPDIR/usr/share/icons/hicolor/256x256/apps"

# Bundle the complete base Python runtime (including libpython*.so and stdlib)
# so the AppImage runs on any Linux distribution regardless of host Python version.
PY_BASE="$(python3 -c 'import sys; print(sys.base_prefix)')"
cp -a "$PY_BASE/." "$APPDIR/usr/python/"
rm -rf "$APPDIR/usr/python/test" "$APPDIR/usr/python/lib/python"*/test 2>/dev/null || true

"$APPDIR/usr/python/bin/python3" -m pip install --upgrade pip --quiet
"$APPDIR/usr/python/bin/python3" -m pip install pirate-get --quiet
"$APPDIR/usr/python/bin/python3" -m pip install "$REPO_ROOT" --quiet

cp "$ICONS_DIR/media_manager.png" "$APPDIR/media-manager.png"
cp "$ICONS_DIR/media_manager.png" "$APPDIR/.DirIcon"
cp "$ICONS_DIR/media_manager.png" "$APPDIR/usr/share/icons/hicolor/256x256/apps/media-manager.png"

cat << 'EOF' > "$APPDIR/media-manager.desktop"
[Desktop Entry]
Type=Application
Name=Media Manager
Comment=Busca, descarga y organiza películas y series
Exec=AppRun %U
Icon=media-manager
Categories=AudioVideo;Video;Network;FileTransfer;P2P;
Terminal=false
EOF

cat << 'EOF' > "$APPDIR/AppRun"
#!/usr/bin/env bash
HERE="$(dirname "$(readlink -f "${0}")")"
export PYTHONHOME="$HERE/usr/python"
export LD_LIBRARY_PATH="$HERE/usr/python/lib:${LD_LIBRARY_PATH:-}"
export PATH="$HERE/usr/python/bin:$PATH"
if [ "$1" = "--cli" ]; then
    shift
    exec "$HERE/usr/python/bin/python3" -m media_manager.cli "$@"
else
    exec "$HERE/usr/python/bin/python3" -m media_manager.gui "$@"
fi
EOF
chmod 0755 "$APPDIR/AppRun"

APPIMAGETOOL="$DIST_DIR/appimagetool-x86_64.AppImage"
if [ ! -f "$APPIMAGETOOL" ]; then
    curl -fsSL -o "$APPIMAGETOOL" "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-x86_64.AppImage"
    chmod +x "$APPIMAGETOOL"
fi

ARCH=x86_64 "$APPIMAGETOOL" --appimage-extract-and-run "$APPDIR" "$DIST_DIR/Media_Manager-${VERSION}-x86_64.AppImage"
rm -f "$APPIMAGETOOL"
rm -rf "$DIST_DIR/stage_deb" "$DIST_DIR/stage_rpm" "$DIST_DIR/stage_appimage"
echo "[OK] Created: $DIST_DIR/Media_Manager-${VERSION}-x86_64.AppImage"
