#!/usr/bin/env bash
set -euo pipefail

VERSION=$("$1" --version 2>/dev/null || true)
if [[ "$VERSION" =~ makori([0-9]+)\.([0-9]+)\.([0-9]+)([[:space:]]|$) ]]; then
    MAJOR=$((10#${BASH_REMATCH[1]}))
    MINOR=$((10#${BASH_REMATCH[2]}))
    PATCH=$((10#${BASH_REMATCH[3]}))
    if (( MAJOR > 0 || MINOR > 6 || (MINOR == 6 && PATCH >= 38) )); then
        # Both pre-fix and post-fix compilers report 0.6.38. Verify ownership
        # behavior rather than accepting an indistinguishable version string.
        ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
        PROBE_DIR=$(mktemp -d "${TMPDIR:-/tmp}/madis-compiler-probe.XXXXXX")
        trap 'rm -rf "$PROBE_DIR"' EXIT
        cp "$ROOT/tests/compiler_ownership_test.mko" "$PROBE_DIR/ownership_test.mko"
        if ! MAKO_CC="${CC:-cc}" "$1" test "$PROBE_DIR/ownership_test.mko" \
            --backend c --leak-check >"$PROBE_DIR/result.log" 2>&1; then
            cat "$PROBE_DIR/result.log" >&2
            echo "Makori ownership probe failed; use commit c2a2d38212903b981f967c7023c5fe07744e1d71 with its matching runtime." >&2
            exit 1
        fi
        # The upstream leak checker reports leaks without a failing exit code.
        if ! grep -Eq 'leak-check: clean \([1-9][0-9]* allocs, 0 leaked\)' "$PROBE_DIR/result.log" \
            || grep -Eq 'leaked: [1-9][0-9]* allocation' "$PROBE_DIR/result.log"; then
            cat "$PROBE_DIR/result.log" >&2
            echo "Makori lacks the required leak-free string and array ownership behavior (#74–#77)." >&2
            exit 1
        fi
        exit 0
    fi
fi
echo "Makori 0.6.38 or later is required for reference-counted strings and ownership fixes (found: ${VERSION:-unknown})" >&2
exit 1
