# SIP CPS/concurrency benchmark

For the reproducible stateful UDP OpenSIPS comparison, use
[`compare_opensips.py`](compare_opensips.py) and read the
[methodology and limitations](../docs/opensips-comparison.md).
The latest [server load-test report](../docs/opensips-249a616-load-test.md)
covers compiler `249a616`, repeated 250/500/1,000-CPS runs, and three-minute soaks.

Set `BENCH_TIMEOUT` longer than `CALLS / RATE` plus dialog drain time for
long runs (for example `BENCH_TIMEOUT=420s RATE=50 CALLS=15000`). The default
is 180 seconds. The harness fails if the proxy exits, SIPp returns an error,
any dialog fails, or the final cumulative statistics do not show every
requested call completed. Logs and metrics are printed before failure.

This is a load harness, not a capacity promise. Read
[`../docs/testing.md`](../docs/testing.md) before comparing Madis with
Kamailio or another proxy.

This harness measures completed INVITE dialogs through the proxy, using SIPp
as both the caller and a registered terminating UAS. It reports successful and
failed calls, response-time buckets, achieved CPS, and the proxy's process
resource usage can be sampled externally.

Run a baseline:

```sh
RATE=100 CALLS=1000 CONCURRENCY=200 WORKERS=1 ./bench/benchmark.sh
```

The harness expects `sipp` unless `SIPP=/path/to/sipp` is set. Build the
proxy with Mako 0.6.38 and its matching runtime first, and keep the UAS, database, route data, CPU
affinity, and message mix identical across candidates.

The scenario holds each dialog for one second. Change that pause in
`bench/invite.xml` when testing a different traffic mix.

Run a saturation sweep:

```sh
for rate in 100 250 500 1000; do
  RATE="$rate" CALLS=5000 CONCURRENCY=1000 WORKERS=1 \
    STATS="/tmp/mako-${rate}.csv" ./bench/benchmark.sh
done
```

Then repeat the same matrix with `WORKERS=2`, `4`, and `8`. The useful score is
the highest rate with zero failed calls and p99 setup latency within the target—not the
highest rate at which the generator starts dropping packets.

For a fair Kamailio comparison, keep the SIPp scenario, host, CPU affinity,
message size, worker count, and database/routing mode identical. Kamailio is
not installed in this checkout; install or point `SIPP`/the proxy command at a
separate candidate before comparing results.

Do not reuse historical CPS or concurrency numbers as release results. Record
the Mako version, source revision, host, scenario, database mode, route data,
worker settings, achieved CPS, failed calls, p95/p99 setup latency, CPU, RSS,
and file-descriptor usage for each run. The repository does not contain a
current Kamailio comparison.

Additional validation commands:

For an offline comparison of stream framing allocations and throughput:

```sh
MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/mako/runtime \
  python3 bench/stream_framing.py --output /tmp/framing.json
```

This compares the frozen RC-aware array result with the production typed result
using the same compiler, runtime, and C optimization flags. Complete messages,
three-fragment messages, and two-message pipelines with incomplete tails are
measured in alternating fresh processes. Timing is uninstrumented; a separate
binary counts generated-code malloc/calloc/realloc calls. Results include raw
samples, source hashes, allocation requests, batch-mean p50/p95 latency, and peak
process RSS. Batch-mean latency is not request tail latency; this has no sockets
or database work and does not establish SIP capacity. CI runs a short checksum
and generated-code smoke check without imposing noisy throughput thresholds.
See [the measured 0.6.38 results](../docs/stream-framing-0.6.38.md).

Transport and interoperability checks:

```sh
python3 bench/transport_matrix.py --binary ./main
python3 bench/wss_outbound_matrix.py --binary ./main
python3 bench/tls_ipv6_matrix.py --binary ./main
python3 bench/fault_matrix.py --binary ./main
python3 bench/abnf_corpus.py --binary ./main
python3 bench/fuzz_sip.py --binary ./main --iterations 1000
sh bench/sanitizer.sh
SOAK_RUNS=5 SOAK_CALLS=1000 SOAK_RATE=750 SOAK_CONCURRENCY=500 SOAK_WORKERS=4 sh bench/soak.sh
python3 bench/perf_matrix.py --binary ./main --out-dir /tmp/madis-perf
```

`tls_ipv6_matrix.py` creates a temporary CA and verifies SNI certificate
selection, hostname rejection, and UDP/TCP/TLS over `::1`. `fault_matrix.py`
drives deterministic loss, delay, duplicate, reorder, retransmission, and
unacknowledged-2xx cases through a real local UAS. These are independent
process checks, but they do not replace independent SIP stack
interoperability; those stacks must be installed and supplied as separate
fixtures.

`wss_outbound_matrix.py` verifies the WebRTC signaling egress path: a
temporary CA signs a `localhost` WSS peer, the proxy registers a
`transport=wss` contact, and an INVITE/180/200/ACK/BYE dialog is checked at a
minimal RFC 6455 upstream over one persistent connection. Production
deployments should set `SIP_UPSTREAM_CA`; insecure WSS is intentionally
opt-in through `SIP_UPSTREAM_TLS_INSECURE=1` for lab use. Persistent idle
associations expire according to `SIP_WSS_IDLE_MS` (default 10 minutes).

`abnf_corpus.py` crosses 24 valid compact/long, quoted/unquoted, IPv4/IPv6,
URI-escaped, and Via-parameter forms, then checks 13 one-rule invalid
mutations receive 4xx responses.

For long-lived TCP connection measurements, use the dependency-free probe:

```sh
SIP_TCP_MAX_CONNECTIONS=100000 \
  python3 bench/tcp_connection_soak.py \
  --port 15060 --connections 10000 --duration 60 --interval 5
```

Run this with increasing connection counts while recording file descriptors,
RSS, CPU, response counts, and failed connections. The requested count is an
input to the experiment; the output is not a capacity guarantee.

For a broader local performance run, `bench/perf_matrix.py` combines UDP CPS,
long-dialog retention, TCP/TLS/WSS stateless OPTIONS load, and TCP connection
retention into one timestamped output directory. It reuses `benchmark.sh` for
INVITE dialogs and `transport_options_load.py` for stream transport load.

## Validator scan microbenchmark

Build `bench/validation_scan.mko` with Mako 0.6.38's C backend and `--release`.
It alternates the pre-scan validator and current validator over 100,000 messages
per round, sharing the current semantic helpers. The reference intentionally
retains old validator ownership behavior. This measures local validation cost,
not SIP call capacity. Recorded timings and the end-to-end comparison are in
[`results/validation-scan-0.6.38-macos.json`](results/validation-scan-0.6.38-macos.json)
and [`docs/opensips-comparison.md`](../docs/opensips-comparison.md).

## Request allocation diagnostic

`proxy_allocation_probe.c` includes a generated `main.c` with its entry point
renamed, then exercises 100 unregistered INVITEs. It requires 404 responses and
keeps its maps as process-lifetime roots. This is a diagnostic, not a clean
ownership gate: it covers only rejected INVITEs with reachable map roots.
With compiler `249a616`, this probe exits cleanly under Linux LSan; the
successful-call load test still shows unresolved RSS growth.
Use a clean environment with no routing/application settings. Generate C with
Mako 0.6.38 and build on Linux, for example:

```sh
MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/runtime \
  bash scripts/build-native.sh main.mko /tmp/madis-probe-source
cc -std=c11 -O1 -g -fno-omit-frame-pointer -DNDEBUG -w \
  -fsanitize=address,undefined -I/path/to/runtime -I/usr/include/postgresql \
  -DMAKO_HAS_OPENSSL -DMAKO_USE_OPENSSL -DMAKO_HAS_LIBPQ \
  -DMADIS_GENERATED_C='"/absolute/path/to/main.c"' \
  bench/proxy_allocation_probe.c -o /tmp/proxy-allocation-probe \
  -pthread -lm -ldl -lresolv -lssl -lcrypto -lpq
env -i ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:fast_unwind_on_malloc=0 \
  UBSAN_OPTIONS=halt_on_error=1 /tmp/proxy-allocation-probe
```

The C harness avoids a 0.6.38 test-codegen error (duplicate actor-state types)
when directly importing the complete request core into a Mako test. Normal
release builds and the focused Mako contract suites compile successfully.
