# SIP CPS/concurrency benchmark

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
proxy with Mako 0.4.16 first, and keep the UAS, database, route data, CPU
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

```sh
python3 bench/transport_matrix.py --binary ./main
python3 bench/wss_outbound_matrix.py --binary ./main
python3 bench/tls_ipv6_matrix.py --binary ./main
python3 bench/fault_matrix.py --binary ./main
python3 bench/abnf_corpus.py --binary ./main
python3 bench/fuzz_sip.py --binary ./main --iterations 1000
sh bench/sanitizer.sh
SOAK_RUNS=5 SOAK_CALLS=1000 SOAK_RATE=750 SOAK_CONCURRENCY=500 SOAK_WORKERS=4 sh bench/soak.sh
```

`tls_ipv6_matrix.py` creates a temporary CA and verifies SNI certificate
selection, hostname rejection, and UDP/TCP/TLS over `::1`. `fault_matrix.py`
drives deterministic loss, delay, duplicate, reorder, retransmission, and
unacknowledged-2xx cases through a real local UAS. These are independent
process checks, but they do not replace PJSIP/Kamailio/OpenSIPS/Asterisk
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
