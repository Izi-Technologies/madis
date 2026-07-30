#!/usr/bin/env bash
# Run Madis Mako contract tests with the madis_memory.c bridge linked.
# Plain `mako test tests` fails on proxy_state (extern madis_cmap_*).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MAKO_BIN="${MAKO_BIN:-mako}"
RUNTIME_DIR="${MAKO_RUNTIME:-${HOME}/.local/share/mako/runtime}"
BUILD_DIR="${MADIS_TEST_BUILD:-${TMPDIR:-/tmp}/madis-test-build}"
mkdir -p "$BUILD_DIR"

CC_BIN="${CC:-clang}"
NATIVE_CFLAGS=(-I"$RUNTIME_DIR")
for include_dir in \
  /opt/homebrew/opt/openssl@3/include \
  /usr/local/opt/openssl@3/include; do
  if [[ -d "$include_dir" ]]; then NATIVE_CFLAGS+=("-I$include_dir"); fi
done

"$CC_BIN" -std=c11 -O2 -DNDEBUG -w "${NATIVE_CFLAGS[@]}" \
  -c "$ROOT/madis_memory.c" -o "$BUILD_DIR/madis_memory.o"

export MAKO_LDFLAGS="$BUILD_DIR/madis_memory.o${MAKO_LDFLAGS:+ $MAKO_LDFLAGS}"
PATH_ARG="${1:-tests}"
shift || true
exec "$MAKO_BIN" test "$PATH_ARG" --backend c "$@"
