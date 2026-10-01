# Stream framing with Makori 0.6.38

## Implementation

`stream_next_msg` returns `StreamFrame { message, remainder }` by value. It no
longer allocates a two-element array or retains a remainder before knowing
whether one exists. Complete single-message buffers share RC string storage;
split messages retain independent ownership. TCP, TLS, and WSS consumers use
named fields. Generated C inspection confirms no string-array allocation in
the framing function.

IMS flow renewal has a pure `ims_flow_refresh_value` helper used by the actual
cache update. It preserves identity/routing fields and never shortens expiry.
The bounded leak fixture can exercise that production helper without allocating
the concurrent cache, which intentionally has process lifetime.

The first Linux leak run found 190,887 bytes in 2,000 allocations in the fixture's
direct `flow = ims_flow_refresh_value(flow, ...)` loop. On the pinned compiler,
an explicit intermediate (`let renewed = ...; flow = renewed`) releases the old
owner correctly. Three worker buffer-append sites use the same precaution. No
leak suppressions or disabled Linux leak checks were introduced.

## Method

The comparison uses the previous RC-aware array framing implementation frozen
in `bench/stream_framing.mko`, and the production typed result, both compiled
with the published 0.6.38 compiler/runtime pair and `-O3 -DNDEBUG`.

The fixture is an INVITE with an SDP body. Scenarios cover a complete message,
three receive fragments, and two pipelined messages plus an incomplete tail.
Each timing sample processes 1,000 iterations, with pipelines normalized to
2,000 complete messages. Checksums must match for both implementations. Each
process warms up first, and baseline/candidate execution order alternates.

Timing and RSS come from an uninstrumented binary. A separate binary counts
malloc/calloc/realloc calls and requested bytes made by generated code during
the batches, including small per-batch fixture setup costs. These are allocation
requests, not live bytes or allocations inside libc. RSS is the process high-water
mark. Latency percentiles are distributions of **batch means**, not per-request
tail latency. Neither benchmark includes network I/O or database work.

Linux x86_64 used Ubuntu 24.04, GCC 13.3, seven fresh processes per variant/scenario,
and 200 batches per process. macOS arm64 used Apple Clang 17, five processes and
100 batches. These are shared hosts, so timing is descriptive rather than a CI
performance threshold. An initial experiment with allocation counters enabled
during timing produced mixed/regressive results; those instrumented timings are
not used in the following comparison.

## Results

Median throughput, array baseline → typed result:

| Scenario | Linux messages/s | Change | macOS messages/s | Change |
| --- | ---: | ---: | ---: | ---: |
| Complete | 1,098,505 → 1,146,293 | +4.4% | 1,917,251 → 1,891,253 | −1.4% |
| Fragmented | 779,295 → 800,228 | +2.7% | 1,049,054 → 1,245,206 | +18.7% |
| Pipeline with tail | 1,042,710 → 1,133,750 | +8.7% | 1,314,112 → 1,343,725 | +2.3% |

Allocation results match on both platforms:

| Scenario | Calls/message | Reduction | Requested bytes/message |
| --- | ---: | ---: | ---: |
| Complete | 2.005 → 1.005 | 49.9% | 60.813 → 4.813 |
| Fragmented | 7.005 → 4.005 | 42.8% | 871.813 → 703.813 |
| Pipeline with tail | 5.503 → 3.503 | 36.3% | 994.907 → 682.407 |

Linux batch-mean p95 ns/message was 1,610 → 1,310 (complete), 1,650 → 1,704
(fragmented), and 1,113 → 1,041 (pipeline). The fragmented p95 regression and
macOS complete-message throughput regression are retained in the results.
Linux peak RSS remained 19,072 KiB in both variants. macOS median peak RSS was
1,728 → 1,632 KiB, 2,032 → 1,808 KiB, and 1,872 → 1,728 KiB respectively.
These measurements establish fewer framing allocations, not a universal speedup,
lower production RSS, or higher end-to-end SIP capacity.

Raw samples, source hashes, compilers, p50/p95, and methodology:

- [Linux x86_64 report](../bench/results/stream-framing-0.6.38-linux-x86_64.json)
- [macOS arm64 report](../bench/results/stream-framing-0.6.38-macos-arm64.json)

## Reproduce

Validation completed with 50 C-backend contract files passing on macOS and Linux,
all five Linux sanitizer suites passing, both bounded fixtures passing Linux
LeakSanitizer, and the updated proxy building natively on Linux. The final
bounded fixture also covers explicit fragmented-buffer replacement at the
worker append sites. Shell/Python syntax, privacy scanning, source-hash/sample
consistency, and diff whitespace checks pass. Kluster was unavailable in this
session, so no Kluster review result is claimed.

```sh
MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/mako/runtime \
  python3 bench/stream_framing.py --runs 7 --batches 200 --iterations 1000 \
  --output /tmp/framing.json

MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/mako/runtime \
  bash scripts/check-ownership.sh
```

Framing regressions cover binary bodies containing NUL and header delimiters,
every byte split of a message, incomplete tails, multiple retained frames,
same-storage reassignment, and the 1 MiB buffer boundary. The bounded Linux
fixture additionally repeats framing and IMS renewal 2,000 times. CI keeps
ASan/UBSan and Linux LeakSanitizer enabled, and runs a small benchmark checksum
and generated-code check without a throughput threshold.
