# Stateful UDP comparison with OpenSIPS

Madis has improved, but a general OpenSIPS performance win is **not established**.
The [September 30 server load tests](opensips-249a616-load-test.md) with compiler
`249a616` supersede the results below: Madis passed 2/3 trials at 500 CPS, but
neither proxy passed a 1,000-CPS trial or the three-minute 250-CPS soak.
Madis RSS continued growing during the soak. The sections below are historical.
The September 28 candidate combined UDP receive tuning, single-pass header validation,
range-based forwarding rewrites, conditional command hashing, and message-owner
fixes for Mako 0.6.38. In the latest three 30-second trials at 1,000 CPS,
Madis passed none and OpenSIPS passed one. Shared-host variation and generator
drops limit capacity conclusions, but these results do not support a win.
No production proxy binary was replaced or restarted.

The comparison uses the same SIPp caller and callee for both proxies: one
in-memory registration, INVITE/200, ACK, a 100 ms call, then BYE/200. The caller
uses the Contact and Record-Route returned by the proxy. No media is generated.
Both caller and callee must report every expected call successful, with zero
failed calls, and the caller must record one INVITE RTT sample per call.

`bench/compare_opensips.py` runs an explicitly supplied binary in its own process
group, checks for occupied benchmark ports, and cleans up that group on exit.
It never manages system services. The proxy runs on CPU 2, caller on CPU 3, and
callee on CPU 4. Run on Linux with those CPUs available. Use a dedicated host
for publishable capacity results; production activity on a shared host can
affect these measurements despite CPU pinning.

Madis uses one UDP worker and its normal validation, transaction, routing and
metrics code, without a database. Private targets are allowed for loopback.
The admin endpoint uses port 18080 with a random token. OpenSIPS uses one UDP
worker, `tm`, `rr`, `registrar`, and an in-memory `usrloc`, with Max-Forwards
checking. These configurations support the same tested call flow, but are not
feature-identical security or accounting profiles. OpenSIPS 4.0.2 includes the
UDP module statically; the configuration must still load `proto_udp.so`.
The final harness gives OpenSIPS 256 MiB of shared memory and 16 MiB of private
memory per process (`-m 256 -M 16`), rather than relying on its small default
shared-memory pool. Madis uses dynamically allocated process memory. Memory
efficiency is not compared here.

Example, after installing or extracting SIPp and OpenSIPS into a scratch directory:

```sh
python3 bench/compare_opensips.py --kind madis --binary /path/to/madis \
  --sipp /path/to/sipp --rate 250 --seconds 5 --output /tmp/madis-run-1
python3 bench/compare_opensips.py --kind opensips --binary /path/to/opensips \
  --modules /path/to/opensips/modules --sipp /path/to/sipp \
  --rate 250 --seconds 5 --output /tmp/opensips-run-1
```

Each output directory must be new. Keep stdout/stderr, SIPp statistics, RTT CSV,
generated configuration and `result.json` together. Results include executable
and fixture SHA-256 hashes, CPU affinity, call counts, retransmissions, watchdog
events, and p50/p95/p99 INVITE RTT. The final harness also samples socket queue
depths/drop counters every 50 ms and records per-CPU busy/steal fractions over
the caller's lifetime, including drain. These CPU fractions include other
processes on the shared host. Drop samples may miss events immediately before
a socket closes. SIPp requests 1 MiB send/receive buffers; kernel limits still
apply. A run with sampled generator drops is rejected even if calls complete.
Both SIPp control sockets are bound to loopback on ports 15080/15081.
SIPp's millisecond timing and event-loop
scheduling limit the interpretation of very short RTTs. Rotate candidate order
between repetitions. Build before timing, using the same Madis release compiler
and flags for before/after comparisons.

## September 28, 2026 measurements

### Profile-guided forwarding and ownership work

CPU-clock profiles of the previous candidate put repeated header parsing,
allocation, and UDP sends ahead of transaction housekeeping. The
[call-stack profile](../bench/results/profile-owned-dwarf-0.6.38-linux.txt)
recorded 1,095 samples without loss; inclusive percentages overlap and must not
be added. A [minor-fault profile](../bench/results/profile-allocation-faults-0.6.38-linux.txt)
identified message rewriting among allocation callers. Sampled RSS grew
throughout the workload; [memory samples](../bench/results/forwarding-memory-0.6.38-linux.json)
are diagnostic observations, not a comparison with OpenSIPS memory use.

Retained changes:

- Compute the application-command identity only when the hook returns a command.
  Every non-empty command retains the same signature and exact-message binding.
- Extract IMS routing fields once from the owned, validated registration snapshot.
  Invalid, expired, and deregistered records still fail validation.
- Use Mako range searches and builder range writes for Max-Forwards rewriting and
  top-Via removal; loop detection also avoids copying a Via line. Frozen-reference
  comparisons cover byte mutations, compact Via, comma-separated Via, missing
  headers, and mixed-case names. Dedicated production ownership tests pass LSan.
- Retain helper results before replacing mutable messages, explicitly releasing
  the previous owner before transfer. Mako 0.6.38 otherwise leaks old owners when
  a helper result shares the same reference-counted buffer. Snapshot-preservation
  tests cover both shared and newly allocated results.

A C diagnostic harness includes the normal generated application C because
Mako's test compiler emitted duplicate actor-state definitions when a Mako test
called the full request core. This does not alter production C or the runtime.
The harness sends 100 unique INVITEs through the unregistered-target path,
requires a 404 result, and keeps transaction maps as process-lifetime roots.
It does not establish whole-server leak freedom or a successful-call memory bound.

| Diagnostic stage | Unreachable bytes | Allocations |
|---|---:|---:|
| Before message-owner changes | 175,998 | 2,701 |
| Named results before assignment | 124,438 | 2,501 |
| Explicit release and transfer | 71,278 | 2,301 |

The [before](../bench/results/proxy-allocations-before-0.6.38-linux.txt) and
[after](../bench/results/proxy-allocations-after-0.6.38-linux.txt) reports retain
all findings. The 59.5% reduction is limited to this probe; remaining leaks
include other string temporaries and RTP configuration arrays. LSan therefore
still fails the broader diagnostic. ASan/UBSan found no invalid access there.

An LTO-only experiment and smaller, more frequent server-timer sweeps did not
produce a clean sustained trial and were not retained. The
[seven diagnostic/follow-up runs](../bench/results/opensips-profile-followups-0.6.38-linux.json)
include those failures. Profiled runs are not competitive baselines.

Before the final owner-transfer change, the
[six matched range-rewrite runs](../bench/results/opensips-udp-range-0.6.38-linux.json)
at 1,000 CPS for 30 seconds yielded one valid run out of three for each proxy.
The successful Madis run had p50/p95 3/26.001 ms; OpenSIPS had 2/24.001 ms.
Madis's other caller completions were 29,838 and 29,189 of 30,000, with zero
sampled generator drops. This is not a sustained-capacity win.

Validation: all 54 Mako test files passed on the final message-owner code.
Forwarding ownership, including retained snapshots, passes Linux ASan/UBSan/LSan.
Range equivalence, application-command, and IMS snapshot suites pass Linux
ASan/UBSan. Their frozen references/process-lifetime resources are excluded from
LSan; production forwarding ownership is checked separately. Kluster remains
unavailable. No production proxy process was replaced or restarted.


### Final owner-transfer candidate

The [six final trials and memory samples](../bench/results/opensips-udp-transfer-0.6.38-linux.json)
used normal release flags and alternated order M/O, O/M, M/O. Each trial
attempted 30,000 calls at 1,000 CPS over 30 seconds.

| Proxy | Run 1 completed | Run 2 completed | Run 3 completed | Valid runs |
|---|---:|---:|---:|---:|
| Madis | 24,845 | 28,702 | 27,265 | 0/3 |
| OpenSIPS | 29,390 | 30,000 | 29,279 | 1/3 |

Completion counts are caller successes; validity additionally requires all
callee completions and the checks described above. All five failed trials had
sampled generator drops. The sole valid OpenSIPS trial had p50/p95/p99 RTT of
3/50/115.001 ms. Failed-run latency must not be presented as a competitive win.

Madis RSS grew from 157,792–161,840 KiB at the first sample to
654,084–691,096 KiB at the sixth sample, nominally four seconds apart. Lower
sampled RSS than earlier candidates is not a controlled memory improvement:
call completions and retransmission load differ, and this experiment does not
establish a memory bound. Allocation leaks and sustained overload remain
unresolved. Repeat on a dedicated host with generators that do not drop packets
before attributing run-to-run changes or publishing a capacity claim.

### Validator scan and ownership follow-up

The validator now counts singleton headers during its existing header syntax
scan instead of making six additional counting passes. It reuses the ingress
control-character check and delimiter search. Compact aliases, duplicate
singletons, folded lines, equal duplicate Content-Length values, and header
limits remain covered by differential tests against the old scan logic.

Mako 0.6.38's emitted C omitted cleanup for slice-expression bindings and some
nested builtin string arguments. Named `str_slice` results and named header
arguments restore compiler-managed cleanup. The initial 2,000-validation fixture
leaked 390,000 bytes in 30,000 allocations; the same fixture now passes Linux
ASan/UBSan/LSan. Expanded cases cover 4,000 valid/invalid validations and malformed
byte mutations. This is a bounded validator result, not a whole-server leak claim.
CI's ownership gate now includes this fixture and the scan differential tests.
The frozen oracle retains old validator temporaries, so only its differential
suite disables LSan; the production-only fixture requires LSan on Linux.

The [local microbenchmark](../bench/results/validation-scan-0.6.38-macos.json)
reduced median time for 100,000 validations from 622 to 441 ms (29.1%). Both
variants share current semantic helpers; the oracle preserves pre-scan validation
logic. These macOS timings do not measure SIP throughput.

The [18 scan-only runs](../bench/results/opensips-udp-scan-0.6.38-linux.json)
preserve the intermediate experiment, including failures. The subsequent
[12 ownership-fixed runs](../bench/results/opensips-udp-owned-0.6.38-linux.json)
used the same final harness, loopback control sockets, memory settings, and
five-second scenarios, alternating candidate order:

| Offered CPS | Candidate | Valid runs | Median per-run p50 / p95 |
|---:|---|---:|---:|
| 250 | Madis, scan + ownership | 3 / 3 | 3 / 11.001 ms |
| 250 | OpenSIPS 4.0.2 | 3 / 3 | 1 / 23.001 ms |
| 1,000 | Madis, scan + ownership | 3 / 3 | 3 / 58.001 ms |
| 1,000 | OpenSIPS 4.0.2 | 2 / 3 | Not aggregated: failed run |

Madis completed all 5,000 calls at both endpoints in each 1,000-CPS run, with no
sampled proxy or generator drops. The failed OpenSIPS run completed 4,941 calls
at the caller and had 202 sampled proxy drops, with no sampled generator drops.
Its two successful runs had p50/p95 of 2/13 and 1/5 ms. The better Madis completion
count in this small series does not establish superior capacity; earlier
series varied markedly on this shared host.

The [30-second follow-up](../bench/results/opensips-udp-owned-long-0.6.38-linux.json)
then invalidated both candidates at 1,000 CPS (30,000 expected calls), with
OpenSIPS run first and Madis second:

| Candidate | Caller / callee completed | Sampled proxy / generator drops |
|---|---:|---:|
| Madis, scan + ownership | 27,839 / 28,064 | 13,401 / 2 |
| OpenSIPS 4.0.2 | 29,944 / 29,933 | 363 / 157 |

Neither result establishes sustained capacity. Madis's substantial proxy drops
cannot be explained away by its two sampled generator drops. The short-run
completion improvement therefore does **not** demonstrate sustained 1,000 CPS.
The worker joins periodic transaction housekeeping on its receive thread;
that path is a profiling candidate, not a confirmed cause of these failures.

Validation: all 52 Mako test files passed. The expanded ownership fixture then
passed Linux ASan/UBSan/LSan; scan differential tests passed ASan/UBSan. The Linux
release build succeeded. Kluster was unavailable throughout this work.


### Earlier UDP tuning comparison

The [final 12 runs](../bench/results/opensips-udp-final-0.6.38-linux.json) use the
retained Madis changes, OpenSIPS's corrected memory allocation and larger SIPp
buffers. Both proxies had an effective 425,984-byte UDP receive buffer on this
host. Candidate order alternated between repetitions.

| Offered CPS | Candidate | Valid runs | Median per-run p50 / p95 |
|---:|---|---:|---:|
| 250 | Madis, tuned | 3 / 3 | 3 / 20 ms |
| 250 | OpenSIPS 4.0.2 | 3 / 3 | 1 / 15 ms |
| 1,000 | Madis, tuned | 1 / 3 | Not compared: failed runs |
| 1,000 | OpenSIPS 4.0.2 | 2 / 3 | Not compared: failed runs |

Each 250 CPS run completed 1,250 calls at both endpoints. At 1,000 CPS, Madis
caller completions were 4,695, 4,959 and 5,000 of 5,000 expected. OpenSIPS caller
completions were 5,000, 5,000 and 4,917. One failing run of each proxy also had
generator drops. The other failing Madis run had 99 sampled proxy-socket drops
and zero sampled generator drops, so the generator does not explain every
failure. CPU use and burst handling need more work before claiming parity or
a win. One successful short run is not a sustainable capacity result.

After these measurements, the harness's SIPp **control** sockets were pinned
to explicit loopback ports and smoke-tested. The measured script hashes
therefore predate that control-only change; SIP signaling scenarios and
load settings are unchanged.

Validation: all 50 Mako test files passed with the final UDP changes; the Linux
release binary built with Mako 0.6.38's C backend. Kluster was unavailable, so
its required review could not be performed.

### Exploratory history

The [raw results](../bench/results/opensips-udp-0.6.38-linux.json) contain 27 runs
on an 8-vCPU AMD EPYC VM running Ubuntu 24.04 / Linux 6.8.0-136. Madis used
Mako 0.6.38's C backend and GCC 13.3 with the repository's `build-native.sh`
release flags. OpenSIPS was the official 4.0.2-1 Ubuntu package; SIPp was 3.7.2.
Each candidate received three five-second runs at each offered rate, with
candidate order rotated between repetitions. The host also served production
traffic. These are exploratory results, not dedicated-host capacity evidence.

The first experiment replaced the fixed 10 ms idle sleep with a persistent
level-triggered event loop, `evloop_add(loop, fd, 1)` and
`evloop_wait(loop, 10)`. It retained the drain limit and housekeeping interval.
The following are medians of the three per-run percentiles, in milliseconds:

| Offered CPS | Baseline p50 / p95 | Readiness p50 / p95 | OpenSIPS p50 / p95 |
|---:|---:|---:|---:|
| 50 | 13 / 22 | 3 / 29 | 2 / 13 |
| 250 | 9 / 23 | 3 / 115 | 1 / 42 |

All 18 runs at these two rates completed every call at both endpoints. One
readiness run had two callee retransmissions. Lower median latency came with
worse p95 latency, so the readiness experiment does not justify a default
production change or an OpenSIPS performance claim.

At 1,000 CPS, **all nine exploratory runs failed** the completion criterion. Out of 5,000
expected calls per run, caller completions ranged from 4,126–4,822 for the
baseline, 4,727–4,971 for readiness and 2,938–3,443 for OpenSIPS. These partial
completion counts do not establish sustainable throughput; latency among
surviving calls also excludes failed calls. OpenSIPS logs revealed exhaustion
of its default shared-memory pool: **its exploratory 1,000 CPS results are
invalid as a competitive baseline**. The harness was corrected to allocate
256 MiB, and matched reruns supersede those results. Madis logs include
unexpected BYE/481 responses and substantial retransmission counts; generator
and socket-buffer limits still need investigation. An initial baseline trial also failed before
the harness's callee timeout was corrected; that aborted trial is not among
the 27 completed result files.

A separate eight-second CPU-clock profile at 250 CPS collected 432 samples,
with no lost samples. Kernel `_raw_spin_unlock_irqrestore` accounted for 24.31%
of samples, predominantly along UDP socket wakeup paths. Other sampled work
included header parsing, map operations and allocation. This is a diagnostic
lead, not proof that event notification caused the tail-latency regression.

The readiness change was removed. The retained candidate reduces the existing
idle sleep from 10 ms to 1 ms, preserving the receive batching and housekeeping
logic. This can increase idle wakeups by up to tenfold; idle CPU cost has not
been measured. At sustained load, waiting still happens only after a receive
attempt finds no datagram. It also requests a 262,144-byte `SO_RCVBUF` through
Mako's `tcp_set_recv_buf` helper, which operates at `SOL_SOCKET` and supports
UDP descriptors. Linux's cap/doubling rules gave 425,984 effective bytes here,
up from 212,992. Failure to tune the buffer logs once and keeps the OS default.

The [36 intermediate runs](../bench/results/opensips-udp-followups-0.6.38-linux.json)
preserve the 1 ms pilot, corrected OpenSIPS memory comparisons, and the first
socket-drop instrumentation. They explain why generator buffering and proxy
buffering were both investigated; superseded runs are not discarded to make
the final result look better.

Raw logs, RTT CSVs and the profile remain in
`/tmp/madis-opensips.6Xq9rD` on the benchmark host. No production service was
restarted or replaced. The stale `makori` 0.6.9 executable was backed up and
replaced with an alias to the installed `mako` 0.6.38 executable.

This fixture does not establish maximum sustainable throughput, CPU efficiency,
memory efficiency, authenticated registrar performance, or TCP/TLS performance.
Those require separate longer runs, resource measurements and generator
saturation checks. Do not infer a general OpenSIPS performance win from a
successful fixed-rate loopback run.
