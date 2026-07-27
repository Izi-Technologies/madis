# Madis carrier integration API

Madis exposes a versioned HTTP/JSON machine API from the standalone WebUI. If the WebUI base URL is `https://madis.example/admin`, the API base URL is:

```text
https://madis.example/admin/api/v1
```

The API is for carrier and application services. It is separate from the browser session API and from the SIP worker’s local `/healthz`, `/readyz`, `/metrics`, `/state`, and `/reload` endpoints.

The machine contracts are also represented by [`openapi.yaml`](openapi.yaml), [`madis-carrier.proto`](madis-carrier.proto), and the JSON schemas in this directory. The source-level reference clients are in [`../sdk/README.md`](../sdk/README.md).

## Authentication

Send a bearer token on every machine request:

```http
Authorization: Bearer <token>
```

| Token | Allowed operations |
| --- | --- |
| `SIP_CARRIER_API_TOKEN` | Capabilities, billing events, event acknowledgement, and CDR reads. |
| `SIP_CONTROL_API_READ_TOKEN` | Control status, reads, validation, and resource lists. |
| `SIP_CONTROL_API_TOKEN` | All read-only control operations plus control writes. |

The write token also has the read scope. The read token cannot create, replace, delete, enable, or disable a routing rule, dialplan, or mutable resource. Browser cookies are not accepted by these routes.

## Endpoints

All list endpoints accept `limit`; values are clamped to 1–100. JSON request bodies are capped at 64 KiB. Responses are bounded and may include a truncation indicator when the response-size limit is reached.

| Method and path | Scope | Description |
| --- | --- | --- |
| `GET /capabilities` | Carrier | Discover transports and enabled integration contracts. |
| `GET /billing/events?limit=100` | Carrier | Read undelivered billing events. |
| `POST /billing/events` | Carrier | Publish an idempotent application event. |
| `POST /billing/events/ack?event_id=...` | Carrier | Acknowledge an event after the consumer commits its work. |
| `GET /billing/cdr?limit=100&call_id=...` | Carrier | Read bounded CDR records for rating or reconciliation. |
| `GET /control/status` | Control read | Read the control-plane capability/status document. |
| `GET /control/routing-rules` | Control read | List routing rules. |
| `POST /control/routing-rules` | Control write | Create an allowlisted routing rule. |
| `POST /control/routing-rules/{id}/enable` | Control write | Enable a routing rule. |
| `POST /control/routing-rules/{id}/disable` | Control write | Disable a routing rule. |
| `GET /control/dialplans` | Control read | List dialplan rules. |
| `POST /control/dialplans` | Control write | Create a dialplan rule. |
| `PUT /control/dialplans/{id}` | Control write | Replace a dialplan rule. |
| `DELETE /control/dialplans/{id}` | Control write | Delete a dialplan rule. |
| `POST /control/dialplans/{id}/enable` | Control write | Enable a dialplan rule. |
| `POST /control/dialplans/{id}/disable` | Control write | Disable a dialplan rule. |
| `POST /control/validate/routing-rule` | Control read | Validate a routing-rule document without storing it. |
| `POST /control/validate/dialplan` | Control read | Validate a dialplan document without storing it. |
| `GET /control/resources/{resource}` | Control read | List an allowlisted SIP resource. |
| `POST /control/resources/{resource}` | Control write | Create a mutable SIP resource; `security-bans` is upserted by `source_ip`. |
| `PUT /control/resources/{resource}/{id}` | Control write | Replace a numeric-ID mutable SIP resource. |
| `DELETE /control/resources/{resource}/{id}` | Control write | Delete a numeric-ID mutable SIP resource. |
| `POST /control/resources/{resource}/{id}/enable` | Control write | Enable a numeric-ID mutable resource. |
| `POST /control/resources/{resource}/{id}/disable` | Control write | Disable a numeric-ID mutable resource. |

The API has no endpoint for arbitrary SQL, database migrations, Mako source, shell commands, or plugin code.

## Billing and CDR flow

Billing events are stored in Madis’s durable outbox. Publishing is idempotent by `event_id`; if the caller omits it, the server derives one from the request body, but portable integrations should always supply a stable ID.

Consumers should follow this sequence:

```text
read pending events → validate and deduplicate by event_id
→ commit the application transaction → acknowledge the event
```

An acknowledgement makes the event unavailable to the pending-event reader. Do not acknowledge before the application’s rating, ledger, or workflow transaction is durable. Delivery is at least once, not exactly once. The application owns retries, schema validation, tenant authorization, and downstream billing state.

The built-in CDR profile is described by [`cdr.schema.json`](cdr.schema.json). `data` and `extensions` in application events remain application-owned JSON; Madis does not turn them into arbitrary database columns.

Example event publication:

```sh
API=https://madis.example/admin
TOKEN="$SIP_CARRIER_API_TOKEN"

curl -fsS -X POST "$API/api/v1/billing/events" \
  -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{
    "schema": "https://carrier.example/schemas/voice-usage.v1",
    "event_id": "call-123:final",
    "event_type": "voice.usage.final",
    "session_id": "call-123",
    "data": {"seconds": 42},
    "extensions": {"application_call_id": "app-456"}
  }'
```

## Routing and dialplan control

Routing actions are values, not executable code. The accepted action families are `route:`, `b2bua:`, `dispatch:`, `reject:`, `redirect:`, `failover:`, `lcr`, and `continue`, subject to the endpoint’s length and character validation. A `b2bua:` action still requires `SIP_B2BUA_MODE=enabled` in the worker environment.

Dialplan actions are limited to number transformations such as `strip`, `prepend`, `set`, `replace`, `e164`, `add_plus`, and `strip_plus`. Use the validation endpoint before presenting or storing a document when the application has multiple control writers.

Example:

```sh
curl -fsS -X POST "$API/api/v1/control/validate/routing-rule" \
  -H "Authorization: Bearer $SIP_CONTROL_API_READ_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"match_prefix":"+1","action":"route:primary","priority":10}'

curl -fsS -X POST "$API/api/v1/control/routing-rules" \
  -H "Authorization: Bearer $SIP_CONTROL_API_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"match_prefix":"+1","action":"route:primary","priority":10,"description":"North America"}'
```

## Generic SIP resources

The resource name is allowlisted; it is never interpreted as a table name. The current resource set is:

| Resource | Mutability | Main fields |
| --- | --- | --- |
| `gateways` | Read/write | `name`, `address`, `port`, `transport`, credentials, `caller_id`, `max_channels`, `number_format`, `tech_prefix`, `caller_id_override` |
| `routes` | Read/write | `prefix`, exactly one of `gateway_id` or `dispatch_set_id`, `priority`, `weight`, `cost_per_min`, `time_start`, `time_end`, `description` |
| `dispatch-sets` | Read/write | `name`, `algorithm`, `description`; algorithms include `round-robin`, `weight`, `priority`, `hash`, `hash-user`, and `broadcast` |
| `dispatch-members` | Read/write | `set_id`, `gateway_id`, `priority`, `weight` |
| `dids` | Read/write | `number`, `destination_user`, `description` |
| `header-rules` | Read/write | `match_method`, `match_direction`, `action`, `header_name`, `header_value`, `priority`, `description` |
| `access-control` | Read/write | `source_ip`, `sip_user`, `action`, `skip_auth`, `tenant`, `max_channels`, `priority`, `description` |
| `security-bans` | Read/create-upsert | `source_ip`, `reason`, `permanent`; the current row key is `source_ip`, not a numeric resource ID |
| `ani-groups` | Read/write | `name`, `description` |
| `ani-ranges` | Read/write | `group_id`, `range_start`, `range_end` |
| `registrations` | Read-only | AOR, contact, transport, node, user agent, and update time |
| `registration-bindings` | Read-only | Binding ID, AOR, contact, source, port, expiry, and update time |
| `cluster-nodes` | Read-only | Node ID, address, port, region, weight, status, and heartbeat |
| `security-events` | Read-only | Event type, source, user, severity, details, and timestamp |

Mutable numeric-ID resource responses expose a `revision` based on the current database row version. Use `expected_revision` with update/delete operations when concurrent writers must not overwrite one another. `security-bans` is the exception: its POST is a source-IP upsert and its list response has no numeric-ID revision. Resource writes create or change only the fields listed by the resource contract; unknown JSON fields are not persisted.

## Error handling and deployment

Typical responses are `200` for reads/state changes, `201` for creates, `202` for accepted events, `400` for invalid input, `401` for missing/invalid credentials, `404` for unknown rows, `409` for revision conflicts where applicable, and `503` when the database or required runtime dependency is unavailable.

Put the standalone WebUI behind an HTTPS reverse proxy, preserve `Host` and `Origin` for browser requests, and never expose bearer tokens in browser code. See [`../docs/operations.md`](../docs/operations.md) for service layout and [`../docs/integrations.md`](../docs/integrations.md) for application patterns.

## IMS subscriber authorization

The optional HTTPS IMS subscriber authorization contract is documented in [`ims-subscriber.md`](ims-subscriber.md) and validated by [`ims-subscriber.schema.json`](ims-subscriber.schema.json). It is a REGISTER authorization boundary, not an HSS/UDM implementation.

Cx MAA authentication-data extraction is documented in [`ims-diameter.md`](ims-diameter.md) and validated by [`ims-aka-vector.schema.json`](ims-aka-vector.schema.json). The envelope is opaque and is not a local AKA implementation.

When `SIP_IMS_AKA=1` and `SIP_IMS_CX=1`, the SIP worker can use that Cx vector boundary for the selected `Digest-AKAv1-MD5` REGISTER profile. HSS/UDM remains responsible for AKA generation, subscriber secrets, and interoperability with the UE.

## What remains external

Madis stores the SIP state needed to route calls and deliver events. The external application remains the source of truth for tenants, products, tariffs, invoices, ledgers, tax, settlement, long-running jobs, and business-specific JSON schemas.
