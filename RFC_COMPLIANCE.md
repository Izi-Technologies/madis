# SIP RFC compliance status

This is an implementation audit, not an interoperability certification. The
current code implements the RFC 3261 proxy/registrar paths listed
below, but it must not be described as “100% RFC compliant” until the open
items are implemented and exercised against independent SIP stacks.

## Covered core behavior

- RFC 3261 message framing and ingress limits, including rejection of malformed
  header lines and control characters.
- RFC 3261 Max-Forwards: absent values default to 70, invalid values are
  rejected, zero produces 483, and forwarded values are decremented without
  depending on header capitalization or whitespace.
- RFC 3261 Via processing: the proxy adds a new branch, preserves the caller's
  remaining Via value when Via hops share a comma-separated line, and drops a
  response when removing the top Via leaves no upstream hop.
- RFC 3581 `received`/`rport` response routing through the Mako SIP runtime.
- RFC 3261 loose routing for the top Route URI and proxy Record-Route values
  with `;lr`.
- RFC 3261 REGISTER lifecycle: multiple bindings, per-contact expiry,
  configurable Min-Expires/423, wildcard Contact removal, zero-expiry removal,
  URI validation, lazy expiry, and complete live-binding 200 responses.
- RFC 3261 OPTIONS/405 capability responses and Proxy-Require/420 handling.
- Basic server-transaction replay protection for duplicate requests, with
  bounded response-cache storage.
- Client-transaction timing with RFC-default T1/T2, UDP Timer A/E
  retransmissions, Timer B/F timeout handling, configurable proxy Timer C, and
  explicit calling/proceeding/completed state transitions.
- Server-transaction final-response retention with UDP Timer G-style
  retransmission, bounded Timer H/J lifetime, and ACK-driven cleanup.
- Fork response-context handling for lowest-final selection, immediate 6xx
  cancellation, first-2xx loser cancellation, non-2xx INVITE ACK generation,
  branch-race suppression, and same-class 401/407 challenge aggregation.
- RFC 3263 NAPTR service selection, RFC 2782 SRV priority/weight ordering,
  alternate-target failover, 60-second DNS caching, and direct A/AAAA fallback.
  The NAPTR/SRV resolver hooks are built into pinned Mako 0.4.16.
- Bracketed IPv6 SIP target parsing and Digest MD5/SHA-256 verification with
  `auth`, `auth-int`, and `-sess` handling, stale nonce challenges, and
  qop-aware replay keys.
- INVITE dialog forwarding for provisional/final responses and ACK/BYE/CANCEL
  forwarding through the recorded destination and branch where applicable.
- Persistent TCP ingress associations, outbound TCP association reuse with
  response draining, event-loop bounded idle handling, and cleanup of closed
  transaction-to-connection mappings. TLS ingress uses the same bounded event
  loop; outbound TLS has pooled, reusable Mako handles with response draining
  and stale-association cleanup. WSS outbound validates the configured CA,
  performs the RFC 6455 client handshake and masking, and routes registered
  `transport=wss` contacts through Mako's TLS-plus-WebSocket client.
- INVITE 2xx server-transaction state is retained after the final response;
  UDP retransmission is bounded and stops on ACK or expiry, while non-2xx
  INVITE responses use generated ACKs before transaction cleanup.
- Proxy-critical SIP URI, host/port, percent-escape, Call-ID, name-addr,
  required-header, and Content-Length validation, with adversarial coverage
  for malformed IPv6, ports, URI parameters, and header injection.
- Compact-header and quoted display-name coverage, singleton transaction-header
  enforcement, case-sensitive CSeq matching, and Via parameter validation for
  branch, rport, ttl, received, and maddr values.
- Explicit RFC 3261 extension boundaries: unsupported `Proxy-Require` tags now
  produce 420/Unsupported, and OPTIONS no longer advertises outbound, Path, or
  GRUU support that is not implemented.
- Independent-process wire matrix for UDP, pipelined TCP, TLS, WSS, and admin
  readiness/health; trusted CA/SNI/hostname rejection; IPv6 UDP/TCP/TLS; and
  seeded malformed-input fuzzing with ASan/UBSan runs.
- Deterministic real-UDP loss, delay, duplicate, reorder, retransmission, and
  unacknowledged-2xx fault coverage through a separate local UAS process.
- Generated-style process corpus covering 24 valid compact/long, quoted,
  IPv4/IPv6, URI-escaped, and Via-parameter combinations plus 13 invalid
  one-rule mutations.
- A repeatable SIPp soak harness is available at [`bench/soak.sh`](bench/soak.sh).
  Run it for the target source revision and record failures, retransmissions,
  timeouts, CPS, concurrency, CPU, and memory with the result.

The focused regression suite is in
[`tests/proxy_state_test.mko`](tests/proxy_state_test.mko).

The runnable validation commands and their limits are documented in
[`docs/testing.md`](docs/testing.md). This file is a protocol-status summary,
not a certificate of universal compliance.

- Established-dialog re-INVITEs are forwarded through the recorded dialog/Route target before IMS role selection, charging, dial-plan, application, or new-call state work; transaction replay and BYE teardown are covered by focused regression tests.
- Transparent in-dialog PRACK and UPDATE forwarding uses Route state and To-tag-specific fork targets. The proxy validates tracked RSeq/RAck state but does not generate reliable provisional responses or claim endpoint-level conformance.

## Not yet complete

These remain material blockers to a 100% RFC 3261 proxy claim:

- Independent-stack timer interoperability and fork-race validation remains
  open. The local fault matrix now covers loss/reordering, delayed responses,
  retransmissions, and 2xx ACK loss through a separate UAS, but it is not a
  PJSIP/Kamailio/OpenSIPS/Asterisk certification.
- Full SIP URI/header ABNF coverage across every RFC production remains open.
  The ingress validator is strict for the proxy-critical grammar and now has
  a generated-style corpus, but it is not a generated full RFC ABNF parser.
- Full nonce lifecycle interoperability across external digest stacks and
  independent PJSIP/SIPp authentication matrices. MD5/SHA-256 and `auth` /
  `auth-int`/`-sess` code paths are covered by local known-answer tests, but
  not yet by independent credential stacks.
- DNS failure injection and long-duration resource/leak monitoring still need
  external transport fixtures. The local TLS matrix now uses a temporary CA
  with certificate verification enabled, including SNI and hostname rejection.
- WSS outbound now uses bounded persistent associations with idle expiry,
  readiness polling, RFC 6455 control-frame handling, response routing, and
  ACK/BYE reuse. The local fixture proves an INVITE/180/200/ACK/BYE dialog on
  one CA-validated connection, but independent WebRTC/SIP stack coverage and
  WebRTC media conformance remain separate requirements.

The following extension families remain explicitly outside the supported
surface and require implementation plus separate conformance suites before
they can be claimed: RFC 3262 reliable provisional-response generation and
endpoint RSeq/RAck conformance, RFC 3264 (offer/answer),
RFC 3265/RFC 6665 (event packages), RFC 3325/RFC 8224 (identity), RFC 5626
(outbound), and RFC 5923 (SIPS/TLS connection reuse).

## Verification gate

Before claiming compliance, run the focused tests plus independent SIPp,
PJSIP, and at least one TCP/TLS interoperability matrix covering UDP loss,
retransmissions, forked INVITEs, CANCEL races, non-2xx ACKs, 2xx ACK loss,
DNS transport selection, IPv6, authentication qop, PRACK, and registration
expiry/wildcard cases. The reusable local harnesses are
`bench/auth_matrix.py`, `bench/transport_matrix.py`,
`bench/tls_ipv6_matrix.py`, `bench/fault_matrix.py`, `bench/abnf_corpus.py`,
`bench/fuzz_sip.py`,
`bench/sanitizer.sh`, and `bench/soak.sh`. Performance results should be
reported separately from RFC conformance; a high CPS result does not prove
timer or protocol compliance.

References: [RFC 3261](https://www.rfc-editor.org/rfc/rfc3261.html),
[RFC 3581](https://www.rfc-editor.org/rfc/rfc3581/),
[RFC 3263](https://www.rfc-editor.org/rfc/rfc3263.html), and
[RFC 3264](https://www.rfc-editor.org/rfc/rfc3264.html).

For the separate charging and IMS boundaries, see
[`api/diameter.md`](api/diameter.md) and
[`api/ims-diameter.md`](api/ims-diameter.md). RFC 8506 credit-control support
does not make the proxy a complete Diameter, IMS, or billing platform.
