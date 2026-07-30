# MADIS Application Fabric

The **MADIS Application Fabric (MAF)** is MADIS’s language-neutral application
surface. External services written in Go, JavaScript/TypeScript, Python, or
another language can observe bounded communication resources and submit
authenticated commands without writing Mako, SQL, SIP bytes, or worker memory.

## Contract status

The first MAF HTTP surface is enabled in the standalone admin process. It
persists calls, channels, commands, and replayable events in PostgreSQL. The
machine-readable contract is [`maf.openapi.yaml`](maf.openapi.yaml).

Mutating requests are durable command-acceptance boundaries: `202` means that
MADIS accepted the command for asynchronous worker processing, not that a SIP
dialog has already changed. The SIP worker remains the owner of signaling
state. The worker executor sends outbound `calls.create` INVITEs, handles
early-dialog reject/hangup with CANCEL, sends confirmed-dialog BYE, and
synchronizes SIP response states back to MAF. With
`SIP_MAF_INBOUND_MODE=control`, an authenticated initial INVITE becomes a
tenant-scoped MAF call and `calls.answer` can send a validated `200 OK`
containing `answer_sdp`. Bridge and media commands are accepted into the
durable queue but finish with an explicit failed receipt until their
worker-owned executors are implemented.

Live WebSocket/gRPC subscriptions are separate follow-up surfaces;
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
GET  /admin/api/v1/maf/events?cursor=...&event_type=...
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
  --data '{"answer_sdp":"v=0\r\no=- 1 1 IN IP4 127.0.0.1\r\ns=MAF\r\nt=0 0\r\nm=audio 4000 RTP/AVP 0\r\n"}'
```

This path currently relies on the worker's SIP server-transaction and reply
routing support. Validate TCP, TLS, WS, and WSS behavior in the target
deployment before enabling inbound control broadly.

The bridge route accepts only 2–8 unique channel IDs that belong to the
tenant-scoped call. Media operations are limited to `play`, `record`, `stop`,
`pause`, and `resume`. Event cursors are numeric and event pages are capped at
100 records.

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
cursor, and deduplicate by `event_id`. The current HTTP event route provides
replay/cursor semantics; it does not expose a separate event acknowledgement
endpoint.

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

## Remaining implementation work

The repository now includes maintained Python, JavaScript, and Go reference
clients in [`../sdk/maf/`](../sdk/maf/), but the enabled HTTP boundary still
needs bridge/media ownership, live WebSocket/gRPC subscriptions, and sustained
interoperability/failure-injection evidence. Inbound MAF control is currently
limited to the SIP transports that the worker can route through its server
transaction/reply path; deployments should validate TCP/TLS/WS/WSS behavior
before enabling it broadly.
Integrations must treat command receipts as asynchronous acceptance and
observe the call or event resources for progress.
