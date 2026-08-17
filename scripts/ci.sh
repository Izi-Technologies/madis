#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO_BIN="${MAKO_BIN:-mako}"
MAKO_VERSION_TEXT=$("$MAKO_BIN" --version 2>/dev/null || true)
case "$MAKO_VERSION_TEXT" in
  *0.5.*) ;;
  *) echo "Mako 0.5.x is required (found: ${MAKO_VERSION_TEXT:-unknown})" >&2; exit 1 ;;
esac

run_mako() {
  if [[ -n "${MAKO_RUNTIME:-}" ]]; then
    MAKO_RUNTIME="$MAKO_RUNTIME" "$MAKO_BIN" "$@"
  else
    "$MAKO_BIN" "$@"
  fi
}

cd "$ROOT"
run_mako check --no-incremental main.mko
run_mako lint main.mko
run_mako check --no-incremental admin/main.mko
run_mako lint admin/main.mko

BUILD_DIR=$(mktemp -d "${TMPDIR:-/tmp}/madis-ci.XXXXXX")
trap 'rm -rf "$BUILD_DIR"' EXIT

CC_BIN="${CC:-cc}"
RUNTIME_DIR="${MAKO_RUNTIME:-}"
if [[ -z "$RUNTIME_DIR" ]]; then
  for candidate in /usr/local/share/mako/runtime /usr/share/mako/runtime /Users/loreste/mako/runtime; do
    if [[ -d "$candidate" ]]; then RUNTIME_DIR="$candidate"; break; fi
  done
fi
[[ -d "$RUNTIME_DIR" ]] || { echo "Mako runtime directory is required for the native link" >&2; exit 1; }

NATIVE_CFLAGS=(-I"$RUNTIME_DIR")
for include_dir in \
  /usr/include/postgresql \
  /usr/local/include \
  /opt/homebrew/include \
  /opt/homebrew/opt/libpq/include \
  /usr/local/opt/libpq/include \
  /opt/homebrew/opt/openssl@3/include \
  /usr/local/opt/openssl@3/include; do
  if [[ -d "$include_dir" ]]; then NATIVE_CFLAGS+=("-I$include_dir"); fi
done

# Pure Mako — no C bridge needed.
run_mako test tests --backend c

build_native() {
  local source="$1"
  local output="$2"
  MAKO_BIN="$MAKO_BIN" MAKO_RUNTIME="$RUNTIME_DIR" \
    "$ROOT/scripts/build-native.sh" "$source" "$output"
}

build_native main.mko "$BUILD_DIR/madis"
build_native admin/main.mko "$BUILD_DIR/madis-admin"

python3 - <<'PY'
import json
from pathlib import Path
for path in Path("api").glob("*.json"):
    json.loads(path.read_text())
    print(f"validated {path}")
PY

bash -n install.sh
python3 -m py_compile sdk/python/madis_carrier.py
python3 -m py_compile sdk/maf/python/madis_maf.py sdk/maf/tests/test_maf_sdk.py bench/maf_security_matrix.py
python3 -m unittest discover -s sdk/maf/tests -p 'test_*.py'

if command -v node >/dev/null 2>&1; then
  node --check sdk/maf/javascript/madis-maf.mjs
  node sdk/maf/tests/test_maf_sdk.mjs
else
  echo "node not installed; skipped MAF JavaScript syntax check"
fi

if command -v go >/dev/null 2>&1; then
  (cd sdk/maf/go && GO111MODULE=off go test)
else
  echo "go not installed; skipped MAF Go compile check"
fi

python3 -m unittest discover -s lab -p 'test_*.py'
python3 -m unittest discover -s media -p 'test_*.py'

echo "Madis CI checks passed with Mako 0.5.0"
