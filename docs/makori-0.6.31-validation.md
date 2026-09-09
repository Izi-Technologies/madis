# Makori 0.6.31 validation

The compiler pin is `8d6f2b68afb7ea0f9311ce5f8c5f08cd73901ccf` (0.6.31).
Validation used local commit `9437f3433de941e745d14bda56eab7637f3a4c50`,
whose complete Git tree is identical to the pinned release commit:
`44025a73e307e429f19253bea68c4b022626d26f`. Compiler and runtime came from
the same checkout; all application builds used the C backend.

## Results

| Check | Result |
| --- | --- |
| Linux arm64 ownership fixture, ASan + UBSan + LeakSanitizer | Both tests pass, zero reported leaks, exit 0 |
| Linux arm64 full ownership script | Pass, including stream, HEP and MAF suites |
| Linux arm64 complete test suite | 46 test files pass, zero failures |
| Returned string-slice regression | Pass on Linux arm64 and macOS arm64 with ASan/UBSan |
| macOS arm64 proxy and admin C builds | Pass |
| Actual proxy/admin processes after SIGPIPE | Both remain healthy |
| Linux x86_64 ownership sanitizer gate | Pass, zero reported leaks in the bounded fixture |
| Linux x86_64 complete test suite | 46 test files pass, zero failures |
| Linux x86_64 proxy/admin builds and SIGPIPE check | Pass; both remain healthy |
| Docker arm64 source build | Pass with matching 0.6.31 compiler/runtime |
| Docker authenticated health, SIGPIPE and SIP OPTIONS | Health passes before/after SIGPIPE; SIP returns 200 OK |

Only the bounded ownership fixture enables Linux leak detection. The other
contract suites retain their documented ASan/UBSan settings. No sanitizer
suppression was added. macOS does not provide the Linux LeakSanitizer check.

The original fixture progressed from 439,430 leaked bytes in 22,203 allocations,
through a returned-slice use-after-free regression, then 120,796 leaked bytes
in 7,202 allocations, to a clean result. Full evidence is attached to
[Mako issue #55](https://github.com/loreste/mako/issues/55#issuecomment-5595169513).

The typed MAF response uses the fixed JSON serializer directly; the 0.6.29
tab/carriage-return workaround is removed. Local build/check scripts require
0.6.31 or later so earlier ownership fixes are not mistaken for this result.

## Remaining validation

These results do not establish stable RSS under sustained SIP traffic.
A repeat traffic soak with post-load idle sampling remains necessary.
The earlier SIGPIPE-fixed 0.6.29 soak failed with SIPp exit 1;
peak and final sampled RSS were 2,578,956 KiB over 361 resource samples.
That failed baseline is not a successful throughput measurement and has not
been repeated with 0.6.31. See the historical
[0.6.29 report](makori-0.6.29-validation.md).
