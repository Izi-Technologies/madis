# MADIS Application Fabric

The **MADIS Application Fabric (MAF)** is MADIS’s language-neutral application
surface. External services written in Go, JavaScript/TypeScript, Python, or
another language can observe bounded communication resources and submit
authenticated commands without writing Mako, SQL, SIP bytes, or worker memory.

## Contract status

The MAF HTTP surface is enabled in the standalone admin process. It persists
calls, channels, bridges, media operations, commands, per-call header policy,
and replayable events in PostgreSQL. The machine-readable contract is
[`maf.openapi.yaml`](maf.openapi.yaml).

Mutating requests are durable command-acceptance boundaries: `202` means that
MADIS accepted the command for asynchronous worker processing, not that a SIP
dialog has already changed. The SIP worker remains the owner of signaling
state. The worker executor sends outbound `calls.create` INVITEs, handles
early-dialog reject/hangup with CANCEL, sends confirmed-dialog BYE, and
synchronizes SIP response states back to MAF. With
`SIP_MAF_INBOUND_MODE=control`, an authenticated initial INVITE becomes a
tenant-scoped MAF call and `calls.answer` can send a validated `200 OK`
containing `answer_sdp`. Bridge commands now create durable,
tenant-owned relationships after the call is answered. Media commands are
dispatched to the configured signed external `media` or `recording` module
and complete only after a valid module response; without that backend they
fail explicitly.

The optional per-call header policy route is also worker-owned. It can add,
set, remove, copy, or move non-identity SIP headers on bounded outbound and
inbound messages while framing, routing, authentication, and dialog identity
headers remain protected.

The WebSocket event subscription is available at
`/admin/api/v1/maf/events/ws`. It supports call-scoped filtering
(`?call_id=...`), event-type filtering (`?event_type=...`), adaptive poll
backoff (50ms when events flow, up to 2s when idle), and 30-second heartbeat
frames. A PostgreSQL `NOTIFY` trigger fires on every event insert; when the
runtime adds `sql_listen` support, the poll interval drops to near-zero.

The protobuf file remains a language-neutral shape description and Madis does
not expose a separate built-in gRPC listener.
[`madis-maf.proto`](madis-maf.proto) describes that language-neutral target.

Existing carrier/control APIs, signed live SIP application/module contracts,
durable billing events, and reference clients remain supported interfaces.

## Enabled HTTP routes

The admin base URL is `/admin` by default:

```text
POST /admin/api/v1/maf/calls
GET  /admin/api/v1/maf/calls/{call_id}
POST /admin/api/v1/maf/calls/{call_id}/answer
POST /admin/api/v1/maf/calls/{call_id}/reject
POST /admin/api/v1/maf/calls/{call_id}/hangup
POST /admin/api/v1/maf/calls/{call_id}/bridges
POST /admin/api/v1/maf/calls/{call_id}/media
POST /admin/api/v1/maf/calls/{call_id}/headers
GET  /admin/api/v1/maf/events?cursor=...&event_type=...&call_id=...
GET  /admin/api/v1/maf/events/ws?cursor=...&event_type=...&call_id=...
```

Read routes use `SIP_MAF_API_READ_TOKEN`. The write token also permits reads:

```http
Authorization: Bearer <MAF token>
```

Mutating routes require a valid write token and an `Idempotency-Key` header or
body `command_id`. The key is bound to a request hash; reusing it with a
different body returns `409`. Commands are tenant-scoped by the
`SIP_MAF_TENANT` process setting, bounded to 64 KiB JSON, and protected by
optimistic call-version checks.

Inbound call control is opt-in. Set `SIP_MAF_INBOUND_MODE=control` on the SIP
worker to stop an authenticated initial INVITE at the MAF boundary and publish
it as a ringing call. The answer command must include a bounded SDP answer in
`answer_sdp`; the worker validates the body, adds its own dialog tag,
records the SIP server transaction, and sends the response. The default mode is
`disabled`, which preserves normal proxy routing.

### Inbound answer lifecycle

Inbound control is owned by the SIP worker and is deliberately narrow:

1. An authenticated initial INVITE is persisted as a tenant-scoped `ringing`
   call and emits `call.created`.
2. The application reads the call resource or event stream and submits
   `POST /admin/api/v1/maf/calls/{call_id}/answer` with `answer_sdp`.
3. The worker validates the bounded SDP, creates the local dialog tag, records
   the server transaction, sends `200 OK`, and transitions the call to
   `answered`.
4. `calls.reject` sends a final response while the call is ringing;
   `calls.hangup` sends `487` before answer or a worker-owned `BYE` after
   answer. Remote `ACK`, `BYE`, and `CANCEL` messages remain SIP-worker state.

Example answer request:

```sh
curl --fail-with-body -sS -X POST \
  "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/answer" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: answer-$CALL_ID" \
 --data '{"answer_sdp":"v=0\r\no=- 1 1 IN IP4 <media-address>\r\ns=MAF\r\nt=0 0\r\nm=audio 4000 RTP/AVP 0\r\n"}'
```

This path currently relies on the worker's SIP server-transaction and reply
routing support. Validate TCP, TLS, WS, and WSS behavior in the target
deployment before enabling inbound control broadly.

The bridge route accepts only 2–8 unique channel IDs that belong to the
tenant-scoped call and exposes the resulting bridge in the call resource.
Media operations are limited to `play`, `record`, `stop`, `pause`, and
`resume`. `play`, `record`, and `stop` use the configured `media` module;
`pause` and `resume` use the configured `recording` module. Configure the
signed module dispatcher with `SIP_MODULE_URL`, `SIP_MODULE_TOKEN`, and the
corresponding names in `SIP_MODULES`. Event cursors are numeric and event
pages are capped at 100 records.

The WebSocket route uses the same MAF bearer credentials as the HTTP event
route. Each text frame is a replayable event page. Clients must persist the
last successfully processed `next_cursor` and reconnect with that cursor.
The stream is read-only. Heartbeat frames (`"heartbeat": true`) are sent
every 30 seconds; clients that receive no data and no heartbeat should
reconnect. Dead-client detection uses `io_read_ready` polling.

Both HTTP and WebSocket event routes support `call_id` filtering to scope
the subscription to a single call.

## Application model

MAF applications work with bounded resources:

- `calls` — the logical communication session;
- `channels` — SIP legs or other participating endpoints;
- `bridges` — relationships between channels;
- `media` — bounded media operations;
- `events` — replayable, tenant-scoped state and command notifications.

Applications observe events, apply business logic, and submit commands. They
do not execute SQL, inject SIP, mutate worker memory, or upload code.

## Event envelope

Events are versioned and replayable:

```json
{
  "schema": "madis.maf.event.v1",
  "event_id": "evt_01J...",
  "event_type": "call.answered",
  "event_version": 1,
  "call_id": "call_01J...",
  "channel_id": "chan_01J...",
  "sequence": 42,
  "occurred_at": "2026-07-29T12:00:00Z",
  "trace_id": "trace_01J...",
  "payload": {}
}
```

Clients commit their cursor only after durable processing, reconnect from that
cursor, and deduplicate by `event_id`. The HTTP event route provides
replay/cursor semantics. The billing event outbox has a separate acknowledgement
endpoint at `/api/v1/billing/events/ack`.

Known event types:

| Event type | Emitted when |
| --- | --- |
| `call.created` | New call inserted (outbound originate or inbound control) |
| `call.ringing` | Early-dialog provisional response received |
| `call.answered` | 2xx received or inbound answer sent |
| `call.ended` | BYE, CANCEL, or terminal response completed |
| `call.failed` | Call failed (timeout, rejection, transport error) |
| `command.accepted` | Command inserted into the command table |
| `command.completed` | Worker finished executing the command |
| `command.failed` | Worker execution failed |
| `bridge.created` | Bridge relationship created between channels |
| `media.completed` | Media operation completed successfully |
| `media.failed` | Media operation failed |

## Security boundary

- Put the admin listener behind HTTPS; use TLS 1.3 and mutual TLS at the
  private reverse proxy or service mesh when required.
- Keep MAF credentials separate from admin, carrier, control, and SIP-worker
  credentials. A client certificate alone is not authorization: the current
  admin process still requires a MAF bearer credential after edge mTLS.
- Use short-lived edge-issued credentials in production. The local route
  implementation accepts separate bounded read/write bearer secrets from
  `SIP_MAF_API_READ_TOKEN` and `SIP_MAF_API_TOKEN`.
- Bind every request to the configured tenant. Do not put bearer credentials in
  browser bundles, SIP headers, URLs, logs, or application payloads.
- Apply rate limits, quotas, token rotation, audit logging, and certificate or
  issuer policy at the private edge. The admin process enforces route,
  credential class, body-size, identifier, idempotency, version, and resource
  ownership checks.

MAF private keys and privileged tokens stay in server-side services. Browser
clients should call an application-owned backend, which then calls MAF.

## SDK clients

Official MAF SDKs are maintained in [`../sdk/maf/`](../sdk/maf/):

| Language | Path | Features |
| --- | --- | --- |
| Python | `sdk/maf/python/madis_maf.py` | stdlib-only, typed, 150 LOC |
| Go | `sdk/maf/go/madismaf.go` | net/http, context-aware, 170 LOC |
| TypeScript | `sdk/maf/typescript/madis-maf.ts` | native fetch, typed interfaces, 350 LOC |
| Erlang | `sdk/maf/erlang/madis_maf.erl` | httpc/inets, stdlib-only, 120 LOC |
| JavaScript | `sdk/maf/javascript/madis-maf.mjs` | ESM, fetch-based, 73 LOC |

All SDKs:
- Send `X-MAF-Version: 0.5.0` on every request
- Auto-generate idempotency keys when not provided
- Enforce the 64 KiB body limit client-side
- Validate token length (16–512 characters)
- Include all 9 operations: create, get, answer, reject, hangup, bridge, media, headers, events

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

## Implementation boundary

The HTTP and WebSocket surfaces are implemented in the standalone admin process.
The protobuf file remains a language-neutral shape description; integrations
that require gRPC can place a translating service beside the HTTP API while
preserving the same tenant, bearer-token, idempotency, cursor, and asynchronous
receipt semantics. Inbound MAF control is currently limited to the SIP
transports that the worker can route through its server transaction/reply path;
deployments should validate TCP/TLS/WS/WSS behavior before enabling it broadly.
Integrations must treat command receipts as asynchronous acceptance and
observe the call or event resources for progress.

## Worker-side improvements

The SIP worker's MAF integration includes:

- **Adaptive poll backoff**: idle workers back off from 100ms to 2s between
  command polls; resets to 100ms when work is found.
- **Transport-aware outbound calls**: `calls.create` derives the SIP transport
  from the target URI (`sips:` → TLS, `transport=tcp` → TCP). The Via header,
  CANCEL, and BYE use the same transport.
- **Atomic claim**: command claiming uses a single `UPDATE ... WHERE status = 'accepted'`
  instead of UPDATE + SELECT.
- **Single-query state transitions**: `maf_worker_call_state` does one UPDATE
  instead of SELECT + UPDATE.
- **Event ID uniqueness**: payload hash included in the event ID seed to prevent
  collision when two events of the same type fire in the same millisecond.
- **Non-MAF fast path**: `maf_worker_sync_sip` skips the DB query for Call-IDs
  that don't match MAF patterns, eliminating a JOIN per SIP message.
