# Madis roadmap to v1.0

This roadmap covers the path from v0.7.0 (feature-complete) to v1.0
(production-proven). The code is implemented; what remains is evidence,
resilience, scale, and compliance.

## Current state: v0.7.0

### What's built

- **SIP core**: RFC 3261 stateful proxy, UDP/TCP/TLS/WSS (RFC 7118),
  transactions (16K rings), dialogs, forks, retransmissions, SO_REUSEPORT
  multi-worker, PROXY protocol v1.
- **RFC extensions**: 3262 (PRACK), 3263 (DNS SRV/NAPTR), 3265/6665
  (SUBSCRIBE/NOTIFY), 3325 (P-Asserted-Identity), 4028 (session timers),
  5626 (outbound), 5923 (TLS reuse), 7118 (WebSocket), 7433 (UUI),
  8224-8226 (STIR/SHAKEN).
- **IMS**: Full Cx/Sh Diameter, AKA auth, iFC, RTR/PPR push, IPsec SA
  export, Rx, P-/I-/S-CSCF roles, charging vectors, subscriber lifecycle,
  emergency call handling (TS 23.167), P-Access-Network-Info (TS 24.229).
- **MAF**: 59 HTTP endpoints, 5 SDKs (Python/Go/TypeScript/JavaScript/Erlang),
  WebSocket streaming, full platform control (calls, routing, gateways, DIDs,
  dispatch, presence, CDR, security, config, charging, RTPEngine, B2BUA,
  STIR/SHAKEN external signing, headers, billing, events).
- **Performance**: 10ms poll, 16K transaction rings, zero-alloc header
  scanning, cached routing/dispatch/gateway lookups, 50ms RTPEngine evloop.
- **Security**: adversarially hardened across 4 audit passes — payload
  injection, cache collision, SDP leak, SSRF, SQL LIKE injection, HS256
  downgrade, CRLF injection, tenant scoping, config allowlist, bounded rings.
- **Infrastructure**: PostgreSQL, RTPEngine, HEP/Homer, DEB/RPM packages,
  GitHub Actions CI/CD, clustering, graceful shutdown.

### Test coverage

- 45 Mako unit tests
- 56 Python MAF SDK contract tests
- 39 Python unit tests (lab HSS, MMTel, media)
- Containerized IMS smoke (P-/I-/S-CSCF chain, Cx/AKA, SDP/RTP, ACK/BYE)

---

## v0.8.0 — Interoperability

Prove it works with real peers. Every item requires captured traces with
declared versions, hardware, and network topology.

### External peer validation

- [ ] Open5GS HSS: full Cx UAR/SAR/MAR/LIR with real subscriber data, AUTS
  SQN recovery with a real USIM.
- [ ] SIPp: sustained load (10K+ CPS), fork/CANCEL race, retransmit storm,
  malformed input fuzzing, timer boundary tests.
- [ ] RTPEngine: real media plane with packet captures, NAT traversal,
  ICE/DTLS-SRTP, codec transcoding, DTMF relay.
- [ ] SIP.js/JsSIP: browser-to-SIP call through WSS with WebRTC media
  bridging, subprotocol negotiation, response routing verification.
- [ ] Real SIP phones (Ooma/Grandstream/Yealink): registration, call, hold,
  transfer, BLF.
- [ ] TransNexus ClearIP: end-to-end external STIR/SHAKEN signing and
  verification with production STI certificates.
- [ ] Asterisk/FreeSWITCH: AS/B2BUA interop as iFC targets, media anchoring.
- [ ] Kamailio/OpenSIPS: peer interoperability comparison, routing behavior.
- [ ] PJSIP/oSIP: client-library interop for PRACK, 100rel, session timers.

### NAT and transport evidence

- [ ] NAT rebinding and MT same-flow packet captures across UDP, TCP, TLS,
  and WSS.
- [ ] Contact rewrite verification with multiple NAT scenarios (CGNAT,
  symmetric NAT, hairpin).
- [ ] IPv6 dual-stack registration and call establishment.

### IMS interop

- [ ] Real IMS UE (VoLTE/VoWiFi) registration through P-/I-/S-CSCF chain.
- [ ] End-to-end SQN/AUTS evidence with a real HSS and IMS UE.
- [ ] Real TAS/MMTel interoperability, supplementary-service coverage.
- [ ] Kernel IPsec/xfrm or strongSwan installation and packet-level evidence.

---

## v0.8.5 — Resilience

Prove it recovers from failures. Each drill must be documented with
reproduction steps and recovery times.

### Failure drills

- [ ] PostgreSQL primary failure: replica promotes, proxy reconnects, no call
  loss for in-progress dialogs.
- [ ] Worker crash during active dialog: restart hydrates registrations,
  cluster BYE forwarding works for orphaned calls.
- [ ] Network partition: split-brain detection, stale-node marking,
  registration reconciliation after heal.
- [ ] Rolling upgrade: zero-downtime deploy with graceful drain, new workers
  accept while old workers finish in-flight transactions.
- [ ] RTPEngine node failure: media failover to backup node, no audio gap
  for active calls.
- [ ] HSS/Diameter peer timeout: fail-closed behavior, bounded backoff,
  recovery without manual intervention.

### Stability

- [ ] 72-hour sustained load soak test (5K CPS) with no memory leak, FD
  leak, or ring eviction of active state.
- [ ] Registration churn: 100K registrations cycling with 60s expiry for 24
  hours, verify no stale bindings routed.
- [ ] Long-duration calls: 1000 concurrent calls held for 24 hours, verify
  no timer drift or dialog eviction.

---

## v0.9.0 — Scale

Measured numbers on declared hardware. All benchmarks must be reproducible
with published methodology.

### CPS and throughput

- [ ] CPS benchmark: target 15K+ on 8-core/16GB, compare against OpenSIPS
  on identical hardware with identical routing policy.
- [ ] REGISTER throughput: target 20K+ registrations/sec with DB writes.
- [ ] OPTIONS/keepalive: target 50K+ stateless responses/sec.

### Concurrent capacity

- [ ] Active dialogs: target 500K+ with measured RSS per dialog.
- [ ] Active registrations: target 1M+ with measured memory footprint.
- [ ] TCP/TLS/WSS connections: target 100K+ with measured FD and RSS.

### Latency

- [ ] P99 INVITE-to-100 latency under load (target < 5ms).
- [ ] P99 REGISTER-to-200 latency under load (target < 10ms).
- [ ] Database write latency impact on CPS at 50th/95th/99th percentile.

### Publish

- [ ] Benchmark scripts in `bench/` with declared hardware, OS, kernel
  parameters, and PostgreSQL configuration.
- [ ] Comparison methodology document against OpenSIPS.

---

## v0.9.5 — Compliance and security

Independent assessment and formal verification.

### RFC compliance

- [ ] Automated SIP message fuzzer against all supported RFCs.
- [ ] Full RFC 3261 ABNF coverage test (request-line, headers, body).
- [ ] 100rel/PRACK interoperability traces with strict UA stacks.
- [ ] Session-timer interoperability traces with endpoint refreshers.
- [ ] GRUU (RFC 5627) if carrier deployments require it.
- [ ] Reg-event (RFC 3680) and dialog event (RFC 4235) packages if AS
  deployments require them.

### Security

- [ ] Independent penetration test by a third-party security firm.
- [ ] OWASP SIP security checklist pass.
- [ ] TLS 1.3 cipher suite hardening, certificate chain validation testing.
- [ ] STIR/SHAKEN STI-GA compliance testing with real STI certificates.
- [ ] MAF tenant isolation verification under adversarial conditions.
- [ ] Rate-limit and ban-bypass testing under distributed attack.

### Certification

- [ ] SRTP/SDES/DTLS-SRTP key handling audit.
- [ ] SRTP media encryption verification with packet captures.
- [ ] Emergency call routing compliance with local regulatory requirements.

---

## v1.0.0 — Production

All of the above, proven in production.

### Hard requirements

- [ ] At least 3 real carrier/operator deployments running for 30+ days.
- [ ] Published CPS and concurrent-call numbers with reproducible methodology.
- [ ] Independent security assessment completed and findings resolved.
- [ ] Open5GS or equivalent HSS interop proven with traces.
- [ ] Real UE (VoLTE/VoWiFi) registration and call proven with traces.
- [ ] Real RTPEngine media plane with SRTP proven with packet captures.
- [ ] Browser WebRTC call through SIP.js proven end-to-end.
- [ ] PostgreSQL failover and rolling upgrade proven with zero call loss.
- [ ] 72-hour stability soak at sustained load completed.
- [ ] External STIR/SHAKEN vendor integration proven (TransNexus or equivalent).
- [ ] MAF SDK used by at least one real application in production.
- [ ] Complete documentation reviewed by someone who didn't write it.

### Version timeline

| Version | Focus | Gate |
|---------|-------|------|
| **v0.7.0** | Feature complete | All features implemented, 140 tests pass ✅ |
| **v0.8.0** | Interoperability | Works with real peers, captured traces |
| **v0.8.5** | Resilience | Recovers from failures, documented drills |
| **v0.9.0** | Scale | Beats OpenSIPS on measured benchmarks |
| **v0.9.5** | Compliance | Independent security assessment passes |
| **v1.0.0** | Production | All above, running in carrier deployments |

---

## Implemented IMS phases

### L1 — Durable registration and subscriber state

- [x] Durable IMPI/IMPU, Contact, Path, Service-Route, S-CSCF, auth state.
- [x] Restart hydration and durable expiry cleanup.
- [x] Associated public identities and implicit registration-set membership.
- [x] Network-initiated deregistration through RTR/PPR.
- [x] Optional HSS re-SAR reconciliation after restart.
- [x] S-CSCF reassignment and fail-closed server mismatch.
- [x] Cx peer selection, realm pinning, bounded backoff, overload limits.
- [x] Deterministic Diameter-to-SIP error mapping.

### L3 — P-CSCF flow and access-edge behavior

- [x] Opaque flow token minting and dynamic Path insertion.
- [x] Route-token and stable-connection flow refresh.
- [x] Source-port-aware flow identity and stream-close cleanup.
- [x] Bounded outbound extension handling.
- [x] MT routing through stored Path when a valid flow is present.
- [x] Optional CK/IK and SA JSON generation for external IPsec enforcer.

### L4 — iFC and application services

- [x] Bounded structured iFC conditions, priority ordering, session cases.
- [x] Originating and terminating AS target selection.
- [x] Optional sequential third-party REGISTER.
- [x] Lab MMTel/TAS adapter for barring and call forwarding.

### L5 — Media control

- [x] RTPEngine offer/answer/delete with evloop-based timeout.
- [x] Bounded multi-node selection and control failover.
- [x] Profile and flag validation/pass-through.
- [x] WebRTC auto-detection (ICE/DTLS/SAVPF) with bridge flags.
- [x] MAF RTPEngine control with per-call flags.
- [x] Cleanup on BYE/CANCEL and early-media bookkeeping.

### L6 — SIP session behavior

- [x] Session-Expires and Min-SE validation.
- [x] Dialog timer binding and negotiated response headers.
- [x] Glare rejection for concurrent re-INVITE/UPDATE.
- [x] PRACK/early-dialog bookkeeping with 100rel in Supported.
- [x] Record-Route WSS→ws normalization (RFC 7118).
- [x] NOTIFY after SUBSCRIBE 200 OK (RFC 6665).
- [x] SUBSCRIBE 200 OK with Contact header (RFC 6665).
- [x] 423 Interval Too Brief with To-tag (RFC 3261).

### L7 — Clustering and recovery

- [x] PostgreSQL-backed lifecycle state with node ownership.
- [x] Affinity and routing guidance for all transports.
- [x] Graceful drain and restart hydration.
- [x] Fail-closed stale remote-registration handling.

### L8 — Charging, emergency, and carrier boundaries

- [x] Ro/charging adapter boundary.
- [x] P-Charging-Vector generation and terminating validation.
- [x] Rx AAR/STR builders and fail-closed authorization gate.
- [x] MAF charging authorization/denial per call.
- [x] Emergency call detection and E-CSCF routing (TS 23.167).
- [x] P-Access-Network-Info insertion (TS 24.229 §5.2.6.3).

### MAF — Full platform control

- [x] 59 HTTP endpoints with tenant-scoped authentication.
- [x] Call lifecycle (13 operations), media (3), identity (1), inspection (2).
- [x] Infrastructure CRUD (22): routing, dialplans, gateways, DIDs, dispatch,
  ip-auth, access-control, header-rules, ANI groups.
- [x] Observability (12): registrations, presence, CDR, active calls, bans,
  security events, billing events, cluster, config.
- [x] Events (4): replayable HTTP, custom app.*, WebSocket, streaming SDKs.
- [x] External STIR/SHAKEN signing (TransNexus, Neustar, Iconectiv).
- [x] 56 SDK contract tests, all passing.

---

## Local contract coverage

- `tests/ims_cx_push_test.mko`: RTR/PPR, mTLS client-CN, listener bounds.
- `tests/ims_flow_test.mko`: flow refresh, expiry, token validation.
- `tests/ims_ipsec_test.mko`: CK/IK export, SA JSON, SPI/port validation.
- `tests/ims_rx_test.mko`: AAR/STR, session correlation, fail-closed.
- `tests/ims_session_timer_test.mko`: validation, negotiation, glare.
- `tests/maf_contract_test.mko`: all MAF routes, auth, idempotency, SDP.
- `tests/maf_improvements_test.mko`: adaptive poll, transport, events.
- `tests/maf_headers_test.mko`: header policy, protected-header rejection.
- `tests/capacity_test.mko`: call state capacity clamping.
- `tests/ops_test.mko`: admin token, runtime reload.
- `sdk/maf/tests/`: 56 SDK-to-OpenAPI contract tests.

Local tests verify contracts only. Real peer, media, failure, scale, and
security evidence is the gate for v0.8.0 through v1.0.0.

## Explicit non-claims

Madis v0.7.0 does not claim: full RFC ABNF coverage, complete RFC 3262
endpoint behavior, GRUU (RFC 5627), complete RFC 4028 endpoint ownership,
a full HSS/UDM/TAS/PCRF/PCF platform, independent security certification,
carrier-scale failover, or a published capacity number. Those require the
external evidence listed in the v0.8.0–v1.0.0 phases above.

See also [`configuration.md`](configuration.md),
[`clustering.md`](clustering.md), [`testing.md`](testing.md),
[`interop-open5gs.md`](interop-open5gs.md), and the
[IMS API contracts](../api/ims-diameter.md).
