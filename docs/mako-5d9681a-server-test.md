# Server validation of runtime 5d9681a — 2026-10-01

Madis was rebuilt and executed directly on `sip-test.example.invalid`
(`test-host`). The isolated release binary is
`/tmp/madis-verify-5d9681a/madis`. The production service was not replaced.

The candidate uses Mako runtime commit
`5d9681af15d34c3f37dd1a6cc60999d17cdd1d41` and retains the Madis ownership
adapters. That upstream commit changes only `runtime/mako_cmap.h`; the unchanged
code generator built at `249a616` was used to regenerate C before the server's
native release build. [Binary and generated-C checksums](../bench/results/madis-5d9681a-server-checksums.txt)
identify the tested artifacts.

## Checks run on the server

- [Integer-cache and transaction-state tests passed](../bench/results/madis-5d9681a-focused-tests.txt).
- [The delayed-BYE regression and UDP fault matrix passed](../bench/results/madis-5d9681a-network-checks.txt):
  pending retransmission absorption, final-response replay, loss/retransmission,
  unacknowledged 2xx, reordered/duplicate responses, and delayed responses.
- SIPp 3.7.2 exercised REGISTER and complete INVITE/200, ACK, BYE/200 calls over
  isolated loopback ports with a 100 ms hold. Proxy/caller/callee were pinned to
  CPUs 2/3/4. Each load case used a fresh candidate process on the shared server.

| Test | Caller completed | Callee completed | Generator drops | Result |
|---|---:|---:|---:|---|
| 250 CPS, 5 seconds | 1,250/1,250 | 1,250/1,250 | 0 | Pass |
| 250 CPS, 30 seconds | 7,500/7,500 | 7,500/7,500 | 0 | Pass |
| 500 CPS, 30 seconds | 14,985/15,000 | 14,999/15,000 | 0 | Fail |
| 250 CPS, 180 seconds | 45,000/45,000 | 45,000/45,000 | 0 | Pass |

At 500 CPS, 15 caller calls remained incomplete at timeout; the callee recorded
one failed call. The endpoints exited nonzero, invalidating that trial. Zero
sampled generator drops does not explain or eliminate this completion failure.

The soak had zero failed calls at both endpoints, 45,000 RTT samples, and a
279 ms p99 INVITE response time. The proxy survived an additional 90 seconds
of idle observation. RSS rose from about 27.7 MiB at startup to 117.0 MiB around
180 seconds, then held near 117.1 MiB through the idle period. Idle stability is
not proof of whole-server leak freedom; memory still rose during traffic.

These are single trials, not repeatability or capacity certification. OpenSIPS
was not rerun in this batch. The [previous matched comparison](dialog-ownership-load-test.md)
remains the comparison evidence; this run does not establish a lead over OpenSIPS.

## Runtime ownership status

Earlier direct Linux allocation checks on this same server found that the
original integer set/get leak is fixed, while empty stored values still leak
one byte per fallback read through `get_int` and `get_int2`.
[Results](../bench/results/cmap-integer-5d9681a-linux.txt) and
[#77 follow-up](https://github.com/loreste/mako/issues/77#issuecomment-5932435889)
document that remaining memory-management bug. The 100-dialog allocation probe
with the updated runtime and existing application workarounds
[passed](../bench/results/dialog-allocations-owned-5d9681a-linux.txt).
The project compiler pin and workarounds remain unchanged pending the residual fix.

## Evidence

- [Four load results and per-second memory samples](../bench/results/madis-5d9681a-server-load.json)
- [Server test driver](../bench/results/madis-5d9681a-server-run.py)
- [Raw SIPp logs, source/generated-C snapshot, build log and regression captures](../bench/results/madis-5d9681a-server-raw.tar.gz)

Kluster was unavailable. No Kluster review was run.
