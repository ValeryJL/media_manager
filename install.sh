#!/usr/bin/env bash

set -e

echo "=========================================="
echo "  Installing Media Manager CLI"
echo "=========================================="
echo ""

INSTALL_ALL_USERS=""
for arg in "$@"; do
    case "$arg" in
        --all-users)
            INSTALL_ALL_USERS="true"
            ;;
        --current-user)
            INSTALL_ALL_USERS="false"
            ;;
    esac
done

if [[ "$OSTYPE" == "darwin"* ]]; then
    PUBLIC_DIR="/Users/Shared"
else
    PUBLIC_DIR="/srv/public"
fi

if [ -z "$INSTALL_ALL_USERS" ]; then
    echo "Select installation scope:"
    echo "  [1] Current user only ($HOME)"
    echo "  [2] All users ($PUBLIC_DIR)"
    read -r -p "Choose an option (1/2) [Default: 2]: " choice
    if [ "$choice" = "1" ]; then
        INSTALL_ALL_USERS="false"
    else
        INSTALL_ALL_USERS="true"
    fi
    echo ""
fi

if [ "$INSTALL_ALL_USERS" = "true" ]; then
    BASE_DIR="$PUBLIC_DIR"
    if [ ! -d "$BASE_DIR" ]; then
        sudo mkdir -p "$BASE_DIR"
        sudo chmod 0777 "$BASE_DIR"
    fi
else
    BASE_DIR="$HOME"
fi

echo "Selected mode: $BASE_DIR"
echo ""

# 1. Install system dependencies if apt is available
if command -v apt-get &> /dev/null; then
    echo "[1/6] Installing system dependencies (aria2)..."
    sudo apt-get update
    sudo apt-get install -y aria2
else
    echo "[1/6] Checking aria2..."
    if ! command -v aria2c &> /dev/null; then
        echo "Warning: apt-get not found and aria2c is missing. Please install 'aria2' using your package manager."
    fi
fi

# 2. Set up Python virtual environment
echo "[2/6] Setting up Python virtual environment in $BASE_DIR..."
VENV_DIR="$BASE_DIR/.local/share/media_manager/venv"
mkdir -p "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"

# 3. Install python dependencies and the app itself inside the venv
echo "[3/6] Installing pirate-get and media-manager inside venv..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install pirate-get --quiet
"$VENV_DIR/bin/pip" install . --quiet

# 4. Setup media folders and configuration (without deleting existing media)
echo "[4/6] Creating media directories and configuration in $BASE_DIR..."
mkdir -p "$BASE_DIR/Media/Downloads" "$BASE_DIR/Media/Movies" "$BASE_DIR/Media/Shows"
CONFIG_DIR="$BASE_DIR/.config/media_manager"
mkdir -p "$CONFIG_DIR"
touch "$CONFIG_DIR/aria2.session"

if [ ! -f "$CONFIG_DIR/config.yml" ]; then
    cat << EOF > "$CONFIG_DIR/config.yml"
download_path: $BASE_DIR/Media/Downloads
media_path: $BASE_DIR/Media
EOF
fi

# Create daemon startup script
START_DAEMON_SH="$CONFIG_DIR/start_daemon.sh"
cat << EOF > "$START_DAEMON_SH"
#!/usr/bin/env bash
umask 0000
export MEDIA_MANAGER_HOME="$BASE_DIR"
"$VENV_DIR/bin/python" -c "from media_manager.downloader import ensure_daemon; ensure_daemon()"
EOF
chmod 0755 "$START_DAEMON_SH"

# If installing for all users, clean up old single-user installation remnants for current user
if [ "$INSTALL_ALL_USERS" = "true" ] && [ "$BASE_DIR" != "$HOME" ]; then
    rm -rf "$HOME/.config/media_manager" "$HOME/.local/share/media_manager" 2>/dev/null || true
    rm -f "$HOME/.local/bin/media-manager" "$HOME/.local/bin/pirate-get" "$HOME/.local/bin/aria2p" 2>/dev/null || true
    sudo chmod -R a+rwX "$BASE_DIR/Media" "$CONFIG_DIR" "$BASE_DIR/.local" 2>/dev/null || true
fi

# 5. Generate hook script and start/reload aria2c daemon in background
echo "[5/6] Initializing background event hook and aria2c daemon..."
MEDIA_MANAGER_HOME="$BASE_DIR" "$VENV_DIR/bin/python" -c "from media_manager.downloader import create_hook_script, ensure_daemon; create_hook_script(); ensure_daemon()"

# 6. Create symlinks and configure system boot service (systemd)
echo "[6/6] Configuring symlinks and startup service..."
BIN_DIR="$BASE_DIR/.local/bin"
mkdir -p "$BIN_DIR"
ln -sf "$VENV_DIR/bin/media-manager" "$BIN_DIR/media-manager"
ln -sf "$VENV_DIR/bin/media-manager-gui" "$BIN_DIR/media-manager-gui"
ln -sf "$VENV_DIR/bin/pirate-get" "$BIN_DIR/pirate-get"
ln -sf "$VENV_DIR/bin/aria2p" "$BIN_DIR/aria2p"

# Install native OS desktop launcher (.desktop on Linux, .app bundle on macOS)
echo "Installing native Desktop GUI launcher (Flutter)..."
if [ "$INSTALL_ALL_USERS" = "true" ]; then
    MEDIA_MANAGER_HOME="$BASE_DIR" "$VENV_DIR/bin/python" -c "from media_manager.gui import install_desktop_shortcut; install_desktop_shortcut(True)" || true
else
    MEDIA_MANAGER_HOME="$BASE_DIR" "$VENV_DIR/bin/python" -c "from media_manager.gui import install_desktop_shortcut; install_desktop_shortcut(False)" || true
fi

if [ "$INSTALL_ALL_USERS" = "true" ]; then
    if [ -d "/usr/local/bin" ]; then
        echo "Adding global symlinks to /usr/local/bin..."
        sudo ln -sf "$VENV_DIR/bin/media-manager" "/usr/local/bin/media-manager" || true
        sudo ln -sf "$VENV_DIR/bin/media-manager-gui" "/usr/local/bin/media-manager-gui" || true
        sudo ln -sf "$VENV_DIR/bin/pirate-get" "/usr/local/bin/pirate-get" || true
        sudo ln -sf "$VENV_DIR/bin/aria2p" "/usr/local/bin/aria2p" || true
    fi

    # Register systemd system service to run aria2c on system boot (survives user logouts)
    if command -v systemctl &> /dev/null && [ -d "/etc/systemd/system" ]; then
        echo "Registering systemd service (media-manager-aria2.service) to start at boot..."
        sudo tee /etc/systemd/system/media-manager-aria2.service > /dev/null << EOF
[Unit]
Description=Media Manager aria2c Background Daemon
After=network-online.target
Wants=network-online.target

[Service]
Type=forking
UMask=0000
Environment="MEDIA_MANAGER_HOME=$BASE_DIR"
ExecStart=$START_DAEMON_SH
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        sudo systemctl daemon-reload || true
        sudo systemctl enable media-manager-aria2.service || true
        sudo systemctl start media-manager-aria2.service || true
        echo "[OK] systemd service 'media-manager-aria2' enabled at system startup."
    fi
else
    # Single-user systemd service
    if command -v systemctl &> /dev/null; then
        USER_SYSTEMD_DIR="$HOME/.config/systemd/user"
        mkdir -p "$USER_SYSTEMD_DIR"
        cat << EOF > "$USER_SYSTEMD_DIR/media-manager-aria2.service"
[Unit]
Description=Media Manager aria2c User Daemon
After=network.target

[Service]
Type=forking
Environment="MEDIA_MANAGER_HOME=$BASE_DIR"
ExecStart=$START_DAEMON_SH
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable --now media-manager-aria2.service 2>/dev/null || true
    fi

    # Check if ~/.local/bin is in PATH
    if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
        echo ""
        echo "WARNING: $BIN_DIR is not in your PATH."
        echo "Please add the following line to your ~/.bashrc or ~/.zshrc:"
        echo "export PATH=\"$BIN_DIR:\$PATH\""
        echo ""
    fi
fi

echo ""
echo "======================================================"
echo "  Installation complete!"
echo "======================================================"
echo "Downloads folder: $BASE_DIR/Media/Downloads"
echo "Media folder:     $BASE_DIR/Media"
echo "Run 'media-manager' to see available commands."
