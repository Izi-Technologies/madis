#!/usr/bin/env bash
# Install Madis on RHEL/Fedora/Rocky/Alma from GitHub Releases.
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

RPM="madis-${VERSION}-1.x86_64.rpm"
URL="https://github.com/$REPO/releases/download/v${VERSION}/${RPM}"

echo "Installing Madis ${VERSION} from GitHub Releases..."

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

curl -fsSL -o "$TMP/$RPM" "$URL"

if command -v dnf >/dev/null 2>&1; then
    dnf install -y "$TMP/$RPM"
else
    yum install -y "$TMP/$RPM"
fi

echo ""
echo "Madis ${VERSION} installed. Configure /etc/madis/madis.env and run:"
echo "  sudo systemctl enable --now madis"
