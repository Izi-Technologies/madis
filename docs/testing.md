# Testing and release checks

Madis builds and tests with Mako **0.4.16** and a matching runtime directory. Do not mix a different compiler/runtime pair with generated C.

## Local CI

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

The CI script runs:

- Mako syntax checks and lint for `main.mko` and `admin/main.mko`.
- All repository Mako test files.
- Native SIP worker and WebUI links, including the `madis_memory.c` bridge.
- JSON-schema parsing, shell syntax validation, and Python SDK compilation.

The checks are deterministic contract and regression tests. They do not establish interoperability with every SIP, WebRTC, Diameter, IMS, or SS7 implementation.

## Focused tests

| Test | Coverage |
| --- | --- |
| `tests/admin_http_test.mko` | HTTP framing, cookie boundaries, form decoding, and Origin checks. |
| `tests/adversarial_test.mko` | Malformed headers, framing, injection, limits, status handling, and SIP URI validation. |
| `tests/app_gateway_test.mko` | Signed application/module commands, header boundaries, SQL-shaped data, and module allowlists. |
| `tests/auth_test.mko` | Digest parameters, qop, MD5/SHA-256, `-sess`, and bounded attacker caches. |
| `tests/b2bua_test.mko` | Independent B2BUA legs, dialog translation, cleanup, and header safety. |
| `tests/carrier_contract_test.mko` | Billing identity/escaping, control API routes, validation, and resource allowlists. |
| `tests/diameter_codec_test.mko` | Diameter headers, AVPs, grouping, malformed input, Cx/Sh correlation, and credit-control fields. |
| `tests/proxy_state_test.mko` | Registration, transactions, forks, ACK/CANCEL/BYE, routes, and state limits. |
| `tests/rfc3261_abnf_test.mko` | Compact headers, quoted values, continuation, Via grammar, and Proxy-Require. |
| `tests/rfc3263_test.mko` | NAPTR/SRV ordering, transport selection, IPv6 targets, and port validation. |

## Protocol and load gates

The optional gates exercise deployment-dependent behavior beyond the unit/contract tests:

```sh
MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/rfc_gate.sh

MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/sanitizer.sh
```

The RFC gate covers selected UDP/TCP/TLS/WSS, IPv6, loss/delay/duplicate/reorder, ABNF, and transport behavior. The sanitizer gate builds AddressSanitizer/UndefinedBehaviorSanitizer variants and runs transport, WSS, TLS/IPv6, fault, and fuzz matrices where the host supports them.

For CPS measurements:

```sh
RATE=100 CALLS=1000 CONCURRENCY=200 WORKERS=1 \
  ./bench/benchmark.sh
```

Record host CPU, memory, file descriptors, database capacity, network conditions, and exact configuration with every benchmark result. A benchmark result is not a production capacity guarantee.

## Release checklist

- [ ] `scripts/ci.sh` passes with Mako 0.4.16.
- [ ] API schemas and documentation match the deployed configuration and token scopes.
- [ ] TLS certificates, CA bundles, bearer-token rotation, database permissions, firewall rules, and backups are reviewed.
- [ ] A real OPTIONS/REGISTER and representative INVITE path work in staging.
- [ ] Billing event deduplication and acknowledgement recovery have been exercised.
- [ ] Control API read/write separation and revision-conflict handling have been exercised.
- [ ] Application/module timeout, signature, allowlist, and failure-mode behavior has been tested if enabled.
- [ ] External SIP, Diameter/IMS, media, and SS7 interoperability checks are recorded separately.
- [ ] Upgrade and database restore procedures have been rehearsed.
