# Madis IMS roadmap

## Purpose and scope

This document defines the implementation path from Madis’s current SIP proxy/registrar foundation to a bounded, testable IMS voice profile. It is a delivery plan and capability boundary, not a claim that Madis is a complete IMS core.

The first target is a lab-capable IMS voice profile. Carrier deployment, VoLTE/VoWiFi, 5G integration, roaming, emergency calling, RCS, and PSTN interconnect require additional profiles and acceptance evidence.

## Current verified foundation

Madis currently provides:

- SIP UDP, TCP, TLS, WS, and WSS transport;
- registration, authentication, transactions, dialogs, routing, dispatch, dialplans, and CDR/outbox behavior;
- PostgreSQL-backed SIP state and an authenticated administration API;
- selected client-side 3GPP Cx and Sh Diameter builders and answer validation;
- optional Cx UAR/SAR authorization and opaque Cx MAR/MAA authentication-vector handling;
- explicit bounded P-/I-/S-CSCF REGISTER and initial-INVITE role routing;
- fail-closed HTTPS subscriber authorization with assigned S-CSCF and bounded service-profile fields;
- registration lifecycle, dialog, transaction, identity/privacy, Path, Service-Route, P-Associated-URI, and target-only iFC boundaries;
- RTPEngine offer/answer/delete control messages with bounded SDP validation;
- deterministic two-subscriber Cx/AKA/session tests and an opt-in local RTPEngine UDP control-path test.

These capabilities are covered by local contract and regression tests. They do not establish interoperability with a real HSS/UDM, IMS UE, RTPEngine, or carrier network.

### Explicit boundaries

- Madis sends bounded RTPEngine control messages; it does not own RTP, ICE, DTLS-SRTP, codecs, recording, or media policy.
- Only bounded `application/sdp` bodies with `v=0` and at least one media line are sent for media rewriting. Invalid or non-SDP bodies remain unmodified.
- `SIP_IMS_SESSION_TIMERS=1` validates request-side `Session-Expires` and `Min-SE`; it does not negotiate refresher ownership or generate endpoint refreshes.
- `SIP_IMS_IDENTITY_POLICY=1` filters trusted and untrusted asserted/preferred identity headers; it does not provide complete RFC 3325/RFC 8224 identity interworking.
- `SIP_IMS_PATH` supports one validated configured P-CSCF `Path`; dynamic flow tokens, discovery, and multi-hop profile-derived Path sets remain open.
- `SIP_IMS_SERVICE_ROUTE` supports one validated configured local S-CSCF `Service-Route`; third-party registration remains external.
- `SIP_IMS_ASSOCIATED_URI` supports one validated fallback or up to eight validated subscriber-profile identities.
- Subscriber `initial_filter_criteria` is limited to four validated SIP/SIPS application targets. Full iFC condition evaluation and TAS behavior remain external.
- Madis does not provide HSS/UDM storage or AKA vector generation, full AKA algorithms, TAS/MMTel, PCRF/PCF, a complete Diameter relay, media termination, or PSTN/SIGTRAN gateway behavior.

See [`../README.md`](../README.md), [`../api/ims-diameter.md`](../api/ims-diameter.md), [`../api/ims-subscriber.md`](../api/ims-subscriber.md), and [`architecture.md`](architecture.md) for the detailed boundaries.

## First lab profile

The first profile is complete only when two provisioned IMS subscribers can register and establish authenticated originating and terminating voice sessions through a selected P-/I-/S-CSCF topology.

### In scope

1. SIP over UDP/TCP/TLS with a controlled access-network model.
2. IMS AKA-backed REGISTER authorization through an HSS-compatible service.
3. Explicit P-CSCF, I-CSCF, and S-CSCF responsibilities, even if initially deployed in one unit.
4. Cx UAR/UAA, MAR/MAA, SAR/SAA, and LIR/LIA procedures needed for registration and session routing.
5. A subscriber service owning IMPI, IMPU, authentication vectors, profiles, iFC, barring, and S-CSCF assignment.
6. Basic originating and terminating SIP sessions with transaction, dialog, identity, privacy, timer, and offer/answer behavior.
7. An external or integrated media anchor able to relay negotiated media.
8. Observability, deterministic failures, configuration validation, recovery procedures, and reproducible interoperability tests.

## Architecture and ownership

```text
 IMS UE / access network
          |
       P-CSCF  -------- HSS/UDM and subscriber service
          |
       I-CSCF  -------- Diameter Cx/Sh peer
          |
       S-CSCF  -------- TAS/application service
          |
       SIP/dialog       RTPEngine/media platform
          |
       policy/charging service
```

| Concern | Owner in the first profile |
| --- | --- |
| SIP transactions, dialogs, routing, and CSCF role behavior | Madis IMS service |
| IMS identities, AKA secrets, vectors, profiles, and assignment | HSS/UDM or subscriber service |
| Media packets and media security | Media platform |
| Application services and iFC-triggered logic | TAS/application service |
| Policy and charging decisions | External policy/charging service |
| Provisioning and operations | Madis API plus subscriber-service API |

Private identities and authentication material must remain outside general SIP routing tables and require separate access control, encryption, rotation, auditing, and backup policy.

## Remaining work

The phases below are ordered by dependency. A phase is complete only when its acceptance evidence exists; implementation alone is not sufficient.

### Phase 1 — External end-to-end lab interoperability (next)

- Connect Cx to a real HSS/UDM or selected HSS-compatible adapter over the configured Diameter security and identity boundary.
- Exercise live UAR/UAA, MAR/MAA, SAR/SAA, and LIR/LIA, including unknown subscriber, barred subscriber, expired vector, unavailable HSS, malformed answer, and serving-S-CSCF mismatch cases.
- Validate a real HTTPS subscriber service with TLS trust, token rotation, provisioning, assigned S-CSCF state, profile retrieval, and fail-closed behavior.
- Register two IMS-compatible clients using the selected AKA profile, then complete originating and terminating sessions.
- Verify retransmission, INVITE/CANCEL separation, PRACK, provisional responses, timeout, BYE, dialog teardown, and node failure across the external systems.

Acceptance evidence: reproducible traces and test logs for two subscribers registering, authenticating, placing, and clearing calls through the selected topology, with deterministic negative responses and no stale registration state.

### Phase 2 — Real media-path interoperability

- Exercise the production RTPEngine offer, answer, and delete path against a real RTPEngine instance.
- Validate NAT traversal, codec and SDP negotiation, RTP/RTCP anchoring, ICE, DTLS-SRTP, DTMF, and media-session cleanup with selected endpoints.
- Define behavior for RTPEngine timeout, malformed response, capacity exhaustion, restart, and unreachable media node.
- Keep RTP ownership outside the SIP worker; the worker performs bounded media-control operations and SIP-side failure handling only.

Acceptance evidence: packet and signaling captures showing negotiated media, anchoring, teardown, and controlled failure for the supported endpoint/profile matrix. The local ng-shaped loopback test is not a substitute.

### Phase 3 — Selected IMS service profile

- Complete the P-/I-/S-CSCF behavior required by the selected 3GPP release, including dynamic Path and flow-token handling, multi-hop routing, SIP outbound, third-party registration, and serving-node reassignment where required.
- Implement full RFC 4028 session-refresh negotiation and endpoint refresher ownership, rather than request-side interval validation only.
- Define trusted identity and privacy behavior for the selected access and interconnect model, including required RFC 3325/RFC 8224 interoperability.
- Add standard iFC condition evaluation, third-party service triggering, TAS/MMTel supplementary services, and service-profile lifecycle handling.
- Close remaining SIP interoperability gaps for reliable provisional responses, offer/answer edge cases, early dialogs, fork cleanup, and in-dialog routing.

Acceptance evidence: standards-referenced positive, malformed, timeout, and failover tests for each selected feature. Unsupported features remain explicitly disabled or rejected.

### Phase 4 — Diameter, policy, charging, and interconnect

- Add required Diameter peer scheduling, capability negotiation, reconnect/failover, overload protection, relay behavior, push requests, and multi-site recovery.
- Integrate PCRF/PCF policy and bearer handling only where required by the selected access profile.
- Complete online/offline charging, quota, reauthorization, CDR correlation, and media-policy enforcement for the selected charging model.
- Add IBCF/SBC topology policy and, if required, BGCF, MGCF, IMS-MGW, and SIGTRAN interworking.
- Define and test roaming, emergency calling, lawful-intercept, and regulatory behavior before including those deployments in scope.

Acceptance evidence: interoperable protocol traces, failure-recovery tests, and release-specific conformance records for every enabled interface. Unimplemented interfaces remain external.

### Phase 5 — Production operations and security review

- Verify active-active or active-standby clustering, transaction affinity, state ownership, registration recovery, database failover, rolling upgrades, backup/restore, and partition behavior.
- Measure configured CPS and concurrent-call targets on representative hardware with documented CPU, memory, file descriptors, database, network, retransmission, and media conditions. Measurements are acceptance data, not capacity guarantees.
- Complete observability for SIP transactions, Diameter exchanges, media-control failures, registration state, CDR correlation, queue drops, and node health.
- Run an independent white-hat security review covering SIP parsing, Diameter input, HTTP contracts, TLS, authorization, replay, resource exhaustion, secrets handling, and cluster boundaries; track and retest every finding.

Acceptance evidence: signed test reports, reproducible load profiles, recovery procedures, security findings with remediation status, and an upgrade/restore rehearsal that does not expose subscriber secrets or silently lose registrations.

## Definition of done for the first profile

The first profile is complete only when an automated or reproducible environment demonstrates:

1. A provisioned subscriber performs IMS AKA registration through P-/I-/S-CSCF behavior.
2. Cx failures produce deterministic SIP responses and do not leave stale registration state.
3. Two registered subscribers complete originating and terminating sessions.
4. Retransmissions, cancellation, timeout, dialog teardown, and node failure are handled correctly.
5. Identity and privacy rules are preserved across trusted and untrusted boundaries.
6. Media is negotiated, anchored, monitored, and torn down without the SIP worker owning RTP.
7. Metrics, traces, CDR correlation, configuration validation, and recovery procedures are documented.
8. Upgrade and restore procedures do not expose subscriber secrets or silently lose registration state.

## Deferred carrier scope

The following are not prerequisites for the first lab profile, but require separate design and acceptance before any carrier deployment:

- full TAS/MMTel and supplementary services;
- PCRF/PCF policy authorization and dedicated bearer/PDU-session control;
- LTE/5G access integration beyond the selected lab model;
- roaming, emergency services, lawful intercept, and regulatory call handling;
- PSTN interworking through BGCF, MGCF, IMS-MGW, and SIGTRAN;
- RCS, presence, messaging, conferencing, recording, transcoding, and announcements;
- complete Diameter relay, overload, and multi-site failover;
- online charging, quota enforcement, reauthorization, and production CDR mediation;
- carrier-scale active-active deployment and disaster recovery.

## Standards and evidence

The implementation must be versioned against a selected release rather than treating “IMS support” as unbounded:

- [3GPP TS 23.228 — IP Multimedia Subsystem stage 2](https://www.3gpp.org/dynareport/23228.htm)
- [3GPP TS 24.229 — IMS call control](https://www.3gpp.org/dynareport/24229.htm)
- [3GPP TS 29.228/29.229 — Cx/Dx](https://www.3gpp.org/dynareport/29229.htm)
- [3GPP TS 29.328/29.329 — Sh](https://www.3gpp.org/dynareport/29329.htm)
- [3GPP TS 29.214 — Rx](https://www.3gpp.org/dynareport/29214.htm)
- [3GPP TS 33.203 — IMS access security](https://www.3gpp.org/dynareport/33203.htm)
- [RFC 3261 — SIP](https://www.rfc-editor.org/rfc/rfc3261)
- [RFC 3262 — PRACK](https://www.rfc-editor.org/rfc/rfc3262)
- [RFC 3264 — SDP offer/answer](https://www.rfc-editor.org/rfc/rfc3264)
- [RFC 4028 — SIP session timers](https://www.rfc-editor.org/rfc/rfc4028)
- [RFC 5626 — SIP outbound](https://www.rfc-editor.org/rfc/rfc5626)
- [RFC 8224 — SIP identity](https://www.rfc-editor.org/rfc/rfc8224)

Local coverage is recorded in [`testing.md`](testing.md). External SIP, Diameter/IMS, media, and carrier interoperability must be recorded separately from local unit and contract tests.
