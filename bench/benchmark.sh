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
TCP_MAX_CONNECTIONS=${SIP_TCP_MAX_CONNECTIONS:-65536}
CALL_STATE_CAPACITY=${SIP_CALL_STATE_CAPACITY:-262144}
RATE=${RATE:-100}
CALLS=${CALLS:-1000}
CONCURRENCY=${CONCURRENCY:-200}
STATS=${STATS:-$ROOT/bench/sipp_stat.csv}
METRICS=${METRICS:-${STATS}.metrics}
STATE_METRICS=${STATE_METRICS:-${STATS}.state}
SAMPLE_INTERVAL_MS=${BENCH_SAMPLE_INTERVAL_MS:-250}
SAMPLE_STATE=${BENCH_SAMPLE_STATE:-0}
STATE_INTERVAL_MS=${BENCH_STATE_INTERVAL_MS:-5000}
STATE_DURING_LOAD=${BENCH_STATE_DURING_LOAD:-0}
KEEP_ARTIFACTS=${KEEP_ARTIFACTS:-0}
USER_RATE_LIMIT=${SIP_USER_RATE_LIMIT:-1000000}
ALLOW_PRIVATE_TARGETS=${SIP_ALLOW_PRIVATE_TARGETS:-1}
BENCH_BUILD=${BENCH_BUILD:-1}
POST_RUN_SLEEP=${BENCH_POST_RUN_SLEEP:-0}
ADMIN_TOKEN=${SIP_ADMIN_TOKEN:-bench-admin-token-0000000000000000}

TMPDIR=$(mktemp -d /tmp/mako-sip-bench.XXXXXX)
PROXY_PID=""
UAS_PID=""
METRICS_PID=""

sample_process() {
    pid="$1"
    output="$2"
    interval_ms="$3"
    admin_port="$4"
    state_output="$5"
    sample_state="$6"
    admin_token="$7"
    state_interval_ms="$8"
    python3 - "$pid" "$output" "$interval_ms" "$admin_port" "$state_output" "$sample_state" "$admin_token" "$state_interval_ms" <<'PY'
import json
import os
import signal
import sys
import time
import urllib.error
import urllib.request

pid = int(sys.argv[1])
output = sys.argv[2]
interval = int(sys.argv[3]) / 1000.0
admin_port = int(sys.argv[4])
state_output = sys.argv[5]
sample_state = sys.argv[6] == "1"
admin_token = sys.argv[7]
state_interval_ms = int(sys.argv[8])
running = True

def stop(_signum, _frame):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)

def read_status(path):
    rss_kb = 0
    vsz_kb = 0
    try:
        with open(path, "r", encoding="utf-8") as handle:
            for line in handle:
                if line.startswith("VmRSS:"):
                    rss_kb = int(line.split()[1])
                elif line.startswith("VmSize:"):
                    vsz_kb = int(line.split()[1])
    except OSError:
        pass
    return rss_kb, vsz_kb

def read_cpu_ticks(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            stat = handle.read()
        tail = stat.rsplit(") ", 1)[1].split()
        return int(tail[11]), int(tail[12])
    except (IndexError, OSError, ValueError):
        return 0, 0

def fetch_state():
    request = urllib.request.Request(
        f"http://127.0.0.1:{admin_port}/state",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=0.2) as response:
            return json.loads(response.read().decode("utf-8"))
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return {}

with open(output, "w", encoding="utf-8") as handle:
    handle.write("ts_ms,rss_kb,vsz_kb,fd_count,utime_ticks,stime_ticks\n")
    state_handle = None
    if sample_state:
        state_handle = open(state_output, "a", encoding="utf-8")
    status_path = f"/proc/{pid}/status"
    stat_path = f"/proc/{pid}/stat"
    fd_path = f"/proc/{pid}/fd"
    next_state_ms = 0
    try:
        while running and os.path.exists(status_path):
            ts_ms = int(time.time() * 1000)
            rss_kb, vsz_kb = read_status(status_path)
            try:
                fd_count = len(os.listdir(fd_path))
            except OSError:
                fd_count = 0
            utime, stime = read_cpu_ticks(stat_path)
            handle.write(f"{ts_ms},{rss_kb},{vsz_kb},{fd_count},{utime},{stime}\n")
            handle.flush()
            if state_handle is not None and ts_ms >= next_state_ms:
                state = fetch_state()
                families = state.get("cache_families", {})
                state_handle.write(
                    "{ts},sample,{registrations},{calls},{cache},{txn},{client},{client_invite},{client_bye},{client_cancel},{client_register},{client_other},{server},{dialog},{fork},{whitelist},{scanner},{ban},{acl},{ipauth}\n".format(
                        ts=ts_ms,
                        registrations=state.get("registrations", 0),
                        calls=state.get("calls", 0),
                        cache=state.get("cache", 0),
                        txn=families.get("txn", 0),
                        client=families.get("client", 0),
                        client_invite=families.get("client_invite", 0),
                        client_bye=families.get("client_bye", 0),
                        client_cancel=families.get("client_cancel", 0),
                        client_register=families.get("client_register", 0),
                        client_other=families.get("client_other", 0),
                        server=families.get("server", 0),
                        dialog=families.get("dialog", 0),
                        fork=families.get("fork", 0),
                        whitelist=families.get("whitelist", 0),
                        scanner=families.get("scanner", 0),
                        ban=families.get("ban", 0),
                        acl=families.get("acl", 0),
                        ipauth=families.get("ipauth", 0),
                    )
                )
                state_handle.flush()
                next_state_ms = ts_ms + state_interval_ms
            time.sleep(interval)
    finally:
        if state_handle is not None:
            state_handle.close()
PY
}

init_state_metrics() {
    if [ "$SAMPLE_STATE" = "1" ]; then
        printf 'ts_ms,phase,registrations,calls,cache,txn,client,client_invite,client_bye,client_cancel,client_register,client_other,server,dialog,fork,whitelist,scanner,ban,acl,ipauth\n' >"$STATE_METRICS"
    fi
}

capture_state_snapshot() {
    phase="$1"
    if [ "$SAMPLE_STATE" != "1" ]; then return 0; fi
    python3 - "$ADMIN_PORT" "$STATE_METRICS" "$ADMIN_TOKEN" "$phase" <<'PY'
import json
import sys
import time
import urllib.error
import urllib.request

admin_port = int(sys.argv[1])
state_output = sys.argv[2]
admin_token = sys.argv[3]
phase = sys.argv[4]
request = urllib.request.Request(
    f"http://127.0.0.1:{admin_port}/state",
    headers={"Authorization": f"Bearer {admin_token}"},
)
try:
    with urllib.request.urlopen(request, timeout=2.0) as response:
        state = json.loads(response.read().decode("utf-8"))
except (OSError, urllib.error.URLError, json.JSONDecodeError):
    state = {}
families = state.get("cache_families", {})
with open(state_output, "a", encoding="utf-8") as handle:
    handle.write(
        "{ts},{phase},{registrations},{calls},{cache},{txn},{client},{client_invite},{client_bye},{client_cancel},{client_register},{client_other},{server},{dialog},{fork},{whitelist},{scanner},{ban},{acl},{ipauth}\n".format(
            ts=int(time.time() * 1000),
            phase=phase,
            registrations=state.get("registrations", 0),
            calls=state.get("calls", 0),
            cache=state.get("cache", 0),
            txn=families.get("txn", 0),
            client=families.get("client", 0),
            client_invite=families.get("client_invite", 0),
            client_bye=families.get("client_bye", 0),
            client_cancel=families.get("client_cancel", 0),
            client_register=families.get("client_register", 0),
            client_other=families.get("client_other", 0),
            server=families.get("server", 0),
            dialog=families.get("dialog", 0),
            fork=families.get("fork", 0),
            whitelist=families.get("whitelist", 0),
            scanner=families.get("scanner", 0),
            ban=families.get("ban", 0),
            acl=families.get("acl", 0),
            ipauth=families.get("ipauth", 0),
        )
    )
PY
}

summarize_metrics() {
    metrics_file="$1"
    if [ ! -s "$metrics_file" ]; then
        echo "metrics_samples=0"
        return
    fi
    python3 - "$metrics_file" <<'PY'
import csv
import sys

rows = []
with open(sys.argv[1], newline="") as handle:
    for row in csv.DictReader(handle):
        try:
            rows.append({key: int(value) for key, value in row.items()})
        except ValueError:
            continue

if not rows:
    print("metrics_samples=0")
    raise SystemExit

first = rows[0]
last = rows[-1]
cpu_ticks = (last["utime_ticks"] + last["stime_ticks"]) - (first["utime_ticks"] + first["stime_ticks"])
duration_ms = max(0, last["ts_ms"] - first["ts_ms"])
print(
    "metrics_samples={samples} rss_peak_kb={rss_peak} rss_last_kb={rss_last} "
    "vsz_peak_kb={vsz_peak} fd_peak={fd_peak} cpu_ticks={cpu_ticks} "
    "sample_duration_ms={duration_ms}".format(
        samples=len(rows),
        rss_peak=max(row["rss_kb"] for row in rows),
        rss_last=last["rss_kb"],
        vsz_peak=max(row["vsz_kb"] for row in rows),
        fd_peak=max(row["fd_count"] for row in rows),
        cpu_ticks=cpu_ticks,
        duration_ms=duration_ms,
    )
)
PY
}

stop_metrics() {
    if [ -n "$METRICS_PID" ]; then
        kill -TERM "$METRICS_PID" 2>/dev/null || true
        wait "$METRICS_PID" 2>/dev/null || true
        METRICS_PID=""
    fi
}

cleanup() {
    stop_metrics
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
    echo "Mako 0.5.0 runtime not found: $RUNTIME" >&2
    exit 2
fi

if [ "$BENCH_BUILD" = "1" ]; then
    echo "Building proxy with runtime: $RUNTIME"
    MAKO_BIN="$MAKO" MAKO_RUNTIME="$RUNTIME" "$ROOT/scripts/build-native.sh" main.mko main
else
    if [ ! -x "$ROOT/main" ]; then
        echo "BENCH_BUILD=0 requires an existing executable: $ROOT/main" >&2
        exit 2
    fi
    echo "Reusing existing proxy binary: $ROOT/main"
fi

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
SIP_TCP_MAX_CONNECTIONS="$TCP_MAX_CONNECTIONS" \
SIP_CALL_STATE_CAPACITY="$CALL_STATE_CAPACITY" \
SIP_USER_RATE_LIMIT="$USER_RATE_LIMIT" \
SIP_ALLOW_PRIVATE_TARGETS="$ALLOW_PRIVATE_TARGETS" \
SIP_ADMIN_TOKEN="$ADMIN_TOKEN" \
SIP_STATE_CACHE_FAMILIES="$SAMPLE_STATE" \
  "$ROOT/main" >"$TMPDIR/proxy.log" 2>&1 &
PROXY_PID=$!
init_state_metrics
sample_process "$PROXY_PID" "$METRICS" "$SAMPLE_INTERVAL_MS" "$ADMIN_PORT" "$STATE_METRICS" "$STATE_DURING_LOAD" "$ADMIN_TOKEN" "$STATE_INTERVAL_MS" &
METRICS_PID=$!

sleep 1
capture_state_snapshot "before_load"

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
capture_state_snapshot "after_load"

if [ "$POST_RUN_SLEEP" != "0" ]; then
    echo "Observing proxy for ${POST_RUN_SLEEP}s after load"
    sleep "$POST_RUN_SLEEP"
fi
capture_state_snapshot "after_observe"

echo
echo "===== SIPp result ====="
tail -80 "$TMPDIR/uac.log"
echo
echo "===== Proxy log tail ====="
tail -30 "$TMPDIR/proxy.log"
echo
echo "===== Resource metrics ====="
stop_metrics
summarize_metrics "$METRICS"
echo
echo "Artifacts: $STATS"
echo "Metrics: $METRICS"
if [ "$SAMPLE_STATE" = "1" ]; then
    echo "State metrics: $STATE_METRICS"
fi
