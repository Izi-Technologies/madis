# September 30 load test: compiler `249a616`

The updated Madis candidate builds and runs on the server, but these results
do **not** establish reliable 1,000-CPS operation or an OpenSIPS performance win.
Both proxies had failed trials, including failures without sampled generator
drops. Madis also showed continuing RSS growth during the three-minute soak.

## Build and workload

- Host: `sip-test.example.invalid`, shared eight-vCPU Linux VM. Production remained
  running at PID 1792355, with the same start time before and after the tests.
- Fresh candidate: `/tmp/madis-load-249a616/madis`, built on the server from
  the current dirty workspace (base Git revision `e36f83b03dbd9d1daed1f933a3e65b06868e4bb0`).
  All 126 uploaded Mako source hashes were verified against the local manifest.
- Compiler/runtime: `249a6168338d290966e9248257cd752cf03bd681`.
  `scripts/build-native.sh` produced uninstrumented GCC `-O3` C-backend output.
  The compiler itself was the source-built executable used in the preceding
  ownership validation; reduced Rust compiler optimization does not change
  the application's GCC release flags.
- Candidate SHA-256: `53b59af281d7ecb33dbbc694a2c31f0c5a999a087057cb043548bfec90d7f811`.
- Comparator: OpenSIPS 4.0.2. Generator: SIPp 3.7.2.
- Existing, unchanged `compare_opensips.py` fixtures: in-memory registration,
  INVITE/200, ACK, 100 ms call, BYE/200. No media or database.
  One UDP worker per proxy. Proxy CPU 2, caller CPU 3, callee CPU 4.
  OpenSIPS uses 256 MiB shared and 16 MiB private memory settings.
- Isolated loopback ports; no production binary replacement or service restart.
  Environment variables were limited to the benchmark settings and dependency
  search path. Each trial used a fresh proxy process. Order alternated by repetition.

A valid trial requires all expected calls successful at **both** endpoints,
zero failed calls and major watchdog events, exact RTT sample count, successful
SIPp exits, a surviving proxy, and zero sampled generator socket drops.
Partial completions are not sustainable throughput. Latencies from failed
trials describe surviving samples and are not competitive success results.

## Repeated 30-second trials

| Offered CPS | Calls per trial | Madis valid | OpenSIPS valid | Madis caller completions, runs 1–3 | OpenSIPS caller completions, runs 1–3 |
|---:|---:|---:|---:|---|---|
| 250 | 7,500 | 0 / 3 | 1 / 3 | 7,456; 7,380; 7,465 | 7,460; 7,500; 7,493 |
| 500 | 15,000 | 2 / 3 | 0 / 3 | 15,000; 14,812; 15,000 | 14,962; 14,871; 14,994 |
| 1,000 | 30,000 | 0 / 3 | 0 / 3 | 28,444; 28,444; 28,327 | 29,981; 28,203; 29,602 |

The two valid Madis 500-CPS trials had p50 INVITE RTT of 4 ms, p95 of 51 and
59 ms, and p99 of 134 and 169.001 ms. The valid OpenSIPS 250-CPS trial had
p50/p95/p99 of 2/42/97.001 ms. These are different rates and are not a
head-to-head latency ratio.

Both initial five-second, 250-CPS smoke trials completed all 1,250 calls with
no failures or retransmissions. Across the complete 22-trial suite, only five
trials met the validity criteria (the two smokes plus three sustained trials).
All six 1,000-CPS trials had sampled generator drops. Some lower-rate failures
had no sampled generator drops, so generator pressure does not explain every
failure. Failed Madis logs include unexpected BYE responses with status 481;
the logs do not by themselves establish which component caused the failure.

## Three-minute soak at 250 CPS

| Proxy | Expected | Caller successful / failed | Callee successful / failed | Generator drops | Valid |
|---|---:|---:|---:|---:|---|
| Madis | 45,000 | 44,926 / 74 | 44,952 / 48 | 76 | No |
| OpenSIPS | 45,000 | 44,974 / 26 | 44,895 / 92 | 242 | No |

Madis root-process RSS samples grew throughout the offered-load interval:

| Approximate elapsed seconds | RSS MiB |
|---:|---:|
| 1 | 28.5 |
| 30 | 119.3 |
| 60 | 162.1 |
| 120 | 242.7 |
| 180 | 322.5 |

Peak sampled RSS including drain was 327.8 MiB. This did not demonstrate a
memory plateau. RSS includes retained allocator pages and live state; growth
alone is not proof of an unreachable allocation leak. These samples cover the
root process, not a cross-proxy aggregate-memory comparison. The earlier clean
100-request sanitizer probe used rejected INVITEs and did not validate this
successful-call workload. It therefore cannot establish leak freedom here.

The host had about 14.6 GiB available and no current memory-pressure signal
when checked during the high-rate phase. CPU and socket sampling still show
that these shared-host runs are unsuitable for a publishable capacity claim.

## Evidence and next work

- [All results and RSS samples](../bench/results/opensips-udp-249a616-linux.json).
- [Build/source provenance](../bench/results/opensips-udp-249a616-provenance.json).
- [Exact orchestration script](../bench/results/opensips-udp-249a616-run.py).
- [Raw logs, SIPp statistics, RTT CSVs, configurations, and build log](../bench/results/opensips-udp-249a616-raw.tar.gz).

The server copy remains at `/tmp/madis-load-249a616`. All benchmark processes
were cleaned up. Kluster was unavailable during this work.

Next work is to reproduce the BYE/481 failures with packet-level correlation,
measure retained state and allocations through successful-call expiry and an
idle drain, and repeat the comparison with generators on a dedicated host.
Do not infer that the remaining successful-call memory growth is the compiler
bug previously closed in #76 without a new allocation-level reproducer.
