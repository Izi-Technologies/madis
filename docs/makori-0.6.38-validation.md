# Makori 0.6.38 validation

CI, release, and IMS smoke workflows pin release commit
`694b8743b552a7c24ec6341ff57514fdb570beb5`, with the runtime from the same
checkout. Source build guards require Makori 0.6.38 or later. All application
builds and contract tests continue to use the C backend.

This upgrade brings reference-counted strings, string/array/channel ownership
fixes, and an 8 MB default worker-pool stack. Regenerate C and rebuild both
applications with a matching compiler/runtime pair; do not reuse C generated
by 0.6.34 with the 0.6.38 runtime.

## Validation

The initial upgrade was validated on macOS arm64 using the published `v0.6.38` release archive,
verified against its SHA-256 checksum. The packaged `mako_rt.h` and
`mako_stdlib.h` match the pinned source revision. The locally installed
compiler also reports 0.6.38 but includes later changes, so it was not used
for these results. The framing update was also validated on Linux x86_64 with
0.6.38 installed from the official release installer.

| Check | Result |
| --- | --- |
| Proxy and admin `check --no-incremental` | Pass |
| Proxy and admin lint | Pass; three existing unused-variable warnings in proxy |
| Complete C-backend contract suite | 50 test files passed, zero failures on macOS and Linux |
| Ownership, framing, stream transport, HEP, and MAF ASan/UBSan suites | All five passed on Linux; both bounded fixtures also passed LeakSanitizer |
| Release native C builds | Proxy/admin pass on macOS; updated proxy also passes on Linux |
| SIGPIPE process checks, proxy and admin | Both remained healthy |
| Minimum-version guard | Rejects 0.6.34, 0.6.37 and unknown; accepts 0.6.38, 0.6.39, 0.7.0 and 1.0.0 |
| Installer shell syntax, privacy scan, diff whitespace | Pass |

The full `scripts/ci.sh` aggregate (including SDK and adapter checks) was not
run locally. CI retains that gate together with Linux ownership sanitizers.
The built-in RC leak detector was added after the release tag and is not a
requirement of this pin.

## Application use of RC strings

Stream reassembly now returns the incoming chunk directly when the buffer is
empty, after checking the 1 MiB limit. Framing a buffer containing exactly one
complete SIP message retains that string instead of creating a full-length
substring. Generated C uses `mako_str_clone` for retention: existing RC strings
share storage; plain runtime strings may still require promotion on first clone.

Peer-host extraction returns its array element directly, relying on the fixed
return ownership handling. IMS flow refresh retains field aliases instead of
forcing copies with empty-string concatenation. Dispatch substring copies remain
necessary because borrowed slice views cannot escape their source block.

Regression coverage includes repeated message retention across input replacement,
same-storage string reassignment, alias isolation, exact-limit and oversized first
reads, and 100 IMS flow refreshes preserving all four identity/routing fields.
The stream and IMS flow suites pass ASan/UBSan with the checksum-verified published
0.6.38 compiler/runtime pair on macOS arm64. These changes reduce explicit copy
operations; no end-to-end throughput improvement has been measured.

The subsequent framing update replaces the result array with an owning
`StreamFrame` value and migrates all transport consumers to named fields. It
adds binary-body, all-fragment-boundary, incomplete-tail, retained-frame, and
bounded Linux leak regressions. Both bounded ownership fixtures pass Linux
ASan/UBSan/LeakSanitizer with the published 0.6.38 compiler installed using the
release installer. See [framing implementation and measurements](stream-framing-0.6.38.md)
for allocation, throughput, latency, RSS results, and the self-reassignment
workaround found by the Linux gate.

## Remaining production validation

Sustained SIP traffic/RSS, end-to-end throughput comparisons, external SIP/IMS
interoperability, and production deployment remain separate checks. The bounded
Linux leak gate does not establish leak freedom for the entire live service.
