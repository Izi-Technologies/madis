#!/usr/bin/env bash
# Install Madis on Debian/Ubuntu from GitHub Releases.
set -euo pipefail

REPO="Izi-Technologies/madis"
VERSION="${1:-latest}"

if [ "$VERSION" = "latest" ]; then
    VERSION=$(curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" | grep '"tag_name"' | sed 's/.*"v\(.*\)".*/\1/')
fi

if [ -z "$VERSION" ]; then
    echo "Could not determine latest version." >&2
    exit 1
fi

DEB="madis_${VERSION}_amd64.deb"
URL="https://github.com/$REPO/releases/download/v${VERSION}/${DEB}"

echo "Installing Madis ${VERSION} from GitHub Releases..."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL -o "$TMP/$DEB" "$URL"
dpkg -i "$TMP/$DEB" || apt-get install -f -y
echo ""
echo "Madis ${VERSION} installed. Configure /etc/madis/madis.env and run:"
echo "  sudo systemctl enable --now madis"
