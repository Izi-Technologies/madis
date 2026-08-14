#!/usr/bin/env bash
set -euo pipefail

GPG_KEY_URL="https://packages.izi.tech/gpg.key"
REPO_URL="https://packages.izi.tech/apt"

echo "Adding Madis APT repository..."

# Import GPG key
curl -fsSL "$GPG_KEY_URL" | gpg --dearmor -o /usr/share/keyrings/madis-archive-keyring.gpg

# Add repository
cat > /etc/apt/sources.list.d/madis.list <<EOF
deb [signed-by=/usr/share/keyrings/madis-archive-keyring.gpg] $REPO_URL stable main
EOF

apt-get update

echo ""
echo "Run: sudo apt install madis"
