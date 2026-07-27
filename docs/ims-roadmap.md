# Madis IMS roadmap

## Purpose

This document defines the first implementation target for extending Madis toward a standards-based IP Multimedia Subsystem (IMS). It is a delivery roadmap and capability boundary, not a claim that Madis is already a complete IMS core.

The first target is a lab-capable IMS voice profile. Carrier deployment, VoLTE/VoWiFi, 5G integration, roaming, emergency calling, RCS, and PSTN interconnect are follow-on profiles with additional requirements.

## Starting point

Madis currently provides a SIP proxy/registrar platform with:

- SIP UDP, TCP, TLS, WS, and WSS transport;
- registration, authentication, transactions, dialogs, routing, dispatch, dialplans, and CDR/outbox behavior;
- PostgreSQL-backed SIP state and an authenticated administration API;
- RTPEngine control-plane hooks, but not the RTP/media plane;
- RFC 6733 Diameter framing and RFC 8506 credit-control support;
- selected client-side 3GPP Cx and Sh message builders and answer parsing, including opaque Cx MAA authentication-data extraction;
- optional Cx UAR/SAR authorization during REGISTER.
- explicit bounded P-CSCF, I-CSCF, and S-CSCF REGISTER behavior: P-CSCF forwarding, I-CSCF static forwarding or Cx LIR/LIA S-CSCF selection, and S-CSCF-local authentication/registration;
- optional fail-closed HTTPS subscriber authorization during REGISTER, using the versioned contract in [`../api/ims-subscriber.md`](../api/ims-subscriber.md).
- a database-backed lab subscriber provider for identity authorization, assigned S-CSCF, and service-profile data; optional SIP AKA REGISTER using opaque Cx MAR/MAA vectors, a short-lived XRES cache, RFC 3310 Digest response validation, and exact assigned-S-CSCF binding.

These capabilities are useful lab-profile building blocks, but the current implementation does not provide HSS/UDM storage or authentication-vector generation; full AKA algorithm support; TAS/MMTel; PCRF/PCF; a complete Diameter peer/relay service; media termination; or PSTN/SIGTRAN gateway behavior. The CSCF role layer is bounded to REGISTER routing and does not yet claim full carrier-grade role behavior. See [`../README.md`](../README.md), [`../api/ims-diameter.md`](../api/ims-diameter.md), and [`architecture.md`](architecture.md) for the current integration boundaries.

## Initial profile

The first end-to-end profile should prove two IMS subscribers can register and establish authenticated originating and terminating voice sessions.

### In scope for the first profile

1. SIP over UDP/TCP/TLS, with a controlled access-network model.
2. IMS AKA-backed REGISTER authorization through an HSS-compatible service.
3. Explicit P-CSCF, I-CSCF, and S-CSCF routing behavior. These roles may initially run in one deployment unit, but their responsibilities and interfaces must remain separate.
4. Cx procedures needed for registration and session routing: UAR/UAA, MAR/MAA, SAR/SAA, and LIR/LIA, with deregistration and server-assignment handling defined.
5. A subscriber service that owns IMPI, IMPU, authentication vectors, service profiles, initial filter criteria, and S-CSCF assignment.
6. Basic originating and terminating SIP sessions with reliable transaction, dialog, identity, privacy, session-timer, and offer/answer behavior.
7. An external or integrated media anchor able to relay the negotiated media for the lab profile.
8. Basic observability, failure responses, configuration validation, and reproducible interoperability tests.

### Explicitly deferred

The following are not prerequisites for the first lab profile, but are required before a carrier-grade IMS claim:

- full TAS/MMTel and supplementary services;
- PCRF/PCF policy authorization and dedicated bearer/PDU-session control;
- LTE and 5G access-specific integration beyond the selected lab model;
- roaming, emergency services, lawful intercept, and regulatory call handling;
- PSTN interworking through BGCF, MGCF, IMS-MGW, and SIGTRAN;
- RCS, presence, messaging, conferencing, recording, transcoding, and announcements;
- complete Diameter relay, peer scheduling, overload, and multi-site failover;
- online charging, quota enforcement, reauthorization, and production CDR mediation;
- carrier-scale active-active deployment and disaster recovery.

## Target architecture

```text
                         +----------------------+
 IMS UE / access network | P-CSCF               |
 ---------------------->| Madis access role     |
                         +----------+-----------+
                                    |
                         +----------v-----------+
                         | I-CSCF / S-CSCF      |
                         | Madis IMS roles      |
                         +---+------+------+----+
                             |      |      |
                   +---------v+  +--v---+  +v----------------+
                   | HSS/UDM  |  | TAS/AS|  | Media platform   |
                   | AKA/data |  | later |  | RTP/RTCP/SRTP    |
                   +----------+  +------+  +------------------+
                             |
                         +---v----------------+
                         | Policy / charging  |
                         | PCF/PCRF, OCS/CHF  |
                         +--------------------+
```

The architecture should keep ownership clear:

| Concern | Owner in the first profile |
| --- | --- |
| SIP transactions, dialogs, routing, and role behavior | Madis IMS service |
| IMS identities, AKA secrets, authentication vectors, profiles | HSS/UDM service |
| Media packets and media security | Media platform |
| Application services and iFC-triggered logic | TAS/application service, initially optional |
| Policy and charging decisions | External policy/charging service, initially stubbed or deferred |
| Provisioning and operational control | Madis API plus subscriber-service API |

HSS/UDM data must not be copied into general SIP routing tables. Private identities and authentication material require separate access controls, encryption, rotation, auditing, and a defined backup policy.

## Delivery phases

### Phase 0 — profile and contracts

- Select the 3GPP release and access model.
- Document the REGISTER and basic call sequence diagrams.
- Define the subscriber-service API and data ownership.
- Define the Cx peer configuration, trust model, timeout, retry, and failover behavior.
- Add a capability matrix that distinguishes implemented, integrated, and deferred behavior.

### Phase 1 — IMS identity and authentication

- Implement an HSS-compatible lab service or an adapter to an existing HSS/UDM.
- Store IMPI, IMPU, realm, aliases, service profile, iFC, barring, and assignment state.
- Generate and validate IMS AKA vectors without exposing private keys through SIP or general administration APIs.
- Complete the Cx registration flow and negative cases: unknown user, barred user, expired vector, unavailable HSS, and failed assignment.

### Phase 2 — CSCF roles and basic calls

- Add explicit P-CSCF, I-CSCF, and S-CSCF configuration and routing decisions.
- Implement access/interconnect trust boundaries and topology policy.
- Complete registration refresh, de-registration, third-party registration, and S-CSCF reassignment behavior.
- Validate originating and terminating calls, forked contacts, retransmissions, early dialogs, cancellation, timeout, and failover behavior.
- Close the relevant SIP gaps recorded in [`../RFC_COMPLIANCE.md`](../RFC_COMPLIANCE.md), especially reliable 100rel generation/conformance, offer/answer, session timers, identity, privacy, and outbound behavior.

### Phase 3 — media and application services

- Define the media-control contract and select the media implementation.
- Add media anchoring, codec policy, DTMF, SRTP/DTLS, and media failure handling.
- Add TAS/MMTel only after the base call path is stable.
- Add initial filter criteria and third-party service triggering.

### Phase 4 — policy, charging, and interconnect

- Add Rx/Gx for EPC or the selected 5G policy interfaces.
- Add online/offline charging, quota, reauthorization, and CDR correlation.
- Add IBCF/SBC and topology-hiding policy.
- Add BGCF/MGCF/IMS-MGW and native signaling gateways for PSTN requirements.

### Phase 5 — carrier readiness

- Add active-active or active-standby behavior, state replication, and database failover.
- Test Diameter/SIP failure recovery, overload, partitions, and rolling upgrades.
- Add emergency services, roaming, lawful-intercept interfaces, security audits, and operational runbooks as required by the deployment.
- Run interop and conformance testing against the selected 3GPP release and partner implementations.

## Definition of done for the first profile

The first profile is complete only when an automated or reproducible test environment can demonstrate:

1. A provisioned subscriber performs IMS AKA registration through P-/I-/S-CSCF behavior.
2. Cx failures produce safe, deterministic SIP responses and do not leave stale registration state.
3. Two registered subscribers complete originating and terminating sessions.
4. Retransmissions, cancellation, timeout, dialog teardown, and node failure are handled correctly.
5. SIP identity and privacy rules are preserved across trusted and untrusted boundaries.
6. Media is negotiated, anchored, monitored, and torn down without the SIP worker pretending to own RTP.
7. Metrics, traces, CDR correlation, configuration validation, and recovery procedures are documented.
8. The deployment can be upgraded and restored without exposing subscriber secrets or silently losing registration state.

## Standards baseline

The implementation should be versioned against a specific release of the following specifications rather than treating “IMS support” as an unbounded feature:

- [3GPP TS 23.228 — IP Multimedia Subsystem stage 2](https://www.3gpp.org/dynareport/23228.htm)
- [3GPP TS 24.229 — IP multimedia call control protocol based on SIP and SDP](https://www.3gpp.org/dynareport/24229.htm)
- [3GPP TS 29.228/29.229 — Cx/Dx interface](https://www.3gpp.org/dynareport/29229.htm)
- [3GPP TS 29.328/29.329 — Sh interface](https://www.3gpp.org/dynareport/29329.htm)
- [3GPP TS 29.214 — Rx interface](https://www.3gpp.org/dynareport/29214.htm)
- [3GPP TS 33.203 — IMS access security](https://www.3gpp.org/dynareport/33203.htm)
- [RFC 3261 — SIP](https://www.rfc-editor.org/rfc/rfc3261)
- [RFC 3262 — PRACK and reliable provisional responses](https://www.rfc-editor.org/rfc/rfc3262)
- [RFC 3264 — SDP offer/answer](https://www.rfc-editor.org/rfc/rfc3264)
- [RFC 4028 — SIP session timers](https://www.rfc-editor.org/rfc/rfc4028)
- [RFC 5626 — SIP outbound](https://www.rfc-editor.org/rfc/rfc5626)
- [RFC 8224 — SIP identity](https://www.rfc-editor.org/rfc/rfc8224)

## Immediate next implementation increment

Established-dialog re-INVITEs now use the recorded SIP dialog/Route target before IMS role selection, charging, application, dial-plan, or new-call state. Transaction replay, INVITE/CANCEL separation, and BYE teardown are covered by focused adversarial tests.

PRACK and UPDATE now forward through early or confirmed dialog state, with To-tag-specific target selection for forked early dialogs. PRACK is checked against tracked RSeq/RAck state; reliable provisional-response generation and endpoint-level conformance remain open interoperability work.

The REGISTER lifecycle now maps initial registration, active-binding refresh, and explicit user de-registration to the corresponding Cx SAR assignment types, with adversarial coverage for wildcard and `expires=0` removal.

Cluster INVITE fallback now trusts only live `registration_bindings` rows with current expiry and owner heartbeat; the legacy registration table cannot keep an expired remote contact routable.

The Cx UAR/UAA registration path now requires the HSS-returned `Server-Name` to exactly match the configured serving S-CSCF before SAR or local registration state is written. Missing, mismatched, or malformed assignments fail closed.

The subscriber contract, Cx vector retrieval, SIP AKA profile, exact assigned-S-CSCF binding, bounded P-/I-/S-CSCF REGISTER plus initial-INVITE role behavior, and a deterministic two-subscriber Cx/AKA/session lab test are now implemented. The next increment is live authenticated registration and call interoperability against an external HSS/UDM and media path.

The original checklist below records the completed identity/authentication foundation; the next active work is end-to-end role interoperability and registration lifecycle behavior described above.

The first code increment should be the **IMS identity/authentication contract**:

1. Define a versioned subscriber-service interface for lookup, AKA vector retrieval, profile/iFC retrieval, and S-CSCF assignment.
2. Add contract fixtures for successful registration and each required negative response.
3. Replace the current implicit Cx-only REGISTER assumptions with an explicit adapter boundary.
4. Add integration tests that prove the SIP worker fails closed when the subscriber service is unavailable or returns an invalid authorization result.

This gives Madis a testable foundation for the first end-to-end IMS registration path without prematurely embedding an HSS, media server, policy engine, and application server into the SIP worker.
