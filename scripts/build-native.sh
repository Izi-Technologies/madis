#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO_BIN="${MAKO_BIN:-${MAKO:-mako}}"
SOURCE="${1:-main.mko}"
OUTPUT="${2:-main}"
CC_BIN="${CC:-cc}"

VERSION=$($MAKO_BIN --version 2>/dev/null || true)
case "$VERSION" in
  *0.5.0*) ;;
  *) echo "Mako 0.5.0 is required (found: ${VERSION:-unknown})" >&2; exit 1 ;;
esac

RUNTIME_DIR="${MAKO_RUNTIME_PATH:-${MAKO_RUNTIME:-}}"
if [[ -z "$RUNTIME_DIR" ]]; then
  for candidate in \
    /usr/local/share/mako/runtime \
    /usr/local/lib/mako/runtime \
    /usr/share/mako/runtime \
    /Users/loreste/mako/runtime \
    /Users/loreste/.local/share/mako/runtime; do
    if [[ -d "$candidate" ]]; then RUNTIME_DIR="$candidate"; break; fi
  done
fi
[[ -d "$RUNTIME_DIR" ]] || { echo "Mako runtime directory not found" >&2; exit 1; }

GENERATED="${SOURCE%.mko}.c"
BUILD_TMP=$(mktemp -d "${TMPDIR:-/tmp}/madis-native.XXXXXX")
trap 'rm -rf "$BUILD_TMP"' EXIT
rm -f "$GENERATED"

BUILD_LOG="$BUILD_TMP/mako-build.log"
if ! MAKO_RUNTIME="$RUNTIME_DIR" "$MAKO_BIN" build --emit-c --release --strip --no-incremental \
  "$SOURCE" -o "$BUILD_TMP/mako-ignored" >"$BUILD_LOG" 2>&1; then
  [[ -s "$GENERATED" ]] || { cat "$BUILD_LOG" >&2; exit 1; }
fi

NATIVE_CFLAGS=(-I"$RUNTIME_DIR")
NATIVE_LDFLAGS=(-pthread -lm -ldl -lresolv -lssl -lcrypto -lpq)
for include_dir in \
  /usr/include/postgresql /usr/local/include /opt/homebrew/include \
  /opt/homebrew/opt/libpq/include /usr/local/opt/libpq/include \
  /opt/homebrew/opt/openssl@3/include /usr/local/opt/openssl@3/include; do
  if [[ -d "$include_dir" ]]; then NATIVE_CFLAGS+=("-I$include_dir"); fi
done
for library_dir in \
  /opt/homebrew/lib /usr/local/lib /opt/homebrew/opt/libpq/lib \
  /usr/local/opt/libpq/lib /opt/homebrew/opt/openssl@3/lib \
  /usr/local/opt/openssl@3/lib; do
  if [[ -d "$library_dir" ]]; then NATIVE_LDFLAGS+=("-L$library_dir"); fi
done

EXTRA_CFLAGS="${MADIS_CFLAGS:-}"
EXTRA_LDFLAGS="${MADIS_LDFLAGS:-}"
if [[ -n "${MADIS_SANITIZE:-}" ]]; then
  EXTRA_CFLAGS="$EXTRA_CFLAGS -fsanitize=${MADIS_SANITIZE}"
  EXTRA_LDFLAGS="$EXTRA_LDFLAGS -fsanitize=${MADIS_SANITIZE}"
fi

# These values are intentionally space-separated flags, matching Mako's own
# MAKO_CFLAGS/MAKO_LDFLAGS convention.
EXTRA_CFLAGS_ARGS=()
EXTRA_LDFLAGS_ARGS=()
if [[ -n "$EXTRA_CFLAGS" ]]; then read -r -a EXTRA_CFLAGS_ARGS <<< "$EXTRA_CFLAGS"; fi
if [[ -n "$EXTRA_LDFLAGS" ]]; then read -r -a EXTRA_LDFLAGS_ARGS <<< "$EXTRA_LDFLAGS"; fi
CC_ARGS=(-std=c11 -O3 -DNDEBUG -w "${NATIVE_CFLAGS[@]}"
  -DMAKO_HAS_OPENSSL -DMAKO_USE_OPENSSL -DMAKO_HAS_LIBPQ)
LD_ARGS=("${NATIVE_LDFLAGS[@]}")
if [[ -n "$EXTRA_CFLAGS" ]]; then CC_ARGS+=("${EXTRA_CFLAGS_ARGS[@]}"); fi
if [[ -n "$EXTRA_LDFLAGS" ]]; then LD_ARGS+=("${EXTRA_LDFLAGS_ARGS[@]}"); fi
"$CC_BIN" "${CC_ARGS[@]}" "$GENERATED" "$ROOT/madis_memory.c" -o "$OUTPUT" "${LD_ARGS[@]}"

echo "Built $OUTPUT with Mako 0.5.0"
