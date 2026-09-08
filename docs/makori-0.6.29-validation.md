# Makori 0.6.29 validation — 2026-09-08

Status: **not ready to merge**. Keep the ownership gate failing until the
underlying leaks are fixed; do not disable leak detection to make CI green.

## Toolchain and environment

- Madis adoption commit: `311ffa2` (follow-up benchmark checks are on the same PR).
- Compiler/runtime pin: `a4d57046072fc573c6411c6167a038864e4a4095`.
- Linux runtime tests used the official `v0.6.29` x86-64 release archive,
  SHA-256 `a3d199d1fe657f389bbede69f96efabf5950b03e5a7e172746d1fa63797c76f6`.
  Its release commit `1225db37fae11b7505dd6c5c682cf5f1835c3342` differs from
  the pin only in `docs/ROADMAP.md`.
- Traffic host: Ubuntu Linux x86-64, kernel 6.8, 8 logical CPUs, approximately
  24 GiB RAM. All SIP traffic was loopback, with no subscriber database.
- Docker source-build check: Debian bookworm, Linux arm64, compiler built
  from the exact pin and runtime from the same checkout.

## Results

| Check | Result |
| --- | --- |
| macOS Mako tests | 46 files passed |
| macOS proxy/admin C-backend release builds | Passed |
| macOS focused ASan/UBSan suites | Passed |
| GitHub Linux project checks | Passed before the new ownership gate |
| Linux ownership LeakSanitizer | Failed: 439,422 bytes in 22,203 allocations |
| Docker source build | Passed with explicit C backend and matching runtime |
| Docker startup/health | Authenticated `/healthz` returned `ok: true` |
| Sustained REGISTER/INVITE attempt | Failed; see below |

Both the specified Linux host and GitHub Actions reproduced the exact leak
summary. Allocation stacks include Contact splitting, Contact-array updates,
HEP packet construction, and string/channel ownership. The fixture's logical
assertions passed before LeakSanitizer failed the process. This is not a clean
memory result.

GitHub evidence: [Linux validation run](https://github.com/Izi-Technologies/madis/actions/runs/34263186697).

## Traffic attempt

The intended run was 15,000 INVITE/ACK/BYE dialogs at 50 calls/second, a
one-second dialog hold, concurrency limit 200, two UDP workers, and one
REGISTER refresh/second. Process resources were sampled every second and
authenticated `/state` every five seconds.

The proxy stopped after approximately 26 seconds. The last resource sample
showed RSS increasing from 10,348 KiB to 243,852 KiB over 25.486 seconds, with
file descriptors increasing from 8 to 9. SIPp ultimately reported 1,173
successful and 6,200 failed dialogs. The run cannot establish steady-state
memory use, sustainable throughput, or a regression relative to 0.6.25.
The exit's root cause was not established by the initial run.

The existing harness hid SIPp's nonzero status and used a fixed 180-second
timeout, so it incorrectly returned success despite these failures. The
follow-up checks preserve SIPp failure status, reject an exited proxy, and
require the final cumulative counters to show every requested call succeeded
with zero failures. `BENCH_TIMEOUT` now permits longer runs; for this load,
use at least `BENCH_TIMEOUT=420s`. Six unit cases cover statistics validation.

## Upstream JSON fix

[Makori PR #54](https://github.com/loreste/mako/pull/54) escapes all JSON control
bytes, including object keys and embedded NUL. The regression passes on
Linux and macOS with the C backend and ASan/UBSan, and on macOS's direct native
backend. Madis retains its compatibility handling until a released compiler
containing the fix is pinned.

The upstream compiler's general performance gate fails on the recursive
`fib30x5` workload. A paired check using the same compiler with the unmodified
runtime also fails that workload (41.4 ms baseline versus 38.9 ms patched
median); generated tracing calls predate the JSON fix. This is a separate
compiler performance issue, not evidence of a JSON throughput regression.
