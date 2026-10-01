# Current compiler ownership integration

Madis now pins `c2a2d38212903b981f967c7023c5fe07744e1d71`, including the
integer-map empty-value fix. Direct Linux allocation checks, all 56 functional
test files, the ownership gate, and the 100-dialog application allocation probe
pass. See the [current verification report](makori-cmap-integer-integration.md).
Existing application ownership adapters remain in place. Production is unchanged.

## Earlier candidate checks

The [5d9681a server release-build and load-test report](mako-5d9681a-server-test.md)
records a passing 45,000-call / 250 CPS soak and an incomplete 500 CPS trial.

Follow-up `5d9681af15d34c3f37dd1a6cc60999d17cdd1d41` fixes the original
integer-map set/get reproducer, but an existing empty value still leaks one byte
per fallback read through both `get_int` and `get_int2`. Missing-key reads pass.
[Linux results](../bench/results/cmap-integer-5d9681a-linux.txt) and the
[empty-value reproducer](../bench/cmap_integer_empty_leak_probe.c) document this
memory-management defect. The early return skips releasing the allocated empty
value; the remaining case is reported on
[#77](https://github.com/loreste/mako/issues/77#issuecomment-5932435889).
The 100-dialog application probe recompiled with the new runtime and existing
adapters [passes Linux sanitizers](../bench/results/dialog-allocations-owned-5d9681a-linux.txt).
Only the runtime header changed upstream; the generated application C was reused
with the unchanged compiler code. The project pin and ownership adapters remain
unchanged pending the residual fix. No production service was changed.

The subsequent [successful-dialog and load-test follow-up](dialog-ownership-load-test.md)
found additional runtime and temporary-ownership leaks, tracked in
[Mako issue #77](https://github.com/loreste/mako/issues/77). Madis now uses explicit
owners and map adapters for those paths. The expanded 100-dialog Linux sanitizer
probe, including transaction ticks, is clean, and all 56 functional test files
pass. The earlier bounded results below remain valid for their original scope.

Madis pins Mako `249a6168338d290966e9248257cd752cf03bd681` with its matching
runtime, including the fixes for issues #74–#76. CI, release, and IMS smoke
builds use that exact revision. Source builds run the expanded compiler probe:
retained strings, crypto/slices, SIP tag temporaries, array replacement with
literal and numeric strings, and a numeric-string append wrapper.

All 55 functional test files and the local and Linux ownership gates pass.
The combined regression fixture passes Linux ASan/UBSan/LSan and the local
built-in checker reports 2,110 allocations with zero leaks. The same
100-rejected-INVITE diagnostic now exits successfully with no reported leaks,
down from 500 bytes on the preceding compiler. See the
[complete follow-up report](makori-temporary-ownership-integration.md#follow-up-249a616)
for logs, build flags, and limitations. The built-in checker does not replace
Linux LSan, which also covers raw allocations.

This is validation of bounded diagnostics, not proof of whole-server leak
freedom or an OpenSIPS performance win. No production deployment or restart
was performed. Kluster was unavailable.

The earlier integration report below is historical; its pin and results have
been superseded by the revision above.

# Historical retained-string integration: `caa7f36`

Madis pins Mako commit `caa7f364bf7f39dedff41024674cbb7dd4f28510`
and the runtime from that same checkout. This is still version 0.6.38, but
includes the fix for [Mako issue #74](https://github.com/loreste/mako/issues/74).
The earlier 0.6.38 release does not include that fix.

The [#75 candidate evaluation](makori-temporary-ownership-integration.md) found
remaining Linux leak-check failures; that candidate has not replaced this pin.

## Changes

- CI, release, and optional IMS builds use the exact commit and Cargo lockfile.
- Source-build checks execute `tests/compiler_ownership_test.mko` in a temporary
  directory with the selected compiler/runtime. They require an explicit clean
  leak report with a positive allocation count. A zero process exit alone is
  insufficient because Mako's leak checker does not fail the process on leaks.
- Twelve message replacements in the SIP core no longer assign an empty string
  before adopting an owned helper result. Named results remain to keep the
  evaluation and replacement order clear.
- The forwarding ownership fixture exercises ordinary replacement while keeping
  a snapshot alive. The standalone compiler fixture covers named and direct
  same-buffer returns plus a newly allocated replacement.

The range-based forwarding optimizations and other ownership fixtures remain.
This upgrade does not establish whole-server leak freedom or an OpenSIPS win.
The previous benchmark reports describe the previous compiler and remain
historical evidence, not measurements of this integration.

## Local validation

Using a clean build of the pinned commit and its matching runtime on macOS:

- All 55 Madis Mako test files pass.
- The ownership gate passes AddressSanitizer/UndefinedBehaviorSanitizer.
- The upstream 21-case string alias fixture passes with its built-in leak check
  reporting 39 allocations and zero leaks, and passes AddressSanitizer.
- Both worker and admin pass compiler checks, link as native binaries, and
  remain healthy after the broken-pipe check.
- The typed stream framing smoke benchmark completes successfully.
- Lint passes; the worker retains three unused-variable warnings.
- The pre-fix 0.6.38 release is rejected by the source-build probe. Gate tests
  also reject leaked, missing, zero-allocation, and failed-test reports.

## Linux validation

The pinned compiler was built from source with `cargo build --release --locked
--offline --bin makori`. The matching runtime was used throughout.

The [ownership gate log](../bench/results/ownership-caa7f36-linux.txt) records a
clean ASan/UBSan run, with LeakSanitizer enabled for bounded ownership fixtures.
The worker also built successfully with the normal release C flags.

The same 100-INVITE, unregistered-target allocation probe used previously still
returns the expected 404 responses. Its [sanitizer report](../bench/results/proxy-allocations-caa7f36-linux.txt)
shows 63,278 unreachable bytes in 2,201 allocations, versus 71,278 bytes in
2,301 allocations with the earlier compiler and explicit ownership workaround.
This is an 8,000-byte reduction in this probe only. LSan still fails because
other leaks remain, including SHA-256 temporaries in MAF and B2BUA paths.
No invalid-access ASan or UBSan error was reported. Maps remain reachable
process-lifetime roots, so this is not a whole-server memory bound.

These checks support removing the workaround with the pinned compiler. They
do not establish an OpenSIPS performance win; sustained comparative benchmarks
have not been rerun for this integration.

Kluster was unavailable during this integration. This work did not replace or
restart production.
