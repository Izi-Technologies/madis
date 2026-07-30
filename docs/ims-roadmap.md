# Madis IMS roadmap

This roadmap describes the bounded IMS voice profile implemented on top of
Madis’s SIP proxy/registrar foundation. It is a delivery plan and capability
boundary; it is not a claim that Madis is a complete IMS core or a certified
carrier platform.

The first target is a reproducible lab profile with a durable registration and
authentication lifecycle. VoLTE/VoWiFi deployment, roaming, emergency
calling, RCS, PSTN interconnect, and carrier-scale operations remain separate
profiles with their own acceptance evidence.

## Evidence policy

A phase is complete only when both of these are true:

1. the behavior is implemented and bounded in the repository; and
2. the required acceptance evidence exists for the intended deployment.

The checklists below use these labels:

- **Implemented** — code exists and is covered by local contract tests.
- **Wired** — the production request, response, worker, or lifecycle path
  invokes the implementation.
- **External evidence pending** — the boundary is ready, but real peer,
  media, failure, or scale evidence has not been collected in this repository.

## Current status

### Implemented and wired

- SIP over UDP, TCP, TLS, WS, and WSS.
- Stateful transactions, retransmissions, dialogs, CANCEL/ACK/BYE handling,
  parallel forking, dispatch groups, dialplans, gateways, routing policy, CDRs,
  and durable billing-event delivery.
- PostgreSQL-backed registrations and lifecycle hydration after worker restart.
- Explicit P-/I-/S-CSCF role boundaries for REGISTER and initial INVITE.
- Cx UAR/SAR/LIR/MAR/Server-Assignment contracts, peer failover controls,
  realm-pinned selection, backoff, and bounded in-flight work.
- AKA consume-once vectors, expiry, multi-vector pools, and AUTS resync.
- Associated public identities, implicit registration sets, network-initiated
  RTR/PPR deregistration, S-CSCF reassignment, Path, and Service-Route.
- Dynamic P-CSCF flow tokens: REGISTER minting, Route/connection refresh,
  source-port binding, and cleanup when TCP/TLS/WS associations close.
- RFC 5626-shaped `Require`/`Supported: outbound` bounds. Kernel IPsec is not
  installed by Madis; optional CK/IK and bounded SA JSON remain an external
  enforcer contract.
- Structured iFC target selection, originating/terminating session cases, and
  optional third-party REGISTER. The lab MMTel/TAS adapter is in `lab/`.
- RTPEngine control for offer/answer/delete, bounded node selection/failover,
  and profile/flag pass-through. RTP and media security remain external.
- Session-timer request validation, dialog binding, and negotiated
  `Session-Expires` response headers. Endpoint refresher generation is not
  owned by the SIP worker.
- PRACK/early-dialog bookkeeping, glare rejection, identity privacy, PAI,
  P-Charging-Vector propagation, Rx authorization hooks, and existing Ro
  charging boundaries.
- Graceful drain, bounded caches, defensive SIP parsing, MAF, the management
  API, and the separate WebUI/admin process.

### Evidence currently available

- Mako native source check passes with the repository’s configured Mako
  runtime.
- `scripts/test.sh tests` is the local native contract-test gate.
- `scripts/lab-smoke.sh unit` runs the Mako, lab, and media unit suites and
  fails on any failing suite.
- `docker compose -f docker-compose.ims-lab.yml config --quiet` validates the
  IMS lab configuration.
- The lab adapters provide deterministic Cx/AKA and bounded media test
  doubles. They are not Open5GS, a commercial UE, or a production RTPEngine.

### Not yet demonstrated

- A clean-machine build and complete CI run against every supported Mako
  release/runtime combination.
- Interoperability with a real IMS UE, Open5GS HSS, SIPp/PJSIP, Kamailio or
  OpenSIPS, Asterisk or FreeSWITCH, and a real RTPEngine media plane.
- NAT rebinding and MT same-flow packet captures across UDP, TCP, TLS, WS, and
  WSS.
- Kernel IPsec/xfrm or strongSwan installation and packet-level IPsec evidence
  for exported SA material.
- PostgreSQL failure, worker restart during active dialogs, network partition,
  rolling upgrade, and registration recovery drills.
- Repeatable CPS, concurrent-dialog, RSS, file-descriptor, database-latency,
  retransmission, and media-capacity measurements.
- An independent SIP-security assessment or carrier interoperability claim.

## Delivery phases

### L1 — Durable registration and subscriber state

- [x] Durable IMPI/IMPU, Contact, Path, Service-Route, S-CSCF, auth state, and
  expiry in `ims_registrations`.
- [x] Restart hydration and durable expiry cleanup.
- [x] Associated public identities and implicit registration-set membership.
- [x] Network-initiated deregistration through RTR/PPR and local lifecycle
  helpers.
- [x] Optional HSS re-SAR reconciliation after restart.
- [x] S-CSCF reassignment and fail-closed handling of server mismatch.
- [x] Cx peer selection, realm pinning, bounded backoff, and overload limits.
- [x] Deterministic Diameter-to-SIP error mapping.
- [ ] End-to-end SQN/AUTS evidence with a real HSS and IMS UE.

### L3 — P-CSCF flow and access-edge behavior

- [x] Opaque flow token minting and dynamic Path insertion.
- [x] Route-token and stable-connection flow refresh.
- [x] Source-port-aware flow identity and stream-close cleanup.
- [x] Bounded outbound extension handling.
- [x] MT routing through stored Path when a valid flow is present.
- [x] Optional CK/IK and SA JSON generation plus a bearer-protected local
  worker-admin retrieval route for an external access-security enforcer; no
  kernel SA installation.
- [ ] UE-driven NAT rebinding, keepalive expiry, and same-flow MT packet
  evidence.
- [ ] External strongSwan/xfrm installation and packet-level IPsec evidence.

### L4 — iFC and application services

- [x] Bounded structured iFC conditions, priority ordering, and session cases.
- [x] Originating and terminating AS target selection.
- [x] Optional sequential third-party REGISTER.
- [x] Lab MMTel/TAS adapter for barring and call forwarding examples.
- [ ] Real TAS/MMTel interoperability, supplementary-service coverage, and
  failure behavior under AS timeout/restart.

### L5 — Media control

- [x] RTPEngine offer/answer/delete control path.
- [x] Bounded multi-node selection and control failover.
- [x] Profile and flag validation/pass-through for external media policy.
- [x] Cleanup on BYE/CANCEL and early-media bookkeeping.
- [ ] Real RTPEngine packet captures and media success matrix.
- [ ] ICE, DTLS-SRTP, codec, DTMF, recording, and media failover evidence.

### L6 — SIP session behavior

- [x] Request-side `Session-Expires` and `Min-SE` validation.
- [x] Dialog timer binding and response-side negotiated header insertion.
- [x] Glare rejection for concurrent re-INVITE/UPDATE.
- [x] PRACK/early-dialog and forked response bookkeeping.
- [x] SDP offer/answer control integration.
- [ ] Endpoint refresher scheduling and timeout ownership, if the deployment
  chooses to place that responsibility in a dedicated session service.
- [ ] Real 100rel/PRACK and session-timer interoperability traces.

### L7 — Clustering and recovery

- [x] PostgreSQL-backed lifecycle state with node ownership metadata.
- [x] Affinity and routing guidance for UDP, TCP, TLS, WS, and WSS.
- [x] Graceful drain and restart hydration runbooks.
- [x] Fail-closed stale remote-registration handling.
- [ ] Live restart, partition, database-failover, and rolling-upgrade drills.
- [ ] Capacity and recovery objectives measured on declared hardware.

### L8 — Charging and carrier boundaries

- [x] Existing Ro/charging adapter boundary.
- [x] Originating P-Charging-Vector generation and terminating validation.
- [x] Rx AAR/STR builders and fail-closed authorization gate.
- [ ] Real PCRF/PCF policy evidence and reauthorization behavior.
- [ ] IBCF/SBC, roaming, emergency, PSTN/SIGTRAN, and regulatory profiles.

## MAF integration track

The MADIS Application Fabric (MAF) is the language-neutral application
boundary for JavaScript/TypeScript, Go, Python, and other clients. It uses
versioned HTTP/JSON routes, bearer scopes, tenant isolation, idempotency keys,
optimistic versions, durable command receipts, and replayable events. The
canonical route and schema list lives in [`api/maf.md`](../api/maf.md) and
[`api/maf.openapi.yaml`](../api/maf.openapi.yaml).

- [x] Read-only call/event access and asynchronous command receipts.
- [x] Tenant-scoped create, answer, reject, hangup, bridge, and media command
  boundaries.
- [x] Separate read/write credentials and fail-closed bearer validation.
- [x] Inbound MAF call ownership behind `SIP_MAF_INBOUND_MODE=control`.
- [x] Node-side command polling and bounded SIP synchronization.
- [ ] Production mTLS/reverse-proxy deployment evidence and SDK examples for
  each supported language.
- [ ] Independent abuse testing for token, tenant, idempotency, replay, and
  command-ordering boundaries.

## Interoperability and adversarial test matrix

Every external-evidence run should preserve traces and declare versions,
hardware, network topology, and configuration:

| System | Required evidence |
| --- | --- |
| IMS UE | AKA, REGISTER refresh/expiry, originating/terminating INVITE, CANCEL, BYE |
| Open5GS or another Cx HSS | UAR/SAR/MAR, AUTS, RTR/PPR, timeout/error mapping |
| RTPEngine | Offer/answer/delete, NAT, ICE/DTLS-SRTP policy, packet capture |
| SIPp/PJSIP | Retransmissions, fork, CANCEL race, malformed input, sustained load |
| Kamailio/OpenSIPS | Peer behavior and interoperability comparison |
| PostgreSQL/network | Failure, restart, partition, recovery, and stale-state behavior |
| MAF clients | Auth scope, tenant isolation, idempotency, replay, ordering, backpressure |

Local contract tests are necessary but are not a substitute for this matrix.

## Definition of done for the first lab profile

1. A provisioned subscriber completes IMS AKA registration through the selected
   P-/I-/S-CSCF path.
2. Cx failures map deterministically to SIP responses without stale lifecycle
   state.
3. Two registered subscribers complete an originating and terminating session,
   with stored Path routing when enabled.
4. Worker restart restores durable registration state used for MT routing.
5. Retransmissions, CANCEL races, timeouts, dialog teardown, and drain are
   exercised and captured.
6. Identity/privacy and application boundaries remain enforced.
7. External media control succeeds and tears down without the SIP worker
   owning RTP.
8. MAF, metrics, traces, CDR correlation, configuration, and recovery steps
   are documented and tested.

## Explicit non-claims

Madis does not currently claim full RFC ABNF coverage, complete RFC 3262
endpoint behavior, SIP Outbound/GRUU, complete RFC 4028 endpoint ownership,
complete RFC 3325/RFC 8224 identity handling, a full HSS/UDM/TAS/PCRF/PCF or
charging platform, independent certification, carrier-scale failover, or a
published capacity number. Those claims require the external evidence listed
above.

See also [`configuration.md`](configuration.md), [`clustering.md`](clustering.md),
[`testing.md`](testing.md), [`interop-open5gs.md`](interop-open5gs.md), and the
[IMS API contracts](../api/ims-diameter.md).
