#!/usr/bin/env bash

set -e

echo "Installing Media Manager CLI..."

# Install system dependencies if apt is available
if command -v apt-get &> /dev/null; then
    echo "Installing system dependencies (aria2)..."
    sudo apt-get update
    sudo apt-get install -y aria2
else
    echo "Warning: apt-get not found. Please install 'aria2' manually using your package manager."
fi

# We use a virtual environment to avoid polluting the system Python and bypassing externally-managed-environments
echo "Setting up Python virtual environment..."
VENV_DIR="$HOME/.local/share/media_manager/venv"
python3 -m venv "$VENV_DIR"

# Install python dependencies and the app itself inside the venv
echo "Installing pirate-get and media-manager inside venv..."
"$VENV_DIR/bin/pip" install pirate-get
"$VENV_DIR/bin/pip" install -e .

# Create symlinks in user's local bin so they are accessible without the venv path
echo "Adding symlinks to $HOME/.local/bin..."
mkdir -p "$HOME/.local/bin"
ln -sf "$VENV_DIR/bin/media-manager" "$HOME/.local/bin/media-manager"
ln -sf "$VENV_DIR/bin/pirate-get" "$HOME/.local/bin/pirate-get"
ln -sf "$VENV_DIR/bin/aria2p" "$HOME/.local/bin/aria2p"

# Check if ~/.local/bin is in PATH
if [[ ":$PATH:" != *":$HOME/.local/bin:"* ]]; then
    echo ""
    echo "WARNING: ~/.local/bin is not in your PATH."
    echo "Please add the following line to your ~/.bashrc or ~/.zshrc:"
    echo 'export PATH="$HOME/.local/bin:$PATH"'
    echo ""
fi

echo "Installation complete!"
echo "Run 'media-manager' to see available commands."
