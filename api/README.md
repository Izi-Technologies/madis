# Madis carrier integration API

Madis exposes a versioned machine API beside the WebUI:

| Endpoint | Purpose |
| --- | --- |
| `GET /admin/api/v1/capabilities` | Runtime and integration capability discovery |
| `GET /admin/api/v1/billing/events?limit=100` | Read pending events, at most 100 per request |
| `POST /admin/api/v1/billing/events` | Publish a carrier-defined JSON event |
| `POST /admin/api/v1/billing/events/ack?event_id=...` | Acknowledge after the consumer commits it |
| `GET /admin/api/v1/control/status` | Read the authenticated control surface |
| `GET /admin/api/v1/control/routing-rules` | List routing rules |
| `POST /admin/api/v1/control/routing-rules` | Create an allowlisted routing rule |
| `POST /admin/api/v1/control/routing-rules/{id}/enable` | Enable a rule |
| `POST /admin/api/v1/control/routing-rules/{id}/disable` | Disable a rule |

For application-team integration patterns, see
[`../docs/integrations.md`](../docs/integrations.md). The reference clients
under [`../sdk/`](../sdk/) are source examples, not published packages. They
can be copied or vendored into Python, Go, and JavaScript services, or replaced
with the HTTP client already used by a framework.

Machine requests use `Authorization: Bearer $SIP_CARRIER_API_TOKEN`. The
installer generates a separate token from the WebUI token. Put the API behind
TLS/mTLS or a private network; the standalone Mako listener is normally bound
to loopback.

Control writes use a separate `SIP_CONTROL_API_TOKEN`. Keep it in the service
that may change call behavior; a billing consumer should receive only the
carrier token. The control API accepts routing policy, not Mako source, SQL,
shell commands, or arbitrary plugin code.

For per-request SIP decisions and external TTS/STT/LLM/media workers, use the
signed HTTP/JSON application and module contracts in
[`../docs/modules.md`](../docs/modules.md). Those services are configured as
out-of-process endpoints; Madis validates their commands and retains
transaction ownership.

The route is served by the standalone WebUI process, so the base URL is the
WebUI's `ADMIN_BIND`/`ADMIN_PORT`, not the SIP worker's `/healthz` listener.
The SDK examples use a base URL ending in `/admin`, for example
`https://madis.example/admin`; their methods append `/api/v1/...` to that
base. If you use raw HTTP, the equivalent full path is
`https://madis.example/admin/api/v1/...`.
Missing or invalid bearer credentials return `401`. A missing database returns
`503`; malformed JSON, content type, or event identifiers return `400`.

A minimal client flow looks like this:

```sh
export API=http://127.0.0.1:8080
export TOKEN='the-value-from-/etc/madis/madis.env'

curl -fsS -H "Authorization: Bearer $TOKEN" "$API/admin/api/v1/capabilities"
curl -fsS -X POST "$API/admin/api/v1/billing/events" \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  --data '{"schema":"https://carrier.example/usage.v1","event_id":"call-42-final","event_type":"voice.usage.final","data":{"seconds":91}}'
```

Read pending events, commit them in the billing system, and acknowledge each
caller-supplied `event_id`. A retry is expected; an acknowledgement before the billing
transaction commits can lose the handoff.

`GET /billing/events` returns an object with `schema`, an `events` array, and a
`truncated` flag. The request limit is clamped to 100 and the response is
bounded. `POST /billing/events` returns `202` after an idempotent insert. The
server currently derives a SHA-256 event ID when a caller omits one; portable
clients should still send an explicit ID and validate against
`billing-event.schema.json`.

## Controlling routing behavior

Use `SIP_CONTROL_API_TOKEN` for policy changes. A rule is created enabled and
applies when the SIP worker evaluates the next call. Environment changes such
as `SIP_B2BUA_MODE=enabled` still require the normal service restart.

```sh
export CONTROL_TOKEN='the-value-from-/etc/madis/madis.env'
curl -fsS -X POST "$API/admin/api/v1/control/routing-rules" \
  -H "Authorization: Bearer $CONTROL_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"match_prefix":"+1555","action":"b2bua:carrier-gateway","priority":10,"description":"Carrier B2BUA policy"}'
```

Accepted actions are `route:`, `b2bua:`, `dispatch:`, `reject:`, `redirect:`,
`failover:`, `lcr`, and `continue`. Values are length-bounded and checked for
CR/LF/NUL/field separators before parameterized SQL is used. Read the rule
list for IDs, then use enable/disable for a recoverable state change. There is
no endpoint for arbitrary SQL or runtime code execution.

The API is at-least-once. Consumers must deduplicate by `event_id`, commit
their billing/charging transaction, then acknowledge. Acknowledgement is not a
delete, so operators can audit the original JSONB payload. Pages and request
bodies are bounded to protect the Mako 0.4.16 worker from memory pressure.

## Custom schemas

The envelope fields are fixed for this API version; `data`, `extensions`, and
application-defined fields are open. Set `schema` to your own URI or version, keep
reuse the same `event_id` across retries, and add a tenant-specific `event_type`.
Madis stores the complete JSON document as JSONB and does not silently rewrite
unknown fields. The built-in CDR event is only one profile, not a required
carrier schema.

```json
{
  "schema": "https://carrier.example/schemas/usage.voice.v3",
  "event_id": "acct-42-call-abc-final",
  "event_type": "voice.usage.final",
  "session_id": "call-abc",
  "tenant_id": "carrier-a",
  "data": {
    "account_id": "42",
    "units": {"seconds": 91, "messages": 0},
    "rating_context": {"plan": "gold", "zone": "us-east"}
  },
  "extensions": {"x-carrier": {"invoice_group": "voice"}}
}
```

## Online charging

`SIP_BILLING_MODE=preauth` uses the configured online charging protocol before
an INVITE is routed. `http` sends the bounded JSON contract to
`SIP_CHARGING_URL`; `diameter` uses the native RFC 8506 client described in
[`diameter.md`](diameter.md). Cx/Dx and Sh builders and parsers are described in
[`ims-diameter.md`](ims-diameter.md). Both charging paths are fail-closed by
default. Post-call termination messages never block SIP completion. The default `outbox` mode
keeps the SIP path local and is the correct choice for offline CDR/accounting.

The HTTP request uses RFC 8506 concepts (`INITIAL_REQUEST`, request number,
requested service units, service context, and subscription identity). RFC
8506 obsoletes RFC 4006; a legacy-only Diameter peer requires a compatibility
adapter.

## IMS and SS7 boundaries

The JSON and Protobuf contracts in this directory are integration boundaries
for P-/I-/S-CSCF, HSS/UDM, PCRF/PCF, TAS/MMTel, charging, and an SS7 gateway.
Cx registration authorization is available behind `SIP_IMS_CX=1`; the HSS,
S-CSCF service logic, and user-data store remain external. Madis does not claim
to be a complete 3GPP IMS core. Likewise, the SS7 envelope carries M3UA/SCCP/ISUP metadata for an
external SIGTRAN gateway; native M3UA remains outside Madis even though the
Mako 0.4.16 runtime provides SCTP primitives.

See `billing-event.schema.json`, `charging-request.schema.json`,
`ims-session.schema.json`, `ss7-m3ua-envelope.schema.json`, and
`madis-carrier.proto`.
