#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
MAKO=${MAKO:-mako}
RUNTIME=${MAKO_RUNTIME_PATH:-${MAKO_RUNTIME:-/Users/loreste/mako/runtime}}
cd "$ROOT"

MAKO_RUNTIME="$RUNTIME" "$MAKO" check --no-incremental main.mko
MAKO_RUNTIME="$RUNTIME" "$MAKO" lint main.mko
BRIDGE_TMP=$(mktemp "${TMPDIR:-/tmp}/madis-rfc-bridge.XXXXXX.o")
trap 'rm -f "$BRIDGE_TMP"' EXIT HUP INT TERM
cc -std=c11 -O2 -DNDEBUG -w -I"$RUNTIME" -c madis_memory.c -o "$BRIDGE_TMP"
MAKO_RUNTIME="$RUNTIME" MAKO_LDFLAGS="$BRIDGE_TMP ${MAKO_LDFLAGS:-}" "$MAKO" test tests
MAKO_BIN="$MAKO" MAKO_RUNTIME="$RUNTIME" "$ROOT/scripts/build-native.sh" main.mko main

python3 bench/transport_matrix.py --binary ./main --base-port 18560
python3 bench/wss_outbound_matrix.py --binary ./main --base-port 19460
python3 bench/tls_ipv6_matrix.py --binary ./main --base-port 18760
python3 bench/fault_matrix.py --binary ./main --base-port 18960
python3 bench/abnf_corpus.py --binary ./main --base-port 19260
python3 bench/auth_matrix.py
python3 bench/fuzz_sip.py --binary ./main --iterations "${FUZZ_ITERATIONS:-1000}" --base-port 18660

if [ "${RFC_FULL:-0}" = "1" ]; then
    sh bench/sanitizer.sh
    sh bench/soak.sh
fi

echo "RFC gate: passed"
