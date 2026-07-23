#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO=${MAKO:-/Users/loreste/mako/target/release/mako}
RUNTIME=${MAKO_RUNTIME_PATH:-/Users/loreste/mako/runtime}
TMP=$(mktemp -d "${TMPDIR:-/tmp}/mako-sip-sanitize.XXXXXX")
trap 'rm -rf "$TMP"' EXIT HUP INT TERM

echo "Building ASan/UBSan proxy"
MAKO_RUNTIME="$RUNTIME" "$MAKO" build --release --sanitize address,undefined --no-incremental main.mko -o "$TMP/main"

echo "Running sanitized transport matrix"
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1} \
python3 "$ROOT/bench/transport_matrix.py" --binary "$TMP/main" --base-port 18760

echo "Running sanitized trusted TLS/IPv6 matrix"
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1} \
python3 "$ROOT/bench/tls_ipv6_matrix.py" --binary "$TMP/main" --base-port 18960

echo "Running sanitized UDP fault matrix"
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1} \
FAULT_TIMING_SCALE=2 \
python3 "$ROOT/bench/fault_matrix.py" --binary "$TMP/main" --base-port 19160

echo "Running sanitized ingress fuzz"
ASAN_OPTIONS=${ASAN_OPTIONS:-detect_leaks=0} \
UBSAN_OPTIONS=${UBSAN_OPTIONS:-halt_on_error=1} \
python3 "$ROOT/bench/fuzz_sip.py" --binary "$TMP/main" --iterations "${FUZZ_ITERATIONS:-500}" --base-port 18860
