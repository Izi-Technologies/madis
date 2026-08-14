#!/usr/bin/env bash
set -euo pipefail

echo "Adding Madis YUM/DNF repository..."

cat > /etc/yum.repos.d/madis.repo <<'EOF'
[madis]
name=Madis SIP Proxy
baseurl=https://packages.izi.tech/rpm
enabled=1
gpgcheck=1
gpgkey=https://packages.izi.tech/gpg.key
EOF

echo ""
echo "Run: sudo dnf install madis"
