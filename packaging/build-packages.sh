#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DIST="$SCRIPT_DIR/dist"
VERSION=$(cat "$ROOT/VERSION")
BINARY="${1:?Usage: $0 <path-to-madis-binary>}"

[ -x "$BINARY" ] || { echo "Binary not found or not executable: $BINARY" >&2; exit 1; }

mkdir -p "$DIST"

# ── .deb ────────────────────────────────────────────────────────────────────
build_deb() {
    local STAGING="$SCRIPT_DIR/.deb-staging"
    rm -rf "$STAGING"
    cp -a "$SCRIPT_DIR/deb" "$STAGING"

    # Patch version into control file
    sed -i "s/^Version:.*/Version: ${VERSION}/" "$STAGING/DEBIAN/control"

    # Place binary
    cp "$BINARY" "$STAGING/usr/local/bin/madis"
    chmod 755 "$STAGING/usr/local/bin/madis"
    rm -f "$STAGING/usr/local/bin/.gitkeep"

    # Fix ownership (fakeroot handles this in CI; best-effort locally)
    if command -v fakeroot >/dev/null 2>&1; then
        fakeroot dpkg-deb --build "$STAGING" "$DIST/madis_${VERSION}_amd64.deb"
    else
        dpkg-deb --build "$STAGING" "$DIST/madis_${VERSION}_amd64.deb"
    fi

    rm -rf "$STAGING"
    echo "Built $DIST/madis_${VERSION}_amd64.deb"
}

# ── .rpm ────────────────────────────────────────────────────────────────────
build_rpm() {
    local RPMBUILD="$SCRIPT_DIR/.rpmbuild"
    rm -rf "$RPMBUILD"
    mkdir -p "$RPMBUILD"/{SOURCES,SPECS,BUILD,RPMS,SRPMS}

    # Place sources
    cp "$BINARY" "$RPMBUILD/SOURCES/madis"
    cp "$SCRIPT_DIR/deb/lib/systemd/system/madis.service" "$RPMBUILD/SOURCES/"
    cp "$SCRIPT_DIR/deb/lib/systemd/system/madis-admin.service" "$RPMBUILD/SOURCES/"
    cp "$SCRIPT_DIR/deb/etc/madis/madis.env.example" "$RPMBUILD/SOURCES/"

    # Patch version into spec
    sed "s/^Version:.*/Version:        ${VERSION}/" \
        "$SCRIPT_DIR/rpm/madis.spec" > "$RPMBUILD/SPECS/madis.spec"

    rpmbuild --define "_topdir $RPMBUILD" \
        -bb "$RPMBUILD/SPECS/madis.spec"

    find "$RPMBUILD/RPMS" -name '*.rpm' -exec cp {} "$DIST/" \;
    rm -rf "$RPMBUILD"
    echo "Built RPM in $DIST/"
}

echo "Building packages for madis ${VERSION}..."

if command -v dpkg-deb >/dev/null 2>&1; then
    build_deb
else
    echo "dpkg-deb not found, skipping .deb build"
fi

if command -v rpmbuild >/dev/null 2>&1; then
    build_rpm
else
    echo "rpmbuild not found, skipping .rpm build"
fi

echo "Done. Packages in $DIST/"
ls -lh "$DIST/"
