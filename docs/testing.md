# Testing and release checks

All native builds and CI checks must use Mako **0.4.16** and the matching
runtime directory. The compiler version and runtime are a pair; do not use a
0.4.15 binary with the 0.4.16 runtime.

## Fast local check

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

This runs Mako checks and lint, all eight Mako test files, native SIP and
WebUI links, and JSON-schema validation. It is the command used by the GitHub
Actions workflow after it builds the pinned Mako revision.

## Adversarial and wire checks

```sh
MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/rfc_gate.sh
```

The RFC gate covers the local unit suites, UDP/TCP/TLS/WSS transport framing,
outbound WSS signaling, trusted TLS and IPv6, deterministic loss/delay/
duplicate/reorder cases, auth vectors, a generated-style ABNF corpus, and
seeded SIP fuzzing. `RFC_FULL=1` adds the longer sanitizer/soak work when the
host has the required external tools.

For memory-safety checks alone:

```sh
MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/sanitizer.sh
```

This builds with AddressSanitizer and UndefinedBehaviorSanitizer, then runs
the transport, WSS, TLS/IPv6, fault, and fuzz matrices. Keep the sanitizer
gate enabled for changes to parser, transport, transaction, admin, or native
bridge code.

## Focused tests

| Test | Focus |
| --- | --- |
| `tests/adversarial_test.mko` | Framing, malformed headers, injection, limits, response status. |
| `tests/auth_test.mko` | Digest parameters, qop, SHA-256, `-sess`, bounded attacker caches. |
| `tests/carrier_contract_test.mko` | Billing identity/escaping and RFC 8506 request contracts. |
| `tests/diameter_codec_test.mko` | Diameter headers, AVPs, grouping, malformed input, Cx/Sh correlation. |
| `tests/proxy_state_test.mko` | Registration, transactions, forks, ACK/CANCEL/BYE, routes, limits. |
| `tests/rfc3261_abnf_test.mko` | Compact headers, quoted names, continuation, Via, Proxy-Require. |
| `tests/rfc3263_test.mko` | NAPTR/SRV ordering, transport selection, IPv6 targets and ports. |
| `tests/admin_http_test.mko` | HTTP framing, cookie boundaries, form decoding, Origin checks. |

These tests are intentionally independent of a production database and mostly
exercise deterministic behavior. Wire tests use separate local processes and
temporary certificates. They do not certify every external SIP, WebRTC,
Diameter, IMS, or SS7 implementation.

## Benchmarking

The SIPp harness reports completed dialog rate, failures, latency buckets, CPS,
and concurrency. Use identical host, CPU affinity, SIPp scenario, transport,
database mode, routing data, and worker settings when comparing Kamailio or
another proxy. Run the generator on a separate machine when possible.

```sh
RATE=100 CALLS=1000 CONCURRENCY=200 WORKERS=1 ./bench/benchmark.sh
```

Sweep rates and concurrency until failures or latency become unacceptable.
Report p95/p99 setup latency, loss, retransmissions, CPU, RSS, file descriptors,
and database load along with CPS. A high generator rate is not a successful
result if calls fail or the generator drops packets. The repository contains
historical host-specific numbers, not a capacity guarantee.

## Release checklist

- [ ] `git diff --check` is clean.
- [ ] Mako 0.4.16 native CI passes.
- [ ] RFC gate passes with the exact runtime.
- [ ] Sanitizer and fuzz gates pass for parser/transport/state changes.
- [ ] Documentation and schemas match the deployed configuration.
- [ ] TLS/CA, bearer tokens, database permissions, firewall, and backups are
      reviewed for the target environment.
- [ ] A real OPTIONS/REGISTER and one representative INVITE path work in a
      staging environment.
- [ ] External SIP, Diameter/IMS, media, and SS7 interop checks are recorded
      separately from local test results.
