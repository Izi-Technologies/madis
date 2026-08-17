# MADIS Application Fabric

The **MADIS Application Fabric (MAF)** is MADIS's language-neutral application
surface. External services written in Go, JavaScript/TypeScript, Python, Erlang,
or another language can observe bounded communication resources and submit
authenticated commands without writing Mako, SQL, SIP bytes, or worker memory.

## Contract status

The MAF HTTP surface is enabled in the standalone admin process. It persists
calls, channels, bridges, media operations, commands, per-call header policy,
and replayable events in PostgreSQL. The machine-readable contract is
[`maf.openapi.yaml`](maf.openapi.yaml).

Mutating requests are durable command-acceptance boundaries: `202` means that
MADIS accepted the command for asynchronous worker processing, not that a SIP
dialog has already changed. The SIP worker remains the owner of signaling
state.

## Operations

### Call lifecycle

| Operation | What it does |
| --- | --- |
| `calls.create` | Originate an outbound INVITE to a SIP URI |
| `calls.answer` | Send 200 OK with `answer_sdp` to an inbound caller |
| `calls.reject` | Send a final error response (486/603) while ringing |
| `calls.hangup` | CANCEL (ringing) or BYE (answered) to end the call |
| `calls.route` | Forward an inbound INVITE to a target, bypassing built-in routing |
| `calls.bridge` | Create a durable bridge between 2-8 channels |
| `calls.transfer` | Blind (REFER) or attended (REFER+Replaces) call transfer |
| `calls.hold` | Place a call on hold (re-INVITE with sendonly) |
| `calls.unhold` | Resume a held call (re-INVITE with sendrecv) |
| `calls.dtmf` | Send a DTMF digit via SIP INFO (dtmf-relay) |
| `calls.media` | Play, record, stop, pause, resume via external media module |
| `calls.headers` | Set per-call SIP header policy (add/set/remove/copy/move) |
| `calls.rtp` | Direct RTPEngine control: offer, answer, delete, query |

### SDK-controlled routing

With `SIP_MAF_INBOUND_MODE=control` or `SIP_MAF_INBOUND_MODE=route`, an
authenticated initial INVITE becomes a tenant-scoped MAF call. The SDK can
then decide where to route it using `calls.route`:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/route" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: route-$CALL_ID" \
  --data '{"target":"sip:dest@gateway.example.com","transport":"udp"}'
```

This completely bypasses the built-in routing engine (dialplan, routing rules,
dispatch sets, LCR). The SDK makes the routing decision based on its own
business logic, external databases, or real-time signals.

Set `"mode": "b2bua"` in the route request to terminate both SIP legs locally
instead of proxy forwarding. Requires `SIP_B2BUA=1`.

### RTPEngine media control

The `calls.rtp` operation gives the SDK direct control over the RTPEngine
media relay:

| Action | Request fields | Description |
| --- | --- | --- |
| `offer` | `sdp`, `from_tag`, `flags?` | Send SDP to RTPEngine, get rewritten SDP with relay addresses |
| `answer` | `sdp`, `from_tag`, `to_tag`, `flags?` | Complete media session with answerer's SDP |
| `delete` | — | Tear down the RTP relay session |
| `query` | — | Check current RTP state for the call |

Per-call flags override the global RTPEngine profile (`ICE=force`, `DTLS=passive`, etc.):

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/rtp" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rtp-offer-$CALL_ID" \
  --data '{"action":"offer","sdp":"v=0\r\n...","from_tag":"abc123","flags":"ICE=force DTLS=passive"}'
```

### SIP message inspection

`GET /admin/api/v1/maf/calls/{call_id}/sip` returns full SIP-level details
from the call's `application_data`. For inbound calls:

```json
{
  "sip_call_id": "abc@192.0.2.10",
  "direction": "inbound",
  "transport": "UDP",
  "nat": "true",
  "source_ip": "203.0.113.10",
  "source_port": 5060,
  "request_uri": "sip:+15551234567@proxy.example.com",
  "user_agent": "Ooma/2.3.0",
  "p_asserted_identity": "sip:+15559876543@carrier.example.com",
  "identity": "<base64-passport>",
  "identity_verified": "true",
  "sdp": "v=0\r\n..."
}
```

When the call is answered, the remote party's details are merged:

```json
{
  "remote_sdp": "v=0\r\n...",
  "remote_contact": "sip:bob@203.0.113.20:5060",
  "remote_user_agent": "Ooma/2.3.0"
}
```

This gives SDKs full visibility into caller identity, STIR/SHAKEN attestation,
codec negotiation, and NAT topology without parsing raw SIP.

### Registration and presence

```sh
# List all online users
curl "$MAF_BASE_URL/api/v1/maf/presence" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Check if a specific user is online
curl "$MAF_BASE_URL/api/v1/maf/presence/alice@example.com" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# List active SIP registration bindings
curl "$MAF_BASE_URL/api/v1/maf/registrations?aor=alice@example.com&limit=50" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

The presence endpoint returns AOR, contact count, and last-seen timestamp.
The per-user endpoint returns all active contacts with transport, source IP,
expiry, and update time. The registrations endpoint returns raw binding data.

### Call detail records

```sh
curl "$MAF_BASE_URL/api/v1/maf/cdr?call_id=call-abc&limit=10" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

Returns caller, callee, status, gateway, SIP code, timestamps, and duration.

### Security control

SDKs can manage IP bans programmatically:

```sh
# List active bans
curl "$MAF_BASE_URL/api/v1/maf/security/bans" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Ban an IP (write scope required)
curl -X POST "$MAF_BASE_URL/api/v1/maf/security/bans" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"source_ip":"192.0.2.99","reason":"abuse","permanent":"false","duration_min":60}'

# Unban an IP
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/security/bans/192.0.2.99" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Routing rules

Full CRUD for the routing rules engine:

```sh
# List all routing rules
curl "$MAF_BASE_URL/api/v1/maf/routing/rules" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create a routing rule
curl -X POST "$MAF_BASE_URL/api/v1/maf/routing/rules" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"match_prefix":"+1212","action":"route:nyc-gateway","priority":5,"description":"NYC local calls"}'

# Delete a routing rule
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/routing/rules/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

Rules support all match conditions (prefix, caller, source IP, time-of-day,
day-of-week, ANI group) and actions (route, dispatch, reject, redirect,
forward, lcr, failover, b2bua, continue).

### Gateways

```sh
# List gateways
curl "$MAF_BASE_URL/api/v1/maf/gateways" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create/update a gateway
curl -X POST "$MAF_BASE_URL/api/v1/maf/gateways" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"carrier-a","address":"10.0.1.100","port":5060,"transport":"UDP"}'
```

### DIDs (inbound numbers)

```sh
# List DIDs
curl "$MAF_BASE_URL/api/v1/maf/dids" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Map a DID to a user
curl -X POST "$MAF_BASE_URL/api/v1/maf/dids" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"number":"+15551234567","destination_user":"alice","description":"Main line"}'
```

### Dispatch sets (load balancing)

```sh
# List dispatch sets with members
curl "$MAF_BASE_URL/api/v1/maf/dispatch-sets" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create a dispatch set
curl -X POST "$MAF_BASE_URL/api/v1/maf/dispatch-sets" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"us-east-carriers","algorithm":"round-robin"}'
```

Algorithms: `round-robin`, `weight`, `priority`, `hash`, `hash-user`, `broadcast`.

### Cluster health

```sh
curl "$MAF_BASE_URL/api/v1/maf/cluster" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

Returns all cluster nodes with ID, address, port, region, status
(`active`/`stale`), last heartbeat, and start time.

### Runtime config

```sh
# Read all config
curl "$MAF_BASE_URL/api/v1/maf/config" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Set a config value
curl -X POST "$MAF_BASE_URL/api/v1/maf/config" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"key":"security_max_auth_failures","value":"10","description":"Raised threshold"}'
```

Config writes use an **allowlist** — only these key prefixes can be set via MAF:
- `rtpengine_*` — RTPEngine configuration
- `security_*` — security thresholds, ban durations
- `stir_shaken_enabled`, `stir_shaken_attestation`, `stir_shaken_cert_url`, `stir_shaken_mode`

All other keys (TLS paths, credentials, DB URLs, private keys) are blocked
with `403`.

### Charging authorization

SDKs can authorize or deny charges for MAF-controlled calls:

```sh
# Authorize charge
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/charge" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"

# Deny charge
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/charge-deny" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

The decision is stored in the call's `application_data` as
`charge_authorized: true/false` and can be read via the call resource or
SIP inspection endpoint.

### Database independence

MAF can use its own PostgreSQL database via `SIP_MAF_DB_URL`, separate from
the core SIP proxy database (`SIP_DB_URL`). This lets operators:

- Isolate MAF state (calls, events, commands) from proxy tables
- Point MAF at a different database cluster for independent scaling
- Run MAF without any core SIP database when using SDK-controlled routing

If `SIP_MAF_DB_URL` is not set, MAF uses `SIP_DB_URL` as before.

### NAT awareness

MAF calls include NAT metadata in creation events. Inbound INVITEs are
NAT-fixed (Contact URI + SDP c=/o= rewrite) before caching. Outbound 200 OK
responses have their SDP NAT-fixed before storage. The SDK sees clean,
routable addresses regardless of endpoint topology.

### Custom application events

SDKs can publish their own events into the MAF event stream. Custom events
must use the `app.` prefix:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/events" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"event_type":"app.ivr.menu_selected","call_id":"call-abc","payload":"{\"menu\":\"sales\"}"}'
```

Custom events appear in the same event stream and WebSocket subscription as
system events. The `call_id` must reference an existing call in the tenant.

## Enabled HTTP routes

```text
POST   /admin/api/v1/maf/calls                          — create call
GET    /admin/api/v1/maf/calls/{call_id}                 — get call
POST   /admin/api/v1/maf/calls/{call_id}/answer          — answer
POST   /admin/api/v1/maf/calls/{call_id}/reject          — reject
POST   /admin/api/v1/maf/calls/{call_id}/hangup          — hangup
POST   /admin/api/v1/maf/calls/{call_id}/route           — SDK routing
POST   /admin/api/v1/maf/calls/{call_id}/bridges         — bridge channels
POST   /admin/api/v1/maf/calls/{call_id}/transfer        — blind/attended transfer
POST   /admin/api/v1/maf/calls/{call_id}/hold            — hold
POST   /admin/api/v1/maf/calls/{call_id}/unhold          — unhold
POST   /admin/api/v1/maf/calls/{call_id}/dtmf            — send DTMF
POST   /admin/api/v1/maf/calls/{call_id}/media           — media control
POST   /admin/api/v1/maf/calls/{call_id}/headers         — header policy
POST   /admin/api/v1/maf/calls/{call_id}/rtp             — RTPEngine control
GET    /admin/api/v1/maf/calls/{call_id}/sip             — SIP inspection
POST   /admin/api/v1/maf/calls/{call_id}/charge          — authorize charge
POST   /admin/api/v1/maf/calls/{call_id}/charge-deny     — deny charge
GET    /admin/api/v1/maf/registrations                    — active registrations
GET    /admin/api/v1/maf/presence                         — online users
GET    /admin/api/v1/maf/presence/{aor}                   — user presence
GET    /admin/api/v1/maf/cdr                              — call detail records
GET    /admin/api/v1/maf/security/bans                    — active bans
POST   /admin/api/v1/maf/security/bans                   — ban IP
DELETE /admin/api/v1/maf/security/bans/{ip}               — unban IP
GET    /admin/api/v1/maf/routing/rules                    — list routing rules
POST   /admin/api/v1/maf/routing/rules                   — create routing rule
DELETE /admin/api/v1/maf/routing/rules/{id}               — delete routing rule
GET    /admin/api/v1/maf/gateways                         — list gateways
POST   /admin/api/v1/maf/gateways                        — create/update gateway
GET    /admin/api/v1/maf/dids                             — list DIDs
POST   /admin/api/v1/maf/dids                            — create/update DID
GET    /admin/api/v1/maf/dispatch-sets                    — list dispatch sets
POST   /admin/api/v1/maf/dispatch-sets                   — create dispatch set
GET    /admin/api/v1/maf/cluster                          — cluster health
GET    /admin/api/v1/maf/config                           — read config
POST   /admin/api/v1/maf/config                          — set config
GET    /admin/api/v1/maf/events                           — event replay
POST   /admin/api/v1/maf/events                          — publish custom event
GET    /admin/api/v1/maf/events/ws                        — WebSocket subscription
```

## Authentication and tenant scoping

Read routes use `SIP_MAF_API_READ_TOKEN`. Write routes require
`SIP_MAF_API_TOKEN` (which also permits reads):

```http
Authorization: Bearer <MAF token>
```

Mutating call commands require an `Idempotency-Key` header or body
`command_id`. The key is bound to a request hash; reusing it with a
different body returns `409`. Commands are tenant-scoped by the
`SIP_MAF_TENANT` process setting.

### Tenant isolation

All MAF resources are scoped to the configured tenant (`SIP_MAF_TENANT`):

| Resource | Tenant-scoped | Notes |
| --- | --- | --- |
| Calls, channels, bridges, media, events, commands | Yes | Per-call state |
| Routing rules, gateways, DIDs, dispatch sets | Yes | Infrastructure per tenant |
| Registrations, presence | Yes | Per-tenant registration bindings |
| Config | Yes | Per-tenant config keys |
| Cluster nodes | No | Platform-level health monitoring |
| Security bans | No | Platform-level; IP bans protect all tenants |
| CDR | No | Filterable by call_id; shared audit trail |

A MAF read token in tenant A cannot see tenant B's gateways, routing rules,
registrations, or call state. Write operations insert with the configured
tenant and delete/update only within it.

## Inbound call modes

| Mode | Behavior |
| --- | --- |
| `disabled` | Default. Normal proxy routing; MAF does not intercept INVITEs. |
| `control` | Intercept initial INVITEs. SDK can answer/reject. Built-in routing available for non-MAF calls. |
| `route` | Intercept initial INVITEs. SDK must route via `calls.route`. Built-in routing bypassed. |

### Inbound answer lifecycle

1. An authenticated initial INVITE is persisted as a tenant-scoped `ringing`
   call and emits `call.created` with full SIP metadata (caller, callee,
   User-Agent, P-Asserted-Identity, STIR/SHAKEN Identity, SDP, NAT status).
2. The application reads the call resource, SIP inspection endpoint, or event
   stream and submits `calls.answer` with `answer_sdp`.
3. The worker validates the SDP, creates the dialog tag, records the server
   transaction, sends `200 OK`, and transitions to `answered`.
4. `calls.reject` sends a final response while ringing; `calls.hangup` sends
   `487` before answer or `BYE` after. Remote ACK/BYE/CANCEL remain worker-owned.

## Event system

Events are versioned, replayable, and durable:

```json
{
  "schema": "madis.maf.event.v1",
  "event_id": "evt_01J...",
  "event_type": "call.answered",
  "event_version": 1,
  "call_id": "call_01J...",
  "sequence": 42,
  "occurred_at": "2026-07-29T12:00:00Z",
  "trace_id": "trace_01J...",
  "payload": {}
}
```

### Event types

| Event type | Emitted when | Key payload fields |
| --- | --- | --- |
| `call.created` | New call (outbound or inbound) | `direction`, `nat`, `source_ip` |
| `call.ringing` | Provisional response | `sip_code`, `remote_party` |
| `call.answered` | 2xx received/sent | `sip_code`, `remote_sdp`, `remote_contact` |
| `call.routed` | SDK routed a call | `target`, `transport` |
| `call.transferring` | Transfer initiated | `type` (blind/attended) |
| `call.held` | Call placed on hold | — |
| `call.unheld` | Call resumed | — |
| `call.dtmf` | DTMF digit sent | `digit`, `duration` |
| `call.ended` | BYE/CANCEL/terminal | `ended_by`, `duration_ms`, `sip_code` |
| `call.failed` | Call failed | `sip_code`, `sip_reason` |
| `command.accepted` | Command queued | `operation`, `command_id` |
| `command.completed` | Worker finished | `command_id` |
| `command.failed` | Worker failed | `error_code`, `error_message` |
| `bridge.created` | Bridge created | `bridge_id`, `mode` |
| `media.completed` | Media op done | `media_id`, `operation` |
| `media.failed` | Media op failed | `error_code` |
| `rtp.offer` | RTPEngine offer OK | `action` |
| `rtp.answer` | RTPEngine answer OK | `action` |
| `rtp.deleted` | RTP session torn down | — |
| `rtp.query` | RTP state queried | `state` |
| `app.*` | Custom application events | User-defined |

### Rich event payloads

State transition events include SIP-level detail:

```json
{
  "call_id": "call-abc",
  "state": "ended",
  "source": "sip-worker",
  "ended_by": "BYE",
  "duration_ms": 45230,
  "sip_code": 200
}
```

### WebSocket event streaming

`GET /admin/api/v1/maf/events/ws` provides real-time event streaming over
WebSocket. Bearer-authenticated, read-only, with the `sip` subprotocol.

**Filters:** `?call_id=...`, `?event_type=...`, `?cursor=...`

**Behavior:**
- Each text frame is a JSON event page (same schema as the HTTP endpoint)
- Adaptive poll: 50ms when events flow, backs off to 2s when idle
- 30-second heartbeat frames (`"heartbeat": true`)
- Resume from `next_cursor` on reconnect — no event loss
- Dead-client detection via read polling

**SDK streaming (HTTP long-poll — no WebSocket dependency):**

```python
# Python — blocking generator
for event in client.subscribe(event_type="call.answered"):
    print(event["call_id"], event["payload"])
```

```typescript
// TypeScript — async generator
for await (const event of client.subscribe({ eventType: "call.answered" })) {
  console.log(event.call_id);
}
```

```javascript
// JavaScript — async generator
for await (const event of client.subscribe({ eventType: "call.ended" })) {
  console.log(event.payload.duration_ms);
}
```

```go
// Go — channel-based with context cancellation
ch := make(chan map[string]any, 100)
go client.Subscribe(ctx, 0, "call.answered", "", ch)
for evt := range ch {
    fmt.Println(evt["call_id"])
}
```

**Direct WebSocket (for SIP.js, JsSIP, or custom WebSocket clients):**

```python
# Python — build the WSS URL for websockets library
url = client.ws_url(event_type="call.created")
# → wss://proxy.example.com/admin/api/v1/maf/events/ws?cursor=0&event_type=call.created
```

```typescript
// TypeScript/JavaScript — native WebSocket
const ws = new WebSocket(client.wsUrl({ eventType: "call.answered" }));
ws.onmessage = (e) => {
  const page = JSON.parse(e.data);
  for (const event of page.events) {
    console.log(event.event_type, event.call_id);
  }
};
```

```go
// Go — gorilla/websocket
url := client.WSUrl(0, "call.answered", "")
// Connect with Authorization header
```

## SIP over WebSocket (RFC 7118)

Madis fully implements RFC 7118 for SIP-over-WebSocket transport, compatible
with SIP.js, JsSIP, and other WebRTC SIP stacks:

**Handshake (§4):**
- Standard HTTP Upgrade with `Sec-WebSocket-Key` / `Sec-WebSocket-Accept`
- `Sec-WebSocket-Protocol: sip` echoed in 101 response
- Validates upgrade request structure before accepting

**Transport binding (§5):**
- Via header uses `SIP/2.0/WSS` transport parameter
- Responses to WSS-originated requests route back through WebSocket text
  frames (not raw TCP) — tracked per-transaction with transport type
- Connection-oriented: the proxy maintains the WebSocket association for the
  duration of the dialog

**Connection reuse (§6):**
- Server-side connection tracking stores transport type alongside FD
- `sip_forward_reply` checks transport: WSS connections use `ws_send_text`,
  TCP/TLS use `tcp_write_all`
- Both single-message and reassembly paths track WSS connections

**Security:**
- Per-IP connection limits enforced on WSS accept
- Connection counter properly decremented on cleanup
- PROXY protocol support for load balancer deployments
- Works with TLS termination at the edge (HAProxy/nginx → WSS)

**WebRTC integration:**
- RTPEngine auto-detects WebRTC SDP (ICE candidates, DTLS fingerprint, SAVPF)
- Applies `ICE=force DTLS=passive SDES-off rtcp-mux-offer rtcp-mux-accept`
  for WebRTC-to-SIP bridging
- SIP.js/JsSIP connect to `wss://<proxy>:<wss_port>` with subprotocol `sip`

**Configuration:**

```text
SIP_WSS_PORT=8443          # WebSocket listen port (default: 8443)
SIP_WSS_WORKERS=4          # Worker count
SIP_TLS_CERT=/path/cert    # TLS certificate (shared with SIP TLS)
SIP_TLS_KEY=/path/key      # TLS private key
```

SIP.js example:

```javascript
const ua = new JsSIP.UA({
  sockets: [new JsSIP.WebSocketInterface("wss://proxy.example.com:8443")],
  uri: "sip:alice@example.com",
  password: "secret"
});
ua.start();
```

## Security boundary

- Put the admin listener behind HTTPS with TLS 1.3.
- Keep MAF credentials separate from admin, carrier, and control credentials.
- Use short-lived edge-issued credentials in production.
- Config writes use an allowlist (`rtpengine_*`, `security_*`, select
  `stir_shaken_*`). All other config keys are blocked.
- Bind every request to the configured tenant.
- MAF private keys and privileged tokens stay in server-side services.

## SDK clients

Official MAF SDKs in [`../sdk/maf/`](../sdk/maf/):

| Language | Path |
| --- | --- |
| Python | `sdk/maf/python/madis_maf.py` |
| Go | `sdk/maf/go/madismaf.go` |
| TypeScript | `sdk/maf/typescript/madis-maf.ts` |
| JavaScript | `sdk/maf/javascript/madis-maf.mjs` |
| Erlang | `sdk/maf/erlang/madis_maf.erl` |

All SDKs: `X-MAF-Version: 0.7.0`, auto-generated idempotency keys, 64 KiB
body limit, 16-512 char token validation.

### SDK method reference

| Category | Operation | Python | Go | TypeScript | JS | Erlang |
| --- | --- | --- | --- | --- | --- | --- |
| **Calls** | Create | `create_call()` | `CreateCall()` | `createCall()` | `createCall()` | `create_call/4` |
| | Get | `get_call()` | `GetCall()` | `getCall()` | `getCall()` | `get_call/3` |
| | Answer | `answer_call()` | `AnswerCall()` | `answerCall()` | `answerCall()` | `answer_call/4` |
| | Reject | `reject_call()` | `RejectCall()` | `rejectCall()` | `rejectCall()` | `reject_call/4` |
| | Hangup | `hangup_call()` | `HangupCall()` | `hangupCall()` | `hangupCall()` | `hangup_call/3` |
| | Route | `route_call()` | `RouteCall()` | `routeCall()` | `routeCall()` | `route_call/4` |
| | Transfer | `transfer_call()` | `TransferCall()` | `transferCall()` | `transferCall()` | `transfer_call/4` |
| | Hold | `hold_call()` | `HoldCall()` | `holdCall()` | `holdCall()` | `hold_call/3` |
| | Unhold | `unhold_call()` | `UnholdCall()` | `unholdCall()` | `unholdCall()` | `unhold_call/3` |
| | DTMF | `send_dtmf()` | `SendDTMF()` | `sendDtmf()` | `sendDtmf()` | `send_dtmf/4` |
| | Bridge | `bridge_call()` | `BridgeCall()` | `bridgeCall()` | `bridgeCall()` | `bridge_call/4` |
| **Media** | Media | `media()` | `Media()` | `media()` | `media()` | `media/4` |
| | RTP | `rtp_control()` | `RTPControl()` | `rtpControl()` | `rtpControl()` | `rtp_control/4` |
| | Headers | `set_headers()` | `SetHeaders()` | `setHeaders()` | `setHeaders()` | `set_headers/4` |
| **Inspect** | SIP | `sip_inspect()` | `SIPInspect()` | `sipInspect()` | `sipInspect()` | `sip_inspect/3` |
| **Presence** | List | `presence()` | `Presence()` | `presence()` | `presence()` | `presence/2` |
| | User | `presence_user()` | `PresenceUser()` | `presenceUser()` | `presenceUser()` | `presence_user/3` |
| | Registrations | `registrations()` | `Registrations()` | `registrations()` | `registrations()` | `registrations/2` |
| **Records** | CDR | `cdr()` | `CDR()` | `cdr()` | `cdr()` | `cdr/2` |
| **Security** | Bans | `bans()` | `Bans()` | `bans()` | `bans()` | `bans/2` |
| | Ban IP | `ban_ip()` | `BanIP()` | `banIP()` | `banIP()` | `ban_ip/6` |
| | Unban IP | `unban_ip()` | `UnbanIP()` | `unbanIP()` | `unbanIP()` | `unban_ip/3` |
| **Routing** | Rules | `routing_rules()` | `RoutingRules()` | `routingRules()` | `routingRules()` | `routing_rules/2` |
| | Create rule | `create_routing_rule()` | `CreateRoutingRule()` | `createRoutingRule()` | `createRoutingRule()` | `create_routing_rule/3` |
| | Delete rule | `delete_routing_rule()` | `DeleteRoutingRule()` | `deleteRoutingRule()` | `deleteRoutingRule()` | `delete_routing_rule/3` |
| **Infra** | Gateways | `gateways()` | `Gateways()` | `gateways()` | `gateways()` | `gateways/2` |
| | Create GW | `create_gateway()` | `CreateGateway()` | `createGateway()` | `createGateway()` | `create_gateway/3` |
| | DIDs | `dids()` | `DIDs()` | `dids()` | `dids()` | `dids/2` |
| | Create DID | `create_did()` | `CreateDID()` | `createDID()` | `createDID()` | `create_did/3` |
| | Dispatch sets | `dispatch_sets()` | `DispatchSets()` | `dispatchSets()` | `dispatchSets()` | `dispatch_sets/2` |
| | Create set | `create_dispatch_set()` | `CreateDispatchSet()` | `createDispatchSet()` | `createDispatchSet()` | `create_dispatch_set/3` |
| **Cluster** | Nodes | `cluster()` | `Cluster()` | `cluster()` | `cluster()` | `cluster/2` |
| **Config** | Read | `config()` | `Config()` | `config()` | `config()` | `config/2` |
| | Set | `set_config()` | `SetConfig()` | `setConfig()` | `setConfig()` | `set_config/3` |
| **Charging** | Authorize | `charge_authorize()` | `ChargeAuthorize()` | `chargeAuthorize()` | `chargeAuthorize()` | `charge_authorize/3` |
| | Deny | `charge_deny()` | `ChargeDeny()` | `chargeDeny()` | `chargeDeny()` | `charge_deny/3` |
| **Events** | Publish | `publish_event()` | `PublishEvent()` | `publishEvent()` | `publishEvent()` | `publish_event/5` |
| | List | `events()` | `Events()` | `events()` | `events()` | `events/3` |
| | Subscribe | `subscribe()` | `Subscribe()` | `subscribe()` | `subscribe()` | — (use events/5) |
| | WS URL | `ws_url()` | `WSUrl()` | `wsUrl()` | `wsUrl()` | `ws_url/4` |

### Contract tests

56 Python tests in `sdk/maf/tests/` validate the SDK-to-OpenAPI contract:

- **OpenAPI contract** — route coverage, required fields, enum consistency, body limits, auth headers
- **Command lifecycle** — state machine (accepted→processing→completed|failed), staleness, idempotency
- **Cursor recovery** — ordering, resume-from-cursor, duplicate prevention, truncation, heartbeat
- **Load/backpressure** — 1000 rapid commands, 64KB boundary, 100-event pages
- **Tenant auth** — token validation, 401/403 handling, token never in URL or error messages

### Application examples

- `sdk/maf/examples/click_to_call.py` — CLI call originator with event polling
- `sdk/maf/examples/event_monitor.py` — streaming event consumer with reconnection

## Configuration

| Variable | Purpose |
| --- | --- |
| `SIP_MAF_API_TOKEN` | MAF write credential (also permits reads) |
| `SIP_MAF_API_READ_TOKEN` | MAF read-only credential |
| `SIP_MAF_TENANT` | Tenant namespace; defaults to `default` |
| `SIP_MAF_INBOUND_MODE` | `disabled` (default), `control`, or `route` |
| `SIP_MAF_DB_URL` | Separate PostgreSQL for MAF tables; falls back to `SIP_DB_URL` |
| `SIP_MAF_CONTACT_URI` | Override Contact URI in MAF-generated SIP responses |

## Worker-side implementation

- **Adaptive poll backoff**: 100ms→2s idle, resets on work
- **Transport-aware outbound**: derives transport from target URI scheme
- **Atomic claim**: single `UPDATE WHERE status='accepted'`
- **Single-query state transitions**: no SELECT+UPDATE
- **Event ID uniqueness**: payload hash tiebreaker for sub-millisecond collisions
- **Non-MAF fast path**: skips DB query for non-MAF Call-IDs
- **Rich event payloads**: SIP code, remote SDP, duration in state transitions
- **NAT-aware caching**: Contact + SDP rewritten before storage
- **B2BUA routing mode**: `calls.route` with `mode=b2bua` terminates both legs
- **RFC 7118 WSS transport**: `Sec-WebSocket-Protocol: sip` handshake,
  transport-aware response routing (WebSocket frames vs raw TCP),
  per-transaction transport tracking, per-IP connection limits on WSS
- **Tenant-scoped infrastructure**: routing rules, gateways, DIDs, dispatch
  sets, config, and registrations are all filtered by `SIP_MAF_TENANT`
