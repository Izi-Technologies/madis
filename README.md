# Madis

Madis is a SIP proxy and registrar written in [Mako](https://github.com/loreste/mako). It owns SIP signaling state and policy; billing, subscriber identity, media, and carrier applications remain separate concerns.

This README is an orientation guide, not a complete feature matrix. The linked documentation and source contracts are authoritative for configuration and protocol boundaries.

## Current implementation

- SIP UDP, TCP, TLS, WS, and WSS listeners with registration, digest authentication, transactions, dialogs, retransmission handling, routing, forking, dispatch, dialplans, and response routing.
- PostgreSQL-backed registrations, routing policy, access control, security state, CDRs, and a durable billing-event outbox.
- A standalone authenticated WebUI and versioned machine API under `/admin/api/v1/`.
- Optional RTPEngine-ng control messages for bounded SDP offer/answer/delete operations. The SIP worker does not own RTP, RTCP, ICE, DTLS-SRTP, codecs, recording, or media policy.
- Selected Diameter RFC 6733/RFC 8506, IMS Cx/Sh, HEPv3, STIR/SHAKEN, charging, and signed external-application contracts. These are bounded integration surfaces, not complete relay, policy, media, or carrier platforms.
- A bounded IMS voice profile: role-aware P-/I-/S-CSCF REGISTER and initial-INVITE handling, selected Cx/AKA authorization, HTTPS subscriber authorization, request-side session-timer validation, trusted identity/privacy filtering, configured Path and Service-Route boundaries, P-Associated-URI handling, and target-only subscriber iFC application targets.

## IMS lab profile

The repository includes an opt-in lab that exercises the implemented IMS boundaries:

- [`lab/ims_hss.py`](lab/README.md) is a bounded Cx/AKA HSS-compatible adapter with HTTP/HTTPS subscriber authorization. It uses configured opaque XRES test values; it is not an HSS/UDM, AKA secret store, or vector generator.
- [`media/rtp_module.py`](media/README.md) is a separate RTPEngine-ng-compatible control sidecar with a bounded one-audio-stream RTP/RTCP relay. It is not a production media server.
- [`docker-compose.ims-lab.yml`](docker-compose.ims-lab.yml) composes the adapters, separate Mako `v0.4.18` P-/I-/S-CSCF workers, and a deterministic two-subscriber client.

The Docker smoke path covers deterministic unknown/barred registration rejection, TLS Cx/AKA, HTTPS subscriber authorization, P-/I-/S-CSCF REGISTER and initial-INVITE forwarding, SDP offer/answer rewriting, bidirectional RTP, ACK, and BYE. It does not establish full 3GPP IMS, real UE/HSS/UDM interoperability, carrier capacity, ICE/DTLS-SRTP support, or production failover. See [`docs/ims-roadmap.md`](docs/ims-roadmap.md) for the remaining work and acceptance evidence.

Run the lab from the repository root:

```sh
docker compose -f docker-compose.ims-lab.yml up \
  --abort-on-container-exit \
  --exit-code-from client
docker compose -f docker-compose.ims-lab.yml down
```

The default repository checks cover the offline lab unit/contract tests. Listener, worker-backed, and Docker checks are opt-in; their commands and limitations are documented in [`docs/testing.md`](docs/testing.md).

## Ownership and boundaries

| Concern | Madis owns | External system remains responsible for |
| --- | --- | --- |
| SIP | Parsing, transactions, dialogs, registration, routing, and bounded policy | Carrier topology and deployment-specific interoperability |
| Subscriber/IMS identity | Bounded authorization requests and selected Cx contracts | HSS/UDM storage, AKA generation, private-key material, profiles, and assignment |
| Media | SDP validation and RTPEngine control messages | RTP/RTCP, ICE, DTLS-SRTP, codecs, recording, and media policy |
| Billing/charging | CDRs, durable outbox, optional preauthorization contracts | Rating, invoicing, ledger, quota, settlement, tax, and tenant business rules |
| Applications | Signed, bounded command/event contracts | TAS/MMTel, long-running jobs, model/media workers, and application persistence |

Madis is not a complete telecom business platform, HSS/UDM, Diameter relay, TAS, PCRF/PCF, RTP/media server, PSTN/SIGTRAN gateway, or generic SQL/API gateway. Review [`PRODUCTION.md`](PRODUCTION.md), [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md), and [`docs/ims-roadmap.md`](docs/ims-roadmap.md) before treating any optional interface as deployment-ready.

## Quick start

For a Linux host:

```sh
sudo ./install.sh
madis status
madis health
madis webui
```

The installer provisions PostgreSQL state, systemd units, the SIP worker, standalone WebUI, `madis` CLI, log rotation, and generated credentials. Keep the WebUI private and terminate public HTTPS/WSS at a reverse proxy.

For the local development Compose profile:

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

That Compose file is a local SIP-worker profile, not the IMS lab and not a public deployment. The standalone WebUI is built and run separately; see [`admin/README.md`](admin/README.md).

## APIs and documentation

The machine API is served by the standalone WebUI at `/admin/api/v1/`. Bearer-token scopes, endpoint schemas, control resources, and billing/CDR flows are documented in [`api/README.md`](api/README.md), [`api/openapi.yaml`](api/openapi.yaml), and [`docs/configuration.md`](docs/configuration.md). The SIP worker's `/healthz`, `/readyz`, `/metrics`, `/state`, and `/reload` endpoints are a separate local HTTP surface.

| Need | Guide |
| --- | --- |
| Understand process/data flow | [`docs/architecture.md`](docs/architecture.md) |
| Configure listeners, security, billing, and integrations | [`docs/configuration.md`](docs/configuration.md) |
| Install, operate, upgrade, and troubleshoot | [`docs/operations.md`](docs/operations.md) |
| Integrate application services | [`docs/integrations.md`](docs/integrations.md) |
| Use carrier APIs and SDKs | [`api/README.md`](api/README.md), [`sdk/README.md`](sdk/README.md) |
| Run checks and benchmarks | [`docs/testing.md`](docs/testing.md), [`bench/README.md`](bench/README.md) |
| Add live SIP applications or external modules | [`docs/modules.md`](docs/modules.md) |
| Use Diameter, IMS, or SS7 contracts | [`api/diameter.md`](api/diameter.md), [`api/ims-diameter.md`](api/ims-diameter.md) |
| Plan IMS acceptance work | [`docs/ims-roadmap.md`](docs/ims-roadmap.md) |
| Review production and protocol boundaries | [`PRODUCTION.md`](PRODUCTION.md), [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md) |

## Build and test

The supported source entry point is [`main.mko`](main.mko). [`sipproxy_full.mko`](sipproxy_full.mko) is a legacy monolithic reference and is not the deployment target. Builds and CI require Mako `0.4.18` with its matching runtime; do not mix compiler/runtime versions when generating native C.

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko madis

MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

The CI script checks Mako syntax/lint, Mako tests, native links, schemas, shell syntax, Python SDK compilation, and the default HSS/media adapter tests. It does not replace external SIP, IMS, Diameter, media, or carrier interoperability testing. See [`docs/testing.md`](docs/testing.md) for opt-in wire, worker-backed, Docker, load, and recovery checks.
