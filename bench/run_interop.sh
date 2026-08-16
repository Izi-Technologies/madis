#!/usr/bin/env bash
# RFC 3261 interoperability test runner for SIPp scenarios.
# Usage: ./run_interop.sh [proxy_ip:proxy_port]
#
# Requires: sipp in PATH.

set -euo pipefail

PROXY="${1:-127.0.0.1:5060}"
PROXY_IP="${PROXY%%:*}"
PROXY_PORT="${PROXY##*:}"

BENCH_DIR="$(cd "$(dirname "$0")" && pwd)"
UAS_PORT=5080
SIPP_TIMEOUT=30   # seconds per scenario
TRANSPORT="-t u1"  # UDP

PASS=0
FAIL=0
RESULTS=()

# UAS scenario files matched to each UAC test
declare -A UAS_SCENARIOS=(
  # timer_retransmit uses its own UAS scenario
  [interop_timer_retransmit]="interop_timer_retransmit.xml"
)

cleanup() {
  # Kill any background SIPp UAS processes we started
  if [[ -n "${UAS_PID:-}" ]]; then
    kill "$UAS_PID" 2>/dev/null || true
    wait "$UAS_PID" 2>/dev/null || true
  fi
  # Remove SIPp screen/log files
  rm -f "${BENCH_DIR}"/*.log "${BENCH_DIR}"/*_screen.txt 2>/dev/null || true
}
trap cleanup EXIT

log() { printf "%-40s %s\n" "$1" "$2"; }

# Start a generic UAS (auto-answer 200) for most tests.
# Individual tests that need a custom UAS start their own.
start_generic_uas() {
  sipp -sn uas -p "$UAS_PORT" -bg -trace_err \
    -error_file "${BENCH_DIR}/uas_generic.log" \
    $TRANSPORT >/dev/null 2>&1 &
  UAS_PID=$!
  sleep 0.5
}

stop_uas() {
  if [[ -n "${UAS_PID:-}" ]]; then
    kill "$UAS_PID" 2>/dev/null || true
    wait "$UAS_PID" 2>/dev/null || true
    UAS_PID=""
  fi
}

run_scenario() {
  local name="$1"
  local xml="${BENCH_DIR}/${name}.xml"
  local custom_uas="${UAS_SCENARIOS[$name]:-}"
  local uas_pid_local=""

  if [[ ! -f "$xml" ]]; then
    log "$name" "SKIP (file not found)"
    return
  fi

  stop_uas

  # Start custom UAS if needed, otherwise generic
  if [[ -n "$custom_uas" && -f "${BENCH_DIR}/${custom_uas}" ]]; then
    sipp -sf "${BENCH_DIR}/${custom_uas}" -p "$UAS_PORT" -bg -trace_err \
      -error_file "${BENCH_DIR}/uas_${name}.log" \
      $TRANSPORT >/dev/null 2>&1 &
    UAS_PID=$!
  else
    start_generic_uas
  fi
  sleep 0.5

  # Run UAC scenario against the proxy
  if sipp "$PROXY_IP" -sf "$xml" \
      -p 0 -rsa "$PROXY_IP:$PROXY_PORT" \
      -m 1 -l 1 \
      -timeout "$SIPP_TIMEOUT" -timeout_error \
      -trace_err -error_file "${BENCH_DIR}/uac_${name}.log" \
      $TRANSPORT >/dev/null 2>&1; then
    log "$name" "PASS"
    PASS=$((PASS + 1))
    RESULTS+=("PASS $name")
  else
    log "$name" "FAIL"
    FAIL=$((FAIL + 1))
    RESULTS+=("FAIL $name")
  fi

  stop_uas
}

# Preflight
if ! command -v sipp >/dev/null 2>&1; then
  echo "ERROR: sipp not found in PATH" >&2
  exit 1
fi

echo "============================================"
echo " RFC 3261 Interop Tests — proxy at $PROXY"
echo "============================================"
echo ""

SCENARIOS=(
  interop_fork_cancel
  interop_non2xx_ack
  interop_cancel_487
  interop_timer_retransmit
  interop_prack
  interop_auth_digest
)

for s in "${SCENARIOS[@]}"; do
  run_scenario "$s"
done

echo ""
echo "============================================"
echo " Results: $PASS passed, $FAIL failed"
echo "============================================"
for r in "${RESULTS[@]}"; do
  echo "  $r"
done

exit "$FAIL"
