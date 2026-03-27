#!/usr/bin/env bash

set -e

MEDIA_DIR="$HOME/Media"
USER_NAME=$(whoami)

echo "Adding Samba configuration for Media Manager..."
echo "This will share your $MEDIA_DIR folder to the local network."
echo "You may be prompted for your sudo password."

# Install samba if not present
if ! command -v smbd &> /dev/null; then
    echo "Installing Samba..."
    sudo apt-get update
    sudo apt-get install -y samba
fi

echo "Configuring Samba share [Media]..."

# Backup existing config just in case
sudo cp /etc/samba/smb.conf /etc/samba/smb.conf.bak

# Check if [Media] already exists to avoid duplicates
if grep -q "\\[Media\\]" /etc/samba/smb.conf; then
    echo "A [Media] share already exists in /etc/samba/smb.conf. Skipping..."
else
    # Append the configuration
    sudo tee -a /etc/samba/smb.conf > /dev/null <<EOL

[Media]
    comment = Media Manager Shared Folder
    path = $MEDIA_DIR
    browsable = yes
    read only = no
    guest ok = yes
    create mask = 0644
    directory mask = 0755
    force user = $USER_NAME
EOL
    echo "Share added to smb.conf!"
fi

echo "Restarting Samba services..."
sudo systemctl restart smbd
sudo systemctl restart nmbd

# Get main IP address
IP=$(hostname -I | awk '{print $1}')

echo ""
echo "====================================================="
echo "✅ Samba configuration complete!"
echo "Your media is now accessible on your local network at:"
echo "Windows: \\\\$IP\\Media"
echo "Mac/Linux: smb://$IP/Media"
echo "====================================================="
