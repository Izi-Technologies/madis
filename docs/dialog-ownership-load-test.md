# Successful-dialog ownership and BYE regression — 2026-10-01

The server candidate fixes a reproducible pending-BYE retransmission race and the
temporary leaks observed in the successful-dialog diagnostic. This is an isolated
build and test; the production service was not replaced or restarted.

## Candidate and changes

- Mako compiler/runtime: `249a6168338d290966e9248257cd752cf03bd681` (0.6.38).
- Candidate: `/tmp/madis-dialog-fix/madis` on `sip-test.example.invalid`.
- Binary SHA-256: `6fb3b7c8d8b5ba43edf4ea118d73e1c88301053182ae8aab46dc29c893c63254`.
- Source: the current working-tree snapshot, including existing user changes.
  [Provenance and source hashes](../bench/results/opensips-udp-dialog-fix-provenance.json)
  record the base commit and exact root Mako files. A checksum-based rsync dry run
  confirmed that local and server source contents match.

An ordinary forwarded BYE now publishes a bounded pending server-transaction entry
before dialog teardown. An identical BYE arriving before the downstream response
is absorbed; the client transaction handles retries. The final response replaces
the pending entry and can be replayed. A new BYE transaction still receives 481
when the dialog is gone, and pending entries expire.

`cache_owned.mko` provides explicit owners for integer-map values and selected
temporary-key/value operations. Atomic increments still use `cmap_incr`. Integer
reads return the supplied fallback for invalid text. Production call sites use
the adapters; upstream reproducer code deliberately retains the leaking helpers.
IMS lifecycle fields, NAT registration slices, log timestamps, REGISTER reply
arguments, and transaction timer reads also now have explicit owners.

The upstream runtime and compiler findings are recorded in
[Mako issue #77](https://github.com/loreste/mako/issues/77), with a standalone C
reproducer and sanitizer stacks. This does not reopen the earlier scenarios
resolved by issue #76.

## Correctness and allocation checks

- [All 56 functional test files passed](../bench/results/dialog-functional-tests-249a616.txt).
- [Linux ownership gate passed](../bench/results/dialog-ownership-249a616-linux.txt),
  followed by the [expanded logging/IMS/NAT ownership test](../bench/results/dialog-stream-ownership-249a616-linux.txt).
- The UDP fault matrix passed loss/retransmit, unacknowledged 2xx,
  reordered/duplicate response, and delayed-response scenarios.
- The deterministic BYE regression changed from
  [premature 481](../bench/results/bye-retransmission-before.json) to
  [pending absorption, final 200, cached 200, distinct-transaction 481](../bench/results/bye-retransmission-fixed.json).
- The standalone integer CMap reproducer leaked
  [15,780 bytes in 2,000 allocations](../bench/results/cmap-integer-249a616-linux.txt)
  over 1,000 set/get iterations.
- The initial successful-call probe leaked
  [111,879 bytes in 6,010 allocations](../bench/results/dialog-allocations-249a616-linux.txt).
  After message-path fixes, extending it to run server/client transaction ticks
  exposed [additional timer-path leaks](../bench/results/dialog-allocations-ticks-before-249a616-linux.txt).
  The final expanded probe completed 100 successful dialogs with
  [no ASan, UBSan, or LSan findings](../bench/results/dialog-allocations-owned-249a616-linux.txt).

The probe keeps its process-lifetime maps reachable so LSan diagnoses lost
temporaries rather than intentionally retained transaction state. It exercises
REGISTER, INVITE/200, ACK, BYE/200 and timer ticks with application and database
integration disabled. It does not prove every transport or optional integration
is leak-free. Its disabled database initialization emits `pg_connect: bad url`;
the probe checks SIP outcomes explicitly and exits successfully.

To rerun on Linux after generating `main.c` with `scripts/build-native.sh`:

```sh
gcc -std=c11 -O0 -g -fno-omit-frame-pointer -DNDEBUG -w \
  -fsanitize=address,undefined -I"$MAKO_RUNTIME" -I/usr/include/postgresql \
  -DMAKO_HAS_OPENSSL -DMAKO_USE_OPENSSL -DMAKO_HAS_LIBPQ \
  -DMADIS_GENERATED_C='"../main.c"' bench/dialog_allocation_probe.c \
  -o /tmp/madis-dialog-probe -pthread -lm -ldl -lresolv -lssl -lcrypto -lpq
env -i PATH=/usr/bin:/bin \
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1:fast_unwind_on_malloc=0 \
  UBSAN_OPTIONS=halt_on_error=1 /tmp/madis-dialog-probe 100
```

The final diagnostic uses GCC `-O0`; the server load candidate uses the native
build script's optimized release settings. Earlier diagnostic iterations used
`-O1`. Tests use the same pinned Mako runtime.

## Load-test method

The comparison uses OpenSIPS 4.0.2, SIPp 3.7.2, one UDP worker, loopback transport,
in-memory registration, and a 100 ms call hold. Proxy, caller, and callee are pinned
to CPUs 2, 3, and 4 respectively. This is a shared production host, not an isolated
capacity lab. The binaries and test ports are separate from production.

Both proxies receive the same corrected scenario. The callee requires an ACK,
then accepts duplicate ACKs while waiting for BYE using SIPp's documented
[optional receive and branch behavior](https://sipp.readthedocs.io/en/latest/scenarios/ownscenarios.html).
The initial batch was stopped after its older fixture aborted calls on duplicate
ACKs. That batch is diagnostic evidence, not part of the corrected comparison.
The changed fixture also means the earlier 249a616 report is not a strictly
matched before/after performance comparison.

There are three 30-second repeats at each of 250 and 500 CPS, alternating proxy
order, plus a 250 CPS / 180-second soak and 90 seconds of idle observation for
each proxy. A valid trial requires all expected calls at both endpoints, clean
SIPp exits, no failed calls or major watchdog events, the exact RTT sample count,
zero sampled generator socket drops, and a live proxy through the idle period.
Retransmissions alone do not invalidate a trial. Latency is SIPp's measured
INVITE response time, not an independent one-way network measurement.

RSS samples track the root proxy process. OpenSIPS forks processes, so its root
RSS must not be treated as total OpenSIPS memory or compared directly with the
threaded Madis process.

## Corrected comparison results

Both 5-second smoke tests completed all 1,250 calls. The repeated trials were:

| Offered load | Madis valid trials | OpenSIPS valid trials | Madis p99 in valid trials | OpenSIPS p99 in valid trials |
|---|---:|---:|---:|---:|
| 250 CPS, 30 seconds | 2/3 | 1/3 | 75–151 ms | 361 ms |
| 500 CPS, 30 seconds | 1/3 | 3/3 | 25 ms | 47–193 ms |

These latency ranges exclude invalid trials. A single valid Madis 500 CPS trial
with lower latency does not establish a performance advantage over three valid
OpenSIPS trials. One other Madis 500 CPS repeat completed all 15,000 calls at both
endpoints but had 112 sampled caller-generator drops and was correctly invalidated.

Neither 250 CPS / 180-second soak passed:

| Proxy | Caller successful / failed | Callee successful / failed / unfinished | Sampled generator drops |
|---|---:|---:|---:|
| Madis | 44,889 / 111 | 44,845 / 69 / 86 | 147 |
| OpenSIPS | 44,915 / 85 | 44,926 / 62 / 12 | 85 |

Both proxy processes survived traffic, drain, and the additional 90-second idle
observation. Unfinished callee calls were still active when SIPp's time budget
ended. These runs cannot establish a drop-free capacity limit for either proxy.

Madis RSS, sampled relative to harness start:

| Approximate elapsed time | RSS |
|---|---:|
| 1 second | 29.0 MiB |
| 30 seconds | 93.5 MiB |
| 60 seconds | 100.5 MiB |
| 120 seconds | 108.7 MiB |
| 180 seconds | 117.3 MiB |
| 210–289 seconds, including idle | 117.7 MiB |

The [earlier candidate](opensips-249a616-load-test.md) was approximately
322.5 MiB at 180 seconds. The new result is substantially lower, but RSS still
rose during traffic and did not return to startup levels during idle. Reachable
state and allocator retention are possible contributors; this trace alone cannot
prove or disprove additional leaks. The fixture changed and both soaks had
failures, so this is not a strict matched memory-efficiency comparison.

The controlled pending-BYE race is fixed, but the first 500 CPS Madis trial still
contains BYE/481 failures. The load traces therefore do not support claiming all
BYE failures are resolved. Follow-up should capture failing transactions end to
end and distinguish response loss, dialog teardown, and response-cache eviction.
The response cache has 16,384 slots; at two new cached transactions per call,
500 CPS can wrap that ring in about 16.4 seconds, shorter than its 64-second
nominal response TTL. That is a concrete diagnostic target, not a proven cause
of the observed failures. Additional sanitizer coverage should include repeated
requests, timeout paths, and background worker housekeeping.

Madis has not demonstrated an OpenSIPS performance or reliability lead. The
reproducible fixes are useful, but the remaining failures block a general
production-performance claim.

## Retained evidence

- [All 16 corrected results, including RSS samples](../bench/results/opensips-udp-dialog-fix-linux.json)
- [Repeat/soak driver](../bench/results/opensips-udp-dialog-fix-run.py)
- [Raw logs, scenario/source snapshot, generated C, and regression captures](../bench/results/opensips-udp-dialog-fix-raw.tar.gz)

The raw archive contains all 16 corrected `result.json` files and preserves the
aborted initial batch separately. Its SHA-256 is
`3c218f0dd84070882995c15f615749245b715b1d666184f068986b68c658c507`.
All corrected trials used identical fixture hashes and the Madis binary hash
recorded above. Test listeners were gone after completion. Production PID
1824330 retained its original start time throughout this work.

Kluster tools were unavailable in this session, so no Kluster review was run.
