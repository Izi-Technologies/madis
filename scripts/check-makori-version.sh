#!/usr/bin/env bash
set -euo pipefail

VERSION=$("$1" --version 2>/dev/null || true)
if [[ "$VERSION" =~ makori([0-9]+)\.([0-9]+)\.([0-9]+)([[:space:]]|$) ]]; then
    MAJOR=$((10#${BASH_REMATCH[1]}))
    MINOR=$((10#${BASH_REMATCH[2]}))
    PATCH=$((10#${BASH_REMATCH[3]}))
    if (( MAJOR > 0 || MINOR > 6 || (MINOR == 6 && PATCH >= 32) )); then
        exit 0
    fi
fi
echo "Makori 0.6.32 or later is required for crew policies, JSON escaping, and ownership fixes (found: ${VERSION:-unknown})" >&2
exit 1
