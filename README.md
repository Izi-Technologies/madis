# Madis

Madis is a SIP proxy and registrar written in [Mako](https://github.com/mako-lang). It provides SIP signaling, registration, authentication, routing, bounded call policy, and integration points for the systems that own billing, media, and carrier applications.

Madis is not a complete telecom business platform. It does not provide rating, invoicing, a tenant database, an RTP/media server, a complete IMS core, or a generic SQL/API gateway.

## What Madis provides

- RTPEngine offer/answer/delete commands include Call-ID and SIP dialog-tag correlation; RTP, ICE, DTLS-SRTP, codecs, and recording remain external.
- Only bounded `application/sdp` bodies with the required session and media lines are sent to RTPEngine; invalid or non-SDP bodies continue without media rewriting.
- Optional RFC 4028 request-side session-timer validation for INVITE and UPDATE, including bounded `Session-Expires`/`Min-SE` syntax, duplicate-header rejection, 400 malformed-request responses, and 422 minimum-interval responses. Endpoint refresh generation remains external.
- Optional trusted-network IMS identity/privacy boundary: untrusted ingress cannot supply `P-Asserted-Identity` or `P-Preferred-Identity`; trusted IP-authenticated peers receive strict single-identity validation, and `Privacy: id` removes asserted/preferred identity on outbound INVITEs.
- Optional P-CSCF `Path` insertion for forwarded REGISTER requests via `SIP_IMS_PATH`; the configured route is strictly validated and replaces UE-supplied Path headers only in the P-CSCF role.
- Optional local-S-CSCF `Service-Route` in successful REGISTER responses via `SIP_IMS_SERVICE_ROUTE`; the configured route is strictly validated and third-party registration remains external.
- Optional local-S-CSCF `P-Associated-URI` in successful REGISTER responses via `SIP_IMS_ASSOCIATED_URI`, or from up to eight validated `service_profile.associated_uris` values returned by the subscriber service.
- Bounded subscriber-profile `initial_filter_criteria`: up to four unique SIP/SIPS application targets can terminally fork an originating initial INVITE from a live local registration or a terminating initial INVITE for a live destination registration; full iFC conditions and TAS behavior remain external.

- SIP proxy and registrar behavior with UDP, TCP, TLS, WS, and WSS listeners.
- REGISTER contact storage, expiry handling, wildcard removal, digest authentication, and database hydration.
- RFC 3261 transaction behavior, retransmission handling, forking, CANCEL, ACK, response routing, Via/Route/Record-Route, Max-Forwards, and Content-Length checks.
- RFC 3263-style NAPTR/SRV transport selection with A/AAAA fallback, IPv6 signaling, and outbound WSS connection reuse.
- Database-backed routing rules, dispatch groups, failover, dialplan number transformation, access-control policy, security bans, ANI ranges, gateways, and header rules.
- Optional single-target B2BUA routing. Enable it with `SIP_B2BUA_MODE=enabled` before using a `b2bua:` route action.
- RTPEngine control-plane hooks for bounded SDP offer/answer and delete exchanges. RTP, ICE, DTLS-SRTP, codecs, and media recording are outside the SIP worker.
- A separate authenticated WebUI and a versioned machine API under `/admin/api/v1/`.
- Durable billing events, bounded CDR reads, and optional online charging through HTTP or Diameter.
- Signed HTTP application and module contracts for live SIP decisions and external TTS/STT/LLM/media/recording/fraud/billing workers.
- Bounded Diameter RFC 6733 peer handling, RFC 8506 credit-control messages, selected IMS Cx/Sh contracts, and an SS7/M3UA envelope for external gateways.
- STIR/SHAKEN verification and signing interfaces. Deployment-specific certificate, attestation, and interoperability validation remain the operator’s responsibility.

The implemented protocol scope and known gaps are summarized in [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md).

## Quick start

For a Linux host:

```sh
sudo ./install.sh
madis status
madis health
madis webui
```

The installer provisions PostgreSQL state, systemd units, the SIP worker, the standalone WebUI, the `madis` CLI, log rotation, and generated credentials. Keep the WebUI bound to loopback and terminate public HTTPS/WSS in a reverse proxy.

For a local Docker deployment:

```sh
export MADIS_DB_PASS='replace-with-a-random-database-password'
export MADIS_ADMIN_TOKEN='replace-with-a-random-admin-token'
export MADIS_CARRIER_API_TOKEN='replace-with-a-random-carrier-token'
export MADIS_CONTROL_API_TOKEN='replace-with-a-random-control-write-token'
export MADIS_CONTROL_API_READ_TOKEN='replace-with-a-random-control-read-token'
docker compose up -d --build
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/healthz
```

The Compose file requires these secrets and binds the worker HTTP and PostgreSQL ports to loopback. It runs the SIP worker, not the standalone WebUI; build and run `admin/main.mko` separately when browser administration is required. Compose remains a local-development profile, not a public deployment.

## Documentation map

The IMS lab HSS adapter and media sidecar are documented in [`lab/README.md`](lab/README.md) and [`media/README.md`](media/README.md).

The reproducible Docker IMS integration lab is documented in [`docker/ims-lab/README.md`](docker/ims-lab/README.md) and uses [`docker-compose.ims-lab.yml`](docker-compose.ims-lab.yml) to run HSS/Cx/AKA, the SIP worker, the media relay, and a two-subscriber end-to-end client test.

| Need | Guide |
| --- | --- |
| Understand process/data flow | [`docs/architecture.md`](docs/architecture.md) |
| Configure listeners, security, billing, and integrations | [`docs/configuration.md`](docs/configuration.md) |
| Install, operate, upgrade, and troubleshoot | [`docs/operations.md`](docs/operations.md) |
| Integrate application services | [`docs/integrations.md`](docs/integrations.md) |
| Use the HTTP/JSON and Protobuf carrier APIs | [`api/README.md`](api/README.md), [`sdk/README.md`](sdk/README.md) |
| Run checks and benchmarks | [`docs/testing.md`](docs/testing.md), [`bench/README.md`](bench/README.md) |
| Build the WebUI | [`admin/README.md`](admin/README.md) |
| Add live SIP applications or external modules | [`docs/modules.md`](docs/modules.md) |
| Use Diameter, IMS, or SS7 integration contracts | [`api/diameter.md`](api/diameter.md), [`api/ims-diameter.md`](api/ims-diameter.md) |
| Plan the IMS implementation | [`docs/ims-roadmap.md`](docs/ims-roadmap.md) |
| Review deployment and protocol boundaries | [`PRODUCTION.md`](PRODUCTION.md), [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md) |

## Machine APIs

The machine API is served by the standalone WebUI at:

```text
https://<admin-host>/admin/api/v1/
```

The SIP worker’s `/healthz`, `/readyz`, `/metrics`, `/state`, and `/reload` endpoints are a separate local HTTP surface. They are not the carrier API.

### Authentication scopes

| Credential | Capabilities |
| --- | --- |
| `SIP_CARRIER_API_TOKEN` | Capabilities, billing outbox events, event acknowledgement, and CDR reads. |
| `SIP_CONTROL_API_READ_TOKEN` | Read-only control status, routing/dialplan reads, validation, and resource lists. |
| `SIP_CONTROL_API_TOKEN` | Everything in the read-only control scope plus policy and resource writes. |
| WebUI session | Browser pages and role-gated WebUI actions; not accepted by machine API routes. |

Control write tokens should be held only by the service that is allowed to change call behavior. Billing consumers normally need only the carrier token. Tokens are bearer credentials: keep them server-side, use TLS, and rotate them through the deployment secret store.

### API groups

The complete endpoint and schema reference is [`api/README.md`](api/README.md), with the OpenAPI contract in [`api/openapi.yaml`](api/openapi.yaml) and the Protobuf messages in [`api/madis-carrier.proto`](api/madis-carrier.proto).

- `GET /capabilities` reports enabled transports and integration contracts.
- `/billing/events` provides an idempotent event outbox. Consumers read pending events, commit their own transaction, deduplicate by `event_id`, and acknowledge only after the commit succeeds.
- `GET /billing/cdr` provides bounded CDR records for rating and reconciliation.
- `/control/routing-rules` and `/control/dialplans` manage allowlisted routing policy and number transformations.
- `/control/validate/routing-rule` and `/control/validate/dialplan` validate documents without storing them.
- `/control/resources/{resource}` manages only the allowlisted SIP resources described below.

The API accepts JSON bodies up to 64 KiB and limits list requests to 100 records. It never executes caller-provided SQL, Mako, shell commands, or arbitrary application code.

### Control resources

The generic resource API exposes these Madis-owned resources:

| Resource | Access | Purpose |
| --- | --- | --- |
| `gateways` | Read/write | Carrier destination address, transport, credentials, caller ID, number format, prefix, and channel limits. |
| `routes` | Read/write | Prefix routes to exactly one gateway or dispatch set, priority, weight, cost, and time window. |
| `dispatch-sets` | Read/write | Named gateway selection groups and algorithms. |
| `dispatch-members` | Read/write | Gateway membership, priority, and weight within a dispatch set. |
| `dids` | Read/write | DID number to destination-user mapping. |
| `header-rules` | Read/write | Validated add, remove, or set rules for SIP headers. |
| `access-control` | Read/write | Source/user policy, allow/deny action, authentication bypass flag, tenant label, and channel limit. |
| `security-bans` | Read/create-upsert | Source-IP bans, reason, and permanence. The current resource shape is keyed by `source_ip`, so the generic numeric-ID update/delete/state operations do not apply. |
| `ani-groups` | Read/write | Named ANI groups. |
| `ani-ranges` | Read/write | Start/end ranges attached to ANI groups. |
| `registrations` | Read-only | Current AOR/contact registration state. |
| `registration-bindings` | Read-only | Registration bindings with source and expiry information. |
| `cluster-nodes` | Read-only | Node health and heartbeat metadata. |
| `security-events` | Read-only | Bounded security event history. |

Mutable responses include a `revision`. Send `expected_revision` when concurrent control writers need optimistic concurrency. The resource API is intentionally not an application database: billing, tenant, product, rating, and invoice data stays in the external application.

## Installation and builds

The supported source entry point is [`main.mko`](main.mko); [`sipproxy_full.mko`](sipproxy_full.mko) is a legacy monolithic reference and is not the deployment target. Builds require Mako 0.4.18 and its matching runtime:

```sh
MAKO_BIN=mako MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko madis

MAKO_BIN=mako MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

`scripts/ci.sh` runs Mako checks and lint, the Mako test suites, native links, schema validation, shell syntax validation, and the Python SDK compile check. See [`docs/testing.md`](docs/testing.md) for what those checks do and do not prove.

## Integration boundaries

For the bounded IMS session path, established-dialog re-INVITEs follow recorded SIP dialog/Route state before role selection or new-call policy; this does not make Madis a complete IMS dialog or service-role implementation. When `SIP_IMS_SESSION_TIMERS=1`, INVITE and UPDATE request headers are checked against configured 90–86,400 second bounds; the feature does not generate refreshes or maintain endpoint timer state.

Transparent in-dialog PRACK and UPDATE forwarding is supported for early and confirmed dialogs; the proxy validates tracked RSeq/RAck state but does not generate reliable provisional responses or claim endpoint-level conformance.

When `SIP_IMS_IDENTITY_POLICY=1`, trusted identity means the existing IP-authenticated or loopback source boundary. This policy does not generate P-Asserted-Identity, rewrite From to anonymous, or implement complete RFC 3325/RFC 8224 interworking. In the P-CSCF role, `SIP_IMS_PATH` adds one validated Path to forwarded REGISTER requests and removes UE-supplied Path headers; it does not implement dynamic Path discovery or flow-token management. `SIP_IMS_SERVICE_ROUTE` adds one validated Service-Route to local S-CSCF REGISTER responses. `SIP_IMS_ASSOCIATED_URI` is a validated static fallback; an authorized subscriber `service_profile.associated_uris` list takes precedence when present. Target-only `service_profile.initial_filter_criteria` is limited to four validated application targets on originating initial INVITEs from live local registrations and terminating initial INVITEs for live destination registrations. Full iFC condition evaluation, third-party registration, and TAS routing remain external.

Madis owns SIP transaction, dialog, registration, routing, and transport state. External services own their application frameworks, tenant authorization, rating, invoices, durable business state, media plane, HSS/UDM, and SS7 gateway behavior.

| Area | Madis provides | External system remains responsible for |
| --- | --- | --- |
| Billing | CDRs, durable outbox, idempotent acknowledgement, optional preauthorization | Rating, ledger, invoicing, settlement, tax, and tenant business rules |
| Media | RTPEngine control messages and SDP hooks | RTP, ICE, DTLS-SRTP, codecs, recording, and media policy |
| Diameter | RFC 6733 framing, RFC 8506 credit control, selected Cx/Sh builders | General relay, peer scheduler, HSS/UDM, quota timers, and carrier-specific conformance |
| IMS | Cx/Sh wire contracts, bounded P-/I-/S-CSCF REGISTER and initial-INVITE role routing, optional Cx UAR/SAR/LIR authorization, optional Cx MAR/MAA-backed AKAv1-MD5 REGISTER, optional HTTPS subscriber authorization with bounded associated-identity and target-only `service_profile` fields, opt-in RFC 4028 request-side interval validation, trusted-network identity/privacy filtering, one configured P-CSCF Path, one configured local-S-CSCF Service-Route, and one configured local-S-CSCF P-Associated-URI fallback | HSS/UDM and AKA generation, endpoint session refreshes, identity assertion generation, dynamic Path/flow-token management, full iFC condition evaluation, third-party registration, TAS/MMTel, PCRF/PCF, full dialog/service-role behavior, and the complete IMS core |
| SS7/SIGTRAN | Versioned M3UA/SCCP/ISUP/TCAP envelope | Native M3UA/SCCP/ISUP/TCAP termination and gateway operations |
| Applications/modules | Signed, bounded HTTP contracts and command validation | Application logic, long-running jobs, model/media workers, and business persistence |

For the detailed support matrix, read [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md). Local tests and wire-contract checks are evidence for the tested paths; they are not universal interoperability or security certification.
## Scale, clustering, and HEP

Active-active deployment guidance is in [`docs/clustering.md`](docs/clustering.md).
Optional HEPv3 UDP capture is configured in [`docs/configuration.md`](docs/configuration.md)
and is best-effort so a collector outage cannot block SIP processing.
