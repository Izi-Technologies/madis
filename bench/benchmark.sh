#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
MAKO=${MAKO:-mako}
RUNTIME=${BENCH_RUNTIME:-${MAKO_RUNTIME:-/Users/loreste/mako/runtime}}
SIPP=${SIPP:-/opt/homebrew/bin/sipp}

PROXY_PORT=${PROXY_PORT:-15060}
UAS_PORT=${UAS_PORT:-15070}
TLS_PORT=${TLS_PORT:-15061}
WSS_PORT=${WSS_PORT:-18443}
ADMIN_PORT=${ADMIN_PORT:-18080}
WORKERS=${WORKERS:-1}
RATE=${RATE:-100}
CALLS=${CALLS:-1000}
CONCURRENCY=${CONCURRENCY:-200}
STATS=${STATS:-$ROOT/bench/sipp_stat.csv}
KEEP_ARTIFACTS=${KEEP_ARTIFACTS:-0}
USER_RATE_LIMIT=${SIP_USER_RATE_LIMIT:-1000000}

TMPDIR=$(mktemp -d /tmp/mako-sip-bench.XXXXXX)
PROXY_PID=""
UAS_PID=""

cleanup() {
    if [ -n "$UAS_PID" ]; then kill -TERM "$UAS_PID" 2>/dev/null || true; fi
    if [ -n "$PROXY_PID" ]; then kill -TERM "$PROXY_PID" 2>/dev/null || true; fi
    sleep 1
    if [ -n "$UAS_PID" ]; then kill -KILL "$UAS_PID" 2>/dev/null || true; fi
    if [ -n "$PROXY_PID" ]; then kill -KILL "$PROXY_PID" 2>/dev/null || true; fi
    if [ -n "$UAS_PID" ]; then wait "$UAS_PID" 2>/dev/null || true; fi
    if [ -n "$PROXY_PID" ]; then wait "$PROXY_PID" 2>/dev/null || true; fi
    if [ "$KEEP_ARTIFACTS" = "1" ]; then
        echo "Kept benchmark artifacts: $TMPDIR"
    else
        rm -rf "$TMPDIR"
    fi
}
trap cleanup EXIT INT TERM

cd "$ROOT"

if [ ! -x "$SIPP" ]; then
    echo "SIPp not found: $SIPP" >&2
    exit 2
fi

if [ ! -f "$RUNTIME/mako_rt.h" ]; then
    echo "Mako 0.4.16 runtime not found: $RUNTIME" >&2
    exit 2
fi

echo "Building proxy with runtime: $RUNTIME"
MAKO_BIN="$MAKO" MAKO_RUNTIME="$RUNTIME" "$ROOT/scripts/build-native.sh" main.mko main

echo "Starting UAS on UDP :$UAS_PORT"
"$SIPP" -sn uas -i 127.0.0.1 -p "$UAS_PORT" -nostdin -skip_rlimit \
  -trace_msg -trace_err -trace_screen >"$TMPDIR/uas.log" 2>&1 &
UAS_PID=$!

echo "Starting proxy on UDP :$PROXY_PORT with $WORKERS worker(s)"
SIP_UDP_PORT="$PROXY_PORT" \
SIP_TLS_PORT="$TLS_PORT" \
SIP_WSS_PORT="$WSS_PORT" \
SIP_ADMIN_PORT="$ADMIN_PORT" \
SIP_UDP_WORKERS="$WORKERS" \
SIP_TCP_WORKERS=1 \
SIP_USER_RATE_LIMIT="$USER_RATE_LIMIT" \
  "$ROOT/main" >"$TMPDIR/proxy.log" 2>&1 &
PROXY_PID=$!

sleep 1

echo "Registering benchmark UAS through proxy"
printf '%s\n%s\n' SEQUENTIAL "$UAS_PORT" >"$TMPDIR/register.csv"
"$SIPP" "127.0.0.1:$PROXY_PORT" \
  -sf "$ROOT/bench/register.xml" \
  -s bench -i 127.0.0.1 -p 15071 -m 1 -recv_timeout 5000 -timeout 10s \
  -inf "$TMPDIR/register.csv" \
  -nostdin -skip_rlimit \
  -trace_err -trace_msg -nd >"$TMPDIR/register.log" 2>&1

echo "Running: rate=${RATE} cps calls=${CALLS} concurrency=${CONCURRENCY}"
"$SIPP" "127.0.0.1:$PROXY_PORT" \
  -sf "$ROOT/bench/invite.xml" -s bench -i 127.0.0.1 -p 15072 \
  -r "$RATE" -l "$CONCURRENCY" -m "$CALLS" \
  -recv_timeout 5000 -timeout 180s \
  -f 1 -fd 1 -stf "$STATS" -trace_stat -trace_err -trace_screen \
  -nostdin -skip_rlimit >"$TMPDIR/uac.log" 2>&1 || true

echo
echo "===== SIPp result ====="
tail -80 "$TMPDIR/uac.log"
echo
echo "===== Proxy log tail ====="
tail -30 "$TMPDIR/proxy.log"
echo
echo "Artifacts: $STATS"
