#!/usr/bin/env bash
set -euo pipefail

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO_BIN="${MAKO_BIN:-$(command -v makori 2>/dev/null || echo mako)}"
bash "$ROOT/scripts/check-makori-version.sh" "$MAKO_BIN"
cd "$ROOT"

# LeakSanitizer is supported on Linux, but not on macOS. Keep leak checking
# limited to the allocation/ownership fixture, which owns all its resources.
LEAKS=0
if [[ "$(uname -s)" == Linux ]]; then LEAKS=1; fi
for suite in tests/compiler_ownership_test.mko tests/ownership_stress_test.mko tests/stream_ownership_test.mko tests/parser_ownership_test.mko tests/forwarding_ownership_test.mko; do
  ASAN_OPTIONS="detect_leaks=$LEAKS:halt_on_error=1" \
  UBSAN_OPTIONS=halt_on_error=1 \
    "$MAKO_BIN" test "$suite" --backend c --sanitize address,undefined
done

# These contract suites use process-lifetime resources. The scan differential
# suites include frozen pre-optimization oracles with known temporary leaks;
# production validator ownership is independently required to pass LSan above.
for suite in tests/stream_transport_test.mko tests/hep_test.mko tests/maf_contract_test.mko tests/parser_scan_test.mko tests/forwarding_range_test.mko; do
  ASAN_OPTIONS=detect_leaks=0:halt_on_error=1 \
  UBSAN_OPTIONS=halt_on_error=1 \
    "$MAKO_BIN" test "$suite" --backend c --sanitize address,undefined
done
