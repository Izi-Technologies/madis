#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO_BIN="${MAKO_BIN:-$(command -v makori 2>/dev/null || echo mako)}"
cd "$ROOT"

# LeakSanitizer is supported on Linux, but not on macOS. Keep leak checking
# limited to the allocation/ownership fixture, which owns all its resources.
LEAKS=0
if [[ "$(uname -s)" == Linux ]]; then LEAKS=1; fi
ASAN_OPTIONS="detect_leaks=$LEAKS:halt_on_error=1" \
UBSAN_OPTIONS=halt_on_error=1 \
  "$MAKO_BIN" test tests/ownership_stress_test.mko --backend c --sanitize address,undefined

# These existing contract suites also use process-lifetime runtime resources.
for suite in tests/stream_transport_test.mko tests/hep_test.mko tests/maf_contract_test.mko; do
  ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
  UBSAN_OPTIONS=halt_on_error=1 \
    "$MAKO_BIN" test "$suite" --backend c --sanitize address,undefined
done
