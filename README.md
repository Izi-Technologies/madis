# Madis

Madis is a SIP proxy and registrar written in [Mako](https://github.com/loreste/mako). It owns SIP signaling state and policy; billing, subscriber identity, media, and carrier applications remain separate concerns.

This README is an orientation guide, not a complete feature matrix. The linked documentation and source contracts are authoritative for configuration and protocol boundaries.

## Version

**v0.7.0** — requires Mako 0.5.0+. Pure Mako: zero `extern "C"` functions, no C bridge code.

## Current implementation

- SIP UDP, TCP, TLS, and WSS (RFC 7118) listeners with registration, digest authentication, transactions, dialogs, retransmission handling, routing, forking, dispatch, dialplans, and response routing. Multiplexed TCP/TLS/WSS workers with `SO_REUSEPORT` multi-worker scaling. PROXY protocol v1 support for HAProxy deployments. Full SIP.js/JsSIP WebSocket compatibility with `Sec-WebSocket-Protocol: sip` subprotocol and transport-aware response routing.
- RFC 3261 compliance improvements: To-tag on all responses, CANCEL→487 generation, 3xx redirect following, and in-dialog REFER/INFO/MESSAGE forwarding. RFC 5626 outbound flow tokens with `+sip.instance`, `reg-id`, and flow token Path URI. RFC 3265/6665 event packages (SUBSCRIBE/NOTIFY with presence and message-summary). RFC 5923 TLS connection reuse with Via `;alias`. RFC 4028 session timer refresh with re-INVITE generation at 50% interval. RFC 3325 P-Asserted-Identity insertion with anonymous From support.
- Security hardening: per-method rate limits, digest URI validation, nonce-count monotonicity, registration enumeration detection, DNS rebinding guard, per-IP connection limits, constant-time digest comparison, and progressive authentication delay.
- PostgreSQL-backed registrations, routing policy, access control, security state, CDRs, and a durable billing-event outbox.
- A standalone authenticated WebUI and versioned machine API under `/admin/api/v1/`.
- Optional RTPEngine-ng control messages for bounded SDP offer/answer/delete operations, with WebRTC bridge support (auto-detect ICE/DTLS SDP). The SIP worker does not own RTP, RTCP, ICE, DTLS-SRTP, codecs, recording, or media policy.
- Cluster call state replication via `SIP_CLUSTER_CALLS`.
- Prometheus labeled metrics (per-method, per-response-code, per-transport) and graceful shutdown with connection drain.
- MAF SDKs in Python, Go, TypeScript, JavaScript, Erlang, and Weft with 90 HTTP operations covering calls, routing, media, presence, security, infrastructure, config, charging, webhooks, queues, conferences, scheduled calls, number intelligence, routing intelligence, and events. Real-time event streaming via HTTP long-poll (`subscribe()`) and WebSocket (`ws_url()`). SIPp interop scenarios covering fork/cancel, non-2xx ACK, CANCEL/487, timer retransmit, PRACK, and digest auth.
- Selected Diameter RFC 6733/RFC 8506, IMS Cx/Sh, HEPv3, STIR/SHAKEN (PASSporT header with `ppt`/`typ`/`x5u`, `iat` freshness check, orig/dest TN validation, x5u certificate fetch, Date header on signed messages), charging, and signed external-application contracts. These are bounded integration surfaces, not complete relay, policy, media, or carrier platforms.
- A bounded IMS voice profile: role-aware P-/I-/S-CSCF REGISTER and initial-INVITE handling, selected Cx/AKA authorization, HTTPS subscriber authorization, durable IMS registration lifecycle (IMPI/IMPU, Path, Service-Route, S-CSCF binding, restart hydration, and Path-aware MT routing), dynamic flow-token refresh/cleanup when enabled, session-timer validation plus negotiated response headers, trusted identity/privacy filtering, P-Associated-URI handling, target-only subscriber iFC application targets, and terminating P-Charging-Vector validation.

## IMS lab profile

The repository includes an opt-in lab that exercises the implemented IMS boundaries:

- [`lab/ims_hss.py`](lab/README.md) is a bounded Cx/AKA HSS-compatible adapter with HTTP/HTTPS subscriber authorization. It uses configured opaque XRES test values; it is not an HSS/UDM, AKA secret store, or vector generator.
- [`media/rtp_module.py`](media/README.md) is a separate RTPEngine-ng-compatible control sidecar with a bounded one-audio-stream RTP/RTCP relay. It is not a production media server.
- [`docker-compose.ims-lab.yml`](docker-compose.ims-lab.yml) composes the adapters, separate Mako `v0.5.0` P-/I-/S-CSCF workers, and a deterministic two-subscriber client.

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

## Install

### Package install (no Mako required)

Pre-built packages are published to [GitHub Releases](https://github.com/Izi-Technologies/madis/releases).

**Debian / Ubuntu:**

```sh
curl -fsSL https://raw.githubusercontent.com/Izi-Technologies/madis/main/packaging/repo/setup-apt.sh | sudo bash
```

**RHEL / Fedora / Rocky / AlmaLinux:**

```sh
curl -fsSL https://raw.githubusercontent.com/Izi-Technologies/madis/main/packaging/repo/setup-dnf.sh | sudo bash
```

Pin a specific version:

```sh
sudo bash setup-apt.sh 0.7.0
sudo bash setup-dnf.sh 0.7.0
```

After install, configure `/etc/madis/madis.env` (see the example at `/etc/madis/madis.env.example`) and start:

```sh
sudo systemctl enable --now madis
```

### Docker

```sh
docker compose up -d --build
```

### Source install

For a Linux host with the Mako compiler:

```sh
sudo ./install.sh
```

The installer provisions PostgreSQL state, systemd units, the SIP worker, standalone WebUI, `madis` CLI, log rotation, and generated credentials. Keep the WebUI private and terminate public HTTPS/WSS at a reverse proxy.

For the local development Compose profile:

```sh
: "${MADIS_DB_PASS:?set via secret manager}"
: "${MADIS_ADMIN_TOKEN:?set via secret manager}"
: "${MADIS_CARRIER_API_TOKEN:?set via secret manager}"
: "${MADIS_CONTROL_API_TOKEN:?set via secret manager}"
: "${MADIS_CONTROL_API_READ_TOKEN:?set via secret manager}"
docker compose up -d --build
curl -fsS http://localhost:8080/readyz
curl -fsS http://localhost:8080/healthz
```

That Compose file is a local SIP-worker profile, not the IMS lab and not a public deployment. The standalone WebUI is built and run separately; see [`admin/README.md`](admin/README.md).

Documentation examples use placeholders, `localhost`, or environment-provided
values only. Never commit real passwords, API keys, bearer tokens, private
keys, database URLs, environment-specific IP addresses, or private hostnames.

## APIs and documentation

### MADIS Application Fabric (MAF)

The **MADIS Application Fabric (MAF)** is Madis's language-neutral HTTP/JSON
application boundary. Services written in Go, JavaScript/TypeScript, Python,
or another language can observe call resources, submit bounded commands, and
consume replayable events without writing Mako, SQL, SIP bytes, or worker
memory. Madis remains the owner of SIP signaling state; the external
application owns business logic and persistence.

The standalone admin process currently exposes the documented MAF HTTP routes
and the bearer-authenticated event WebSocket:

```text
POST   /admin/api/v1/maf/calls                          — create call
GET    /admin/api/v1/maf/calls/{call_id}                 — get call
POST   /admin/api/v1/maf/calls/{call_id}/answer          — answer
POST   /admin/api/v1/maf/calls/{call_id}/reject          — reject
POST   /admin/api/v1/maf/calls/{call_id}/hangup          — hangup
POST   /admin/api/v1/maf/calls/{call_id}/route           — SDK routing
POST   /admin/api/v1/maf/calls/{call_id}/bridges         — bridge
POST   /admin/api/v1/maf/calls/{call_id}/transfer        — transfer
POST   /admin/api/v1/maf/calls/{call_id}/hold            — hold
POST   /admin/api/v1/maf/calls/{call_id}/unhold          — unhold
POST   /admin/api/v1/maf/calls/{call_id}/dtmf            — DTMF
POST   /admin/api/v1/maf/calls/{call_id}/media           — media
POST   /admin/api/v1/maf/calls/{call_id}/headers         — headers
POST   /admin/api/v1/maf/calls/{call_id}/rtp             — RTPEngine
GET    /admin/api/v1/maf/calls/{call_id}/sip             — SIP inspect
POST   /admin/api/v1/maf/calls/{call_id}/charge          — charge auth
POST   /admin/api/v1/maf/calls/{call_id}/charge-deny     — charge deny
GET    /admin/api/v1/maf/registrations                    — registrations
GET    /admin/api/v1/maf/presence                         — online users
GET    /admin/api/v1/maf/presence/{user}                  — user presence
GET    /admin/api/v1/maf/cdr                              — CDR
GET    /admin/api/v1/maf/security/bans                    — bans
POST   /admin/api/v1/maf/security/bans                   — ban IP
DELETE /admin/api/v1/maf/security/bans/{ip}              — unban IP
GET    /admin/api/v1/maf/routing/rules                    — routing rules
POST   /admin/api/v1/maf/routing/rules                   — create rule
DELETE /admin/api/v1/maf/routing/rules/{id}              — delete rule
GET    /admin/api/v1/maf/gateways                         — gateways
POST   /admin/api/v1/maf/gateways                        — create gateway
GET    /admin/api/v1/maf/dids                             — DIDs
POST   /admin/api/v1/maf/dids                            — create DID
GET    /admin/api/v1/maf/dispatch-sets                    — dispatch sets
POST   /admin/api/v1/maf/dispatch-sets                   — create set
GET    /admin/api/v1/maf/cluster                          — cluster health
GET    /admin/api/v1/maf/config                           — config
POST   /admin/api/v1/maf/config                          — set config
GET    /admin/api/v1/maf/events                           — event replay
POST   /admin/api/v1/maf/events                          — publish event
GET    /admin/api/v1/maf/events/ws                        — WebSocket stream
POST   /admin/api/v1/maf/webhooks                        — create webhook
GET    /admin/api/v1/maf/webhooks                        — list webhooks
DELETE /admin/api/v1/maf/webhooks/{id}                   — delete webhook
POST   /admin/api/v1/maf/queues                          — create queue
GET    /admin/api/v1/maf/queues                          — list queues
POST   /admin/api/v1/maf/queues/{id}/members             — add member
POST   /admin/api/v1/maf/conferences                     — create conference
GET    /admin/api/v1/maf/conferences                     — list conferences
POST   /admin/api/v1/maf/scheduled-calls                 — schedule call
GET    /admin/api/v1/maf/scheduled-calls                 — list scheduled
POST   /admin/api/v1/maf/number-intelligence             — number lookup
GET    /admin/api/v1/maf/routing/intelligence             — routing scores
POST   /admin/api/v1/maf/call-flows                      — create flow
GET    /admin/api/v1/maf/call-flows                      — list flows
  ...and additional CRUD, identity, and infrastructure routes (90 total)
```

MAF provides 90 HTTP endpoints covering the full call lifecycle (create,
answer, reject, hangup, route, bridge, transfer, hold, unhold, DTMF),
media control (play/record/stop, RTPEngine offer/answer/delete), SIP message
inspection (headers, SDP, STIR/SHAKEN attestation, NAT status), presence and
registration awareness, CDR access, security (ban/unban), infrastructure CRUD
(routing rules, gateways, DIDs, dispatch sets), webhooks, queues, conferences,
scheduled calls, number intelligence, routing intelligence, call flows,
cluster health, runtime config, charging authorization, and custom application
events — all tenant-scoped with separate read/write bearer credentials.

Set `SIP_MAF_INBOUND_MODE=route` for full SDK-controlled routing where the
application decides where every call goes. Set `mode=b2bua` in the route
request to terminate both SIP legs locally. RFC 7118 WebSocket transport is
fully supported for SIP.js and JsSIP clients.

MAF credentials are separate from admin, carrier, control, and SIP-worker
credentials. Configure a write token, an optional read-only token, and the
process tenant in the admin environment:

```sh
export SIP_MAF_API_TOKEN="$(openssl rand -hex 32)"
export SIP_MAF_API_READ_TOKEN="$(openssl rand -hex 32)"
export SIP_MAF_TENANT="default"
export SIP_MAF_INBOUND_MODE="control"
```

Put the admin listener behind HTTPS and, for production, a private mTLS edge.
The route still requires a MAF bearer token after mTLS. Keep tokens in
server-side services; do not place them in browser bundles, SIP headers, URLs,
logs, or user payloads.

#### curl: originate and observe a call

This example uses a write token to create a call, then a read-capable token to
read the resource and replay events. The same `Idempotency-Key` safely
retries the create request; reusing it with a different body returns `409`.

```sh
MAF_BASE_URL="${MAF_BASE_URL:-https://proxy.example.net/admin}"
MAF_WRITE_TOKEN="${SIP_MAF_API_TOKEN:?set SIP_MAF_API_TOKEN in the admin environment}"
MAF_READ_TOKEN="${SIP_MAF_API_READ_TOKEN:-$MAF_WRITE_TOKEN}"

RECEIPT="$(curl --fail-with-body -sS -X POST "$MAF_BASE_URL/api/v1/maf/calls" \
  -H "Authorization: Bearer $MAF_WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: readme-call-20260729" \
  --data '{"from":"sip:alice@example.net","to":"sip:bob@example.net"}')"
printf '%s\n' "$RECEIPT"
CALL_ID="$(printf '%s' "$RECEIPT" | jq -r '.resource_id')"

curl --fail-with-body -sS \
  -H "Authorization: Bearer $MAF_READ_TOKEN" \
  "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID"

curl --fail-with-body -sS \
  -H "Authorization: Bearer $MAF_READ_TOKEN" \
  "$MAF_BASE_URL/api/v1/maf/events?cursor=0&limit=50"
```

#### curl: answer an inbound call

Enable inbound ownership on the SIP worker with `SIP_MAF_INBOUND_MODE=control`.
After the authenticated INVITE appears as a `ringing` call, answer it with
bounded SDP. The command is asynchronous; observe the call resource or event
stream for the `answered` transition.

```sh
curl --fail-with-body -sS -X POST \
  "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/answer" \
  -H "Authorization: Bearer $MAF_WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: answer-$CALL_ID" \
 --data '{"answer_sdp":"v=0\r\no=- 1 1 IN IP4 <media-address>\r\ns=MAF\r\nt=0 0\r\nm=audio 4000 RTP/AVP 0\r\n"}'
```

The SIP worker owns dialog tags, transaction recording, and SIP response
delivery. `calls.reject` is available while ringing; `calls.hangup` sends
`487` before answer and a worker-owned `BYE` after answer. The default inbound
mode is `disabled`, preserving normal proxy routing.

The receipt has schema `madis.maf.command-receipt.v1` and includes the
`command_id`, `status`, `resource_id`, and `trace_id`. Persist the event cursor
only after durable application processing, and deduplicate by event ID when a
consumer reconnects.

#### JavaScript/TypeScript: server-side command client

```js
const baseUrl = process.env.MAF_BASE_URL ?? "https://proxy.example.net/admin";
const token = process.env.SIP_MAF_API_TOKEN;
if (!token) throw new Error("SIP_MAF_API_TOKEN is required");

const response = await fetch(`${baseUrl}/api/v1/maf/calls`, {
  method: "POST",
  headers: {
    Authorization: `Bearer ${token}`,
    "Content-Type": "application/json",
    "Idempotency-Key": "js-call-20260729",
  },
  body: JSON.stringify({
    from: "sip:alice@example.net",
    to: "sip:bob@example.net",
  }),
});

const receipt = await response.json();
if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(receipt)}`);
console.log(receipt);
```

#### Go: server-side command client

```go
package main

import (
    "bytes"
    "encoding/json"
    "fmt"
    "net/http"
    "os"
)

func main() {
    baseURL := os.Getenv("MAF_BASE_URL")
    if baseURL == "" { baseURL = "https://proxy.example.net/admin" }
    payload, _ := json.Marshal(map[string]string{
        "from": "sip:alice@example.net",
        "to":   "sip:bob@example.net",
    })

    req, _ := http.NewRequest(http.MethodPost,
        baseURL+"/api/v1/maf/calls", bytes.NewReader(payload))
    req.Header.Set("Authorization", "Bearer "+os.Getenv("SIP_MAF_API_TOKEN"))
    req.Header.Set("Content-Type", "application/json")
    req.Header.Set("Idempotency-Key", "go-call-20260729")

    res, err := http.DefaultClient.Do(req)
    if err != nil { panic(err) }
    defer res.Body.Close()

    var receipt map[string]any
    _ = json.NewDecoder(res.Body).Decode(&receipt)
    if res.StatusCode < 200 || res.StatusCode >= 300 {
        panic(fmt.Sprintf("MAF returned %d: %v", res.StatusCode, receipt))
    }
    fmt.Printf("%v\n", receipt)
}
```

MAF is a bounded command/event contract, not a generic code-execution or raw
SIP injection API. The HTTP boundary and opt-in inbound answer path are enabled
now; the bearer-authenticated MAF event WebSocket is available at
`/api/v1/maf/events/ws`, and bridge/media ownership is wired through the
documented worker and external-module boundaries. Independent production
interoperability evidence remains follow-up work. Read the complete contract in [`api/maf.md`](api/maf.md), the
machine-readable schema in [`api/maf.openapi.yaml`](api/maf.openapi.yaml), and
deployment guidance in [`docs/integrations.md`](docs/integrations.md) and
[`docs/configuration.md`](docs/configuration.md).

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

The supported source entry point is [`main.mko`](main.mko). [`sipproxy_full.mko`](sipproxy_full.mko) is a legacy monolithic reference and is not the deployment target. The codebase is pure Mako with no C bridge code; all composite-key maps, UDP reuseport, TLS server pool, base64url, and JWT custom header support are Mako builtins. Tests run without linking any C code. Builds and CI require Makori `0.6.5` or later with its matching runtime; do not mix compiler/runtime versions when generating native C.

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko madis

MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

The CI script checks Mako syntax/lint, Mako tests, native links, schemas, shell syntax, Python SDK compilation, and the default HSS/media adapter tests. The current suite totals 150 tests (45 Mako test files with 1507 assertions + 56 Python MAF SDK + 39 lab + 10 media). It does not replace external SIP, IMS, Diameter, media, or carrier interoperability testing. See [`docs/testing.md`](docs/testing.md) for opt-in wire, worker-backed, Docker, load, and recovery checks.
