# Compiler ownership fix evaluations

**Current result:** `249a6168338d290966e9248257cd752cf03bd681` passes all
focused regressions and the 100-request leak probe and is now pinned for builds.
See [the accepted follow-up](#follow-up-249a616). Earlier sections below record
historical candidates and their failures.

## Initial candidate: `47f661b`

Candidate `47f661b5926a9bc2879b4ad6c7e27b988a0a376e` addresses crypto
argument and slice-base temporaries from [Mako issue #75](https://github.com/loreste/mako/issues/75).
It did not replace the then-current `caa7f36` pin: Linux LeakSanitizer failed
both the upstream regression fixture and an expanded Madis fixture.

## Results

- All 55 Madis Mako test files pass functional assertions with the candidate.
- Worker and admin build with the normal release C flags and pass broken-pipe
  health checks. Local ownership ASan/UBSan checks pass with macOS leak checking
  disabled, as in the existing gate.
- The upstream four-case #75 fixture reports 140 allocations and zero leaks
  with the built-in checker and local ASan/UBSan.
- The same upstream fixture fails Linux LSan: **660 bytes in 20 allocations**.
  See the [complete upstream report](../bench/results/upstream-issue75-47f661b-linux.txt).
- The expanded Madis compiler probe passes functional assertions and the
  built-in leak checker, but fails Linux LSan: **3,333 bytes in 101 allocations**.
  See the [complete report](../bench/results/ownership-47f661b-linux.txt) and
  [preserved diagnostic fixture](../bench/issue75_temporary_ownership_test.mko).
  This fixture is kept outside the normal suite while the existing pin remains.
- The previous compiler reports 200 leaked allocations in that expanded
  built-in probe. The new fix therefore improves the targeted cleanup, but
  the built-in clean report is insufficient to establish leak freedom.

The remaining small-fixture stacks originate in `mako_str_slice`, including
slice results retained in local bindings and nested expressions. These are
not invalid-access sanitizer reports. The full request-path allocation probe
is evaluated separately below; its result must not be substituted for the
focused fixture failures.

## Request-path probe

The same 100 unique rejected INVITEs all returned their expected 404 responses.
The [full Linux report](../bench/results/proxy-allocations-47f661b-linux.txt)
records **40,298 leaked bytes in 1,801 allocations**, down from 63,278 bytes
in 2,201 allocations on `caa7f36`. The 22,980-byte reduction confirms progress
on the digest/input temporary paths. It does not resolve the focused slice-result
failures above or establish whole-server leak freedom. The probe retains maps
as reachable process-lifetime roots. No invalid-access ASan or UBSan error was
reported; LSan still fails.

To reproduce the focused candidate failure on Linux with the candidate compiler
and matching runtime, run:

```sh
repro_dir=$(mktemp -d)
cp bench/issue75_temporary_ownership_test.mko "$repro_dir/ownership_test.mko"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 UBSAN_OPTIONS=halt_on_error=1 \
  makori test "$repro_dir/ownership_test.mko" \
  --backend c --sanitize address,undefined
```

Use a clean temporary directory: Mako merges sibling compilation units, so
running directly from `bench/` also imports unrelated benchmark code.

The upstream reproduction is
`examples/testing/issue75_sha256_leak_test.mko` in the Mako checkout, using the
same flags. Recheck both with Linux LSan before promoting the candidate.

## Follow-up: `f6ca048`

Commit `f6ca048d1ae8ab90a1b84e94ec6356faeb11e129` changes string-keyed
`has()` arguments to use `emit_str_arg`. It does not change the separate
`cmap_get()`/`cmap_has()` compiler paths used by Madis's reported cache-key
leaks; those still emit the key using `emit_expr`. It also does not modify
slice-result cleanup.

A fresh Linux compiler build with the matching runtime reproduces both focused
failures with unchanged counts:

| Fixture | Leaked bytes | Allocations |
|---|---:|---:|
| Upstream #75 regression | 660 | 20 |
| Expanded Madis regression | 3,333 | 101 |

The [upstream report](../bench/results/upstream-issue75-f6ca048-linux.txt) and
[Madis report](../bench/results/ownership-f6ca048-linux.txt) retain the complete
stacks. Both fixture processes exit 1 under Linux ASan/UBSan with LSan enabled;
functional assertions pass. The candidate has not replaced the `caa7f36` pin.
The Linux compiler uses the same reduced-Rust-optimization build method below.

The worker builds with normal release C flags. The same 100-INVITE probe
returns the expected 404 responses and still reports **40,298 leaked bytes in
1,801 allocations**, unchanged from `47f661b`. See the
[full request-path report](../bench/results/proxy-allocations-f6ca048-linux.txt).
No invalid-access ASan or UBSan error was reported; the probe exits 1 for leaks.
The new ordinary-map `has()` fix does not reduce leaks in this tested path.

## Follow-up: `bb36025`

Commit `bb36025a457d18093b991f13aca764a8fc36a5d7` registers string slice
results for own-drop and changes concurrent-map key/value arguments to
`emit_str_arg`. The same Linux build method and matching runtime were used.
The pin remains `caa7f36` because focused Linux LSan checks still fail.

| Diagnostic | Leaked bytes | Allocations |
|---|---:|---:|
| Upstream #75 regression | 830 | 30 |
| Isolated expanded Madis regression | 3,366 | 102 |
| 100-INVITE request probe | 24,068 | 1,597 |

Complete reports: [upstream](../bench/results/upstream-issue75-bb36025-linux.txt),
[isolated fixture](../bench/results/ownership-bb36025-linux.txt),
[request probe](../bench/results/proxy-allocations-bb36025-linux.txt).
The request probe improves by 16,230 bytes from `f6ca048`; it still fails LSan.
All expected 404 responses were received. No invalid-access ASan or UBSan error
was reported in these diagnostics.

All 55 Madis functional test files pass, and the existing local ASan/UBSan
ownership gate passes. The isolated local regression reports 808 RC allocations
and zero leaks with the built-in checker; Linux LSan still finds the raw slice
allocations above. This is why the built-in checker cannot replace LSan here.
An initial local run from `bench/` imported neighboring benchmark code and was
discarded; the reported focused result uses a clean directory.

The [emitted C function](../bench/results/slice-cleanup-bb36025-generated-c.txt)
provides additional evidence: `expected` and slice temporaries `__mako_sl_10`,
`__mako_sl_17`, and `__mako_sl_20` have no corresponding `mako_str_free` calls
in that function. The digest itself is freed. This was emitted from the same
standalone fixture with a `main` calling its crypto test; it is code-generation
inspection, separate from the test-runner LSan measurements.

## Follow-up: `e241e7a` (includes `3ffc70d`)

The next slice fix, `3ffc70d21a9522f1473fa962fdfa6bc7ea2e9627`, was tested
as part of HEAD `e241e7a868045bd29c05cf7c9c81d5597844ff6c`, with its matching
runtime and the same Linux build method. All 55 functional test files and the
existing local sanitizer ownership gate pass. The isolated local built-in
checker reports 808 allocations and zero leaks.

Linux LSan still fails, but the expanded fixture now has only its named-binding
leak and the request-path totals improve:

| Diagnostic | Leaked bytes | Allocations |
|---|---:|---:|
| Upstream #75 regression | 660 | 20 |
| Isolated expanded Madis regression | 33 | 1 |
| New minimal named-slice regression | 500 | 100 |
| 100-INVITE request probe | 17,600 | 1,200 |

Reports: [upstream](../bench/results/upstream-issue75-e241e7a-linux.txt),
[expanded fixture](../bench/results/ownership-e241e7a-linux.txt),
[minimal fixture](../bench/results/named-slice-e241e7a-linux.txt),
[request probe](../bench/results/proxy-allocations-e241e7a-linux.txt).
All expected assertions/404 responses pass. No invalid-access ASan or UBSan
error was reported. These are separate diagnostics, not additive counts.

The [minimal reproduction](../bench/issue76_named_slice_test.mko) repeats
`let piece = source[0:4]` 100 times while checking that the source remains valid.
Run it from a clean directory as described above. Each copied slice leaks five
bytes. Code inspection identifies the likely missing step:
`expr_is_scope_drop_safe` recognizes string slices, but `expr_is_fresh_own`
still falls through to false for `Expr::Slice`; the `Stmt::Let` auto-drop path
is gated on that second helper. Binding cleanup must distinguish allocating
string slices from non-owning array/byte views.

The candidate remains unpromoted and the pin stays at `caa7f36`. No production
binary was replaced or restarted.

## Follow-up: `0e63b41`

Commit `0e63b41917750a9d568a2a1bec2a76d8a870c28a` adds slice expressions
to `expr_is_fresh_own`, enabling scope-exit cleanup for named slice bindings.
All three focused Linux ASan/UBSan/LSan diagnostics now exit successfully:

- [Upstream #75 regression](../bench/results/upstream-issue75-0e63b41-linux.txt): no reported leaks (previously 660 bytes / 20 allocations).
- [Expanded Madis regression](../bench/results/ownership-0e63b41-linux.txt): no reported leaks (previously 33 bytes / 1 allocation).
- [Named-slice regression](../bench/results/named-slice-0e63b41-linux.txt): no reported leaks (previously 500 bytes / 100 allocations).

All 55 local functional test files pass. The local ASan/UBSan gate and the
[Linux ownership gate](../bench/results/ownership-gate-0e63b41-linux.txt) pass;
the latter enables LSan for the five ownership suites, with its existing
documented exclusions for the five contract/differential suites.

The same [100-rejected-INVITE diagnostic](../bench/results/proxy-allocations-0e63b41-linux.txt)
still reports **17,600 bytes in 1,200 leaked allocations**, unchanged from
`e241e7a`. All requests return the expected 404; no invalid-access ASan or
UBSan error is reported. Remaining stacks include `mako_sip_header_n`,
`mako_str_from_cstr`, `mako_str_clone`, and `mako_int_to_string`, across B2BUA,
request processing, transaction lookup, and RTP configuration paths. These
stacks identify investigation targets, not a proven common root cause.

The fixtures use isolated directories; the full probe reuses the same Madis
scratch source as the preceding measurements. Both compiler builds use this
exact commit and its matching runtime, with the reduced compiler optimization
flags described below. The compiler pin stays at `caa7f36`; no production
deployment or restart was performed. These results do not establish an
OpenSIPS performance win. Kluster remains unavailable in this session.

## Follow-up: `4a6e711`

Commit `4a6e7115fed1788ef74a0d4916c31fee883bb72c` routes SIP header/view
string arguments through `emit_str_arg`. The same 100-rejected-INVITE probe
improves from 17,600 bytes / 1,200 allocations to **7,200 bytes / 500 allocations**
([full report](../bench/results/proxy-allocations-4a6e711-linux.txt)). All 100
responses are the expected 404. No invalid-access ASan or UBSan error appears.

All 55 local functional test files and the local and
[Linux ownership gates](../bench/results/ownership-gate-4a6e711-linux.txt) pass.
The isolated [named-slice](../bench/results/named-slice-4a6e711-linux.txt),
[expanded crypto/retained-string](../bench/results/ownership-4a6e711-linux.txt),
and [upstream #75](../bench/results/upstream-issue75-4a6e711-linux.txt)
regressions remain LSan-clean.

Two new isolated reproducers pass their assertions but fail Linux LSan:

- [SIP-tag temporary](../bench/issue76_sip_tag_temporary_test.mko):
  `msg |> sip_header("From") |> sip_addr_tag()` leaks 2,600 bytes / 100 allocations
  ([report](../bench/results/sip-tag-4a6e711-linux.txt)). `sip_addr_tag` still uses
  `emit_expr` for its string argument, unlike the SIP builtins changed by this commit.
- [String-array replacement](../bench/issue76_array_replacement_test.mko):
  replacing a three-string array with a function-produced copy leaks 4,100 bytes /
  300 allocations ([report](../bench/results/array-replacement-4a6e711-linux.txt)).
  This isolates a pattern used in RTP configuration; it does not establish the
  compiler's exact missing cleanup operation.

Run each reproducer in its own clean directory using the sanitizer command
above. The array fixture's initial compilation required correcting its local
result binding to `let mut`; the saved report is from the corrected fixture.
These are separate diagnostics and their leak counts must not be added to the
full-probe result. The remaining full-probe stacks include SIP-tag extraction,
transaction lookup, and RTP configuration.

Compiler and matching runtime were built from the exact commit using the same
flags below. The application scratch snapshot is unchanged. The compiler pin
remains `caa7f36`; production was not restarted or deployed. Kluster tools remain
unavailable. This does not establish an OpenSIPS performance win.

## Follow-up: `f0006ce`

Commit `f0006ce965a4d2e1b858b1ea190dfa3beb9d59cc` extends `emit_str_arg`
cleanup to the remaining SIP builtins. The isolated
[SIP-tag reproducer now passes Linux LSan](../bench/results/sip-tag-f0006ce-linux.txt),
eliminating its previous 2,600 bytes / 100 allocations. The
[named-slice](../bench/results/named-slice-f0006ce-linux.txt),
[expanded crypto/retained-string](../bench/results/ownership-f0006ce-linux.txt),
and [upstream #75](../bench/results/upstream-issue75-f0006ce-linux.txt)
regressions remain clean.

The same [100-rejected-INVITE probe](../bench/results/proxy-allocations-f0006ce-linux.txt)
improves from 7,200 bytes / 500 allocations to **4,600 bytes / 400 allocations**.
All 100 requests return 404; no invalid-access ASan or UBSan error is reported.
Remaining stacks account for 1,300 bytes in transaction lookup and 3,300 bytes
in RTP configuration. Code inspection finds `cmap_has2` still emitting both
string arguments with `emit_expr`; this is a likely cleanup gap, not a separately
isolated runtime proof for that builtin.

The [string-array replacement reproducer](../bench/issue76_array_replacement_test.mko)
still passes its assertions but fails LSan with **4,100 bytes / 300 allocations**
([report](../bench/results/array-replacement-f0006ce-linux.txt)). This is a
separate diagnostic and is not additive to the full-probe count.

All 55 local functional test files and both local and
[Linux ownership gates](../bench/results/ownership-gate-f0006ce-linux.txt) pass.
The existing gates therefore do not cover the two remaining leak paths.
Compiler/runtime, build flags, fixture isolation, and application snapshot
follow the same procedure as the preceding measurements. The compiler pin
stays at `caa7f36`; production was not deployed or restarted. Kluster remains
unavailable. No OpenSIPS performance comparison was run.

## Follow-up: `71dbcc3`

Commit `71dbcc32478e932b7c5e0352ad2dfda31040f9fd` adds temporary cleanup
for CMap key arguments. The same
[100-rejected-INVITE probe](../bench/results/proxy-allocations-71dbcc3-linux.txt)
improves from 4,600 bytes / 400 allocations to **3,300 bytes / 300 allocations**.
The transaction-lookup allocation stack is gone; all remaining reported
allocations originate in `rtp_config`. All 100 requests return the expected
404. No invalid-access ASan or UBSan error is reported.

The isolated [string-array replacement fixture](../bench/issue76_array_replacement_test.mko)
still passes its assertions but leaks **4,100 bytes / 300 allocations**
([report](../bench/results/array-replacement-71dbcc3-linux.txt)). Its count is
independent of the full probe, not additive. Exact compiler cleanup root cause
remains unproven; the fixture provides a small reproduction of the pattern.

The [SIP-tag](../bench/results/sip-tag-71dbcc3-linux.txt),
[named-slice](../bench/results/named-slice-71dbcc3-linux.txt),
[expanded crypto/retained-string](../bench/results/ownership-71dbcc3-linux.txt),
and [upstream #75](../bench/results/upstream-issue75-71dbcc3-linux.txt)
diagnostics pass Linux ASan/UBSan/LSan. All 55 local functional test files and
both local and [Linux ownership gates](../bench/results/ownership-gate-71dbcc3-linux.txt)
pass. The existing gates do not cover the remaining array leak.

The exact compiler commit and matching runtime were built using the flags
below. Fixture isolation and the application scratch snapshot are unchanged.
The compiler pin remains `caa7f36`; no production deployment or restart was
performed. Kluster remains unavailable. No OpenSIPS comparison was run.

## Follow-up: `2c55486`

Commit `2c5548638970c9dad333fec89e8ed74a4424f43e` fixes the original
[string-array replacement regression](../bench/results/array-replacement-2c55486-linux.txt).
The same [100-rejected-INVITE probe](../bench/results/proxy-allocations-2c55486-linux.txt)
improves from 3,300 bytes / 300 allocations to **500 bytes / 100 allocations**.
All requests return the expected 404; no invalid-access ASan or UBSan error
is reported. Remaining allocations originate in `mako_int_to_string` in RTP
configuration (495 bytes across 99 requests, plus 5 bytes on the first).

A [numeric-string variant](../bench/issue76_array_numeric_replacement_test.mko)
of the array regression uses `cfg[2] = string(2223)` instead of a literal.
Its assertions pass, but it leaks **500 bytes / 100 allocations** under Linux
LSan ([report](../bench/results/array-numeric-replacement-2c55486-linux.txt)).
The new cleanup condition requires `_rc` and a shared reference count;
`mako_int_to_string` produces a raw allocation with `_rc == 0`, which that
condition skips. This identifies the remaining reproduction and likely
cleanup gap; a correction must still preserve moved/borrowed elements.
The focused and full-probe counts are separate measurements, not additive.

The [SIP-tag](../bench/results/sip-tag-2c55486-linux.txt),
[named-slice](../bench/results/named-slice-2c55486-linux.txt),
[expanded crypto/retained-string](../bench/results/ownership-2c55486-linux.txt),
and [upstream #75](../bench/results/upstream-issue75-2c55486-linux.txt)
regressions remain clean. All 55 functional test files and local and
[Linux ownership gates](../bench/results/ownership-gate-2c55486-linux.txt) pass.

Exact compiler/runtime source, build flags, fixture isolation, and application
snapshot follow the preceding procedure. The compiler pin remains `caa7f36`;
no production deployment/restart or OpenSIPS comparison was performed.
Kluster remains unavailable.

## Follow-up: `249a616`

Commit `249a6168338d290966e9248257cd752cf03bd681` closes the numeric-string
array-replacement leak. All isolated Linux ASan/UBSan/LSan diagnostics pass:

- [Numeric-string replacement](../bench/results/array-numeric-replacement-249a616-linux.txt).
- [Numeric-string append wrapper](../bench/results/array-numeric-append-249a616-linux.txt), added to check that moved elements remain valid.
- [Literal-string array replacement](../bench/results/array-replacement-249a616-linux.txt).
- [SIP-tag temporary](../bench/results/sip-tag-249a616-linux.txt).
- [Named slice](../bench/results/named-slice-249a616-linux.txt).
- [Expanded crypto/retained-string](../bench/results/ownership-249a616-linux.txt).
- [Upstream #75](../bench/results/upstream-issue75-249a616-linux.txt).

The same [100-rejected-INVITE probe](../bench/results/proxy-allocations-249a616-linux.txt)
exits **0 with no reported leaks**, down from 500 bytes / 100 allocations.
All 100 responses are 404. No invalid-access ASan or UBSan error is reported.
This harness retains process-lifetime map roots, so a clean result does not
prove whole-server memory bounds or cover successful-call workloads.

All 55 functional test files and local and
[Linux ownership gates](../bench/results/ownership-gate-249a616-linux.txt) pass.
The accepted [combined regression fixture](../tests/compiler_ownership_test.mko)
covers all seven Madis cases above (the expanded fixture contributes two tests).
It passes [Linux sanitizers](../bench/results/compiler-ownership-249a616-linux.txt)
and the local built-in checker reports 2,110 allocations with zero leaks.
The installed source-build capability probe and integrated fixture were also
rechecked after the update. Linux LSan remains necessary for raw allocations.

CI, release, and IMS smoke now pin this exact revision with its matching runtime.
Installer diagnostics and current documentation identify the new pin. The
compiler build flags below, isolation procedure, and application snapshot are
unchanged. No production deployment/restart or OpenSIPS comparison was run.
Kluster was unavailable.

## Build method (all follow-ups)

Both candidate compilers use matching source/runtime and cached release
dependencies. The final compiler crate is built with reduced Rust optimization:
`cargo rustc --release --locked --offline --bin makori -- -C opt-level=0`.
macOS retains thin LTO to consume its cached dependencies; Linux additionally
uses `-C lto=off`. Generated Madis C still uses its normal release `-O3` flags.
The temporary macOS attempt to disable LTO failed because Apple's linker
could not read the cached Rust LLVM bitcode; retaining LTO resolved that build.

Kluster was unavailable. This evaluation did not deploy or restart production
and does not establish an OpenSIPS performance win.
