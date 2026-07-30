# MADIS Application Fabric integration

The MADIS Application Fabric (MAF) is the language-neutral boundary for
external application services. Applications own their business state and use
MADIS for SIP state, routing policy, CDR delivery, and selected
charging/integration boundaries. MAF HTTP and WebSocket surfaces are served by
the standalone admin process. Mutating calls are durable asynchronous command
acceptance; use the call resource and event cursor to observe progress. The
worker executes outbound originate and early-dialog cancellation; confirmed
hangup sends BYE. Set `SIP_MAF_INBOUND_MODE=control` to publish authenticated
initial INVITEs as ringing MAF calls and let `calls.answer` send a validated
`answer_sdp` response. Bridge operations create durable tenant-owned
relationships after a call is answered. Media operations dispatch through the
signed `media` or `recording` module configured with `SIP_MODULE_URL`,
`SIP_MODULE_TOKEN`, and `SIP_MODULES`; they fail explicitly when no safe
backend accepts the request. Live MAF event replay is available over HTTP and
the bearer-authenticated `/api/v1/maf/events/ws` WebSocket route. The protobuf
remains a shape description; the repository does not expose a separate
built-in gRPC listener.

## Inbound call control

Set `SIP_MAF_INBOUND_MODE=control` on the SIP worker to opt into MAF ownership
of authenticated initial INVITEs. MADIS persists each accepted INVITE as a
tenant-scoped `ringing` call and emits `call.created`; it does not intercept
normal proxy traffic while the mode is `disabled`.

An application answers with `POST /admin/api/v1/maf/calls/{call_id}/answer` and
a bounded `answer_sdp`. The SIP worker validates the SDP, creates the local
dialog tag, records the server transaction, sends `200 OK`, and emits the
resulting state event. Rejecting while ringing sends a final SIP response;
hangup sends `487` before answer or a worker-owned `BYE` after answer.
Validate TCP, TLS, WS, and WSS behavior in the deployment before enabling this
mode broadly. See the complete sequence and request example in
[`../api/maf.md`](../api/maf.md).

## Choose the right interface

| Requirement | Madis interface |
| --- | --- |
| Build an external call application | MAF HTTP routes; see [`../api/maf.md`](../api/maf.md) and [`../api/maf.openapi.yaml`](../api/maf.openapi.yaml) |
| Read enabled transports and integration contracts | `GET /admin/api/v1/capabilities` |
| Consume CDR or application billing events | Carrier API with `SIP_CARRIER_API_TOKEN` |
| Change routes, dialplans, gateways, or other SIP policy | Control API with `SIP_CONTROL_API_TOKEN` |
| Observe policy without mutation | Control API with `SIP_CONTROL_API_READ_TOKEN` |
| Make a per-request SIP decision | Signed live application contract; see [`modules.md`](modules.md) |
| Dispatch TTS/STT/LLM/media/recording/fraud/billing work | Signed module contract; see [`modules.md`](modules.md) |
| Online authorization before an INVITE | HTTP or Diameter charging configuration; see [`../api/diameter.md`](../api/diameter.md) |

The HTTP/JSON base URL includes `/admin`, for example:

```text
https://proxy.example.net/admin/api/v1/
```

The SIP worker’s local `/healthz` and `/readyz` endpoints are infrastructure probes, not an application API. Readiness should be checked separately from billing or control API health.

## Authentication and network placement

Use `Authorization: Bearer ...` on every machine API request. Keep the following credentials separate:

- `SIP_CARRIER_API_TOKEN` for billing consumers and CDR/rating integrations.
- `SIP_CONTROL_API_TOKEN` for the service that may change call behavior.
- `SIP_CONTROL_API_READ_TOKEN` for observers and reconciliation jobs that must not mutate state.
- `SIP_MAF_API_TOKEN` for MAF writes; it also permits MAF reads.
- `SIP_MAF_API_READ_TOKEN` for MAF read-only call and event access.
- `SIP_MAF_TENANT` for the tenant namespace bound to this admin process; it defaults to `default`.
- `SIP_MAF_INBOUND_MODE=control` to let MAF own authenticated initial INVITEs; the default `disabled` preserves normal proxy routing.

Keep tokens in server-side configuration. Do not put them in browser bundles, SIP headers, routing-rule descriptions, logs, or application URLs. Put the admin service behind HTTPS and a private network or reverse proxy. The repository does not ship a public TLS termination or identity provider.

## Capabilities discovery

Start an integration by querying capabilities:

```sh
curl -fsS \
  -H "Authorization: Bearer $SIP_CARRIER_API_TOKEN" \
  https://proxy.example.net/admin/api/v1/capabilities
```

The response identifies the Madis schema/version, signaling transports, available billing/charging/IMS/SS7 contracts, control surface, and whether the optional signed application or module endpoints are enabled. Treat it as runtime discovery, not a replacement for deployment configuration review.

## Billing event consumer

The billing outbox is at-least-once. A robust consumer does the following:

```text
poll events → validate schema and tenant policy
→ deduplicate by event_id → commit rating/ledger/workflow transaction
→ acknowledge event_id
```

Do not acknowledge first. If a consumer crashes after committing but before acknowledging, it must safely process the same `event_id` again. Retry connection failures and transient `503` responses with bounded exponential backoff and jitter; fix `400` and `401` responses instead of retrying them blindly.

Madis provides event identity, bounded JSON persistence, CDR reads, and acknowledgement. The application provides the rating formula, ledger, invoices, settlement, tax, tenant authorization, and durable job orchestration.

## Control API usage

Use the validation endpoints before writing policy assembled by an operator or another service:

```sh
API=https://proxy.example.net/admin/api/v1

curl -fsS -X POST "$API/control/validate/dialplan" \
  -H "Authorization: Bearer $SIP_CONTROL_API_READ_TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"match_prefix":"+1","callee_action":"e164,prepend:1","priority":20}'
```

Use the generic resource API for Madis-owned SIP state such as gateways, routes, dispatch sets, DIDs, access control, security bans, ANI ranges, and header rules. Security bans are currently listed and created/upserted by `source_ip`; they do not use the generic numeric-ID update/delete/state operations. The API is not a generic CRUD interface for application tables. See [`../api/README.md`](../api/README.md) for the complete resource catalog and field bounds.

Mutable resource responses include a `revision`. When multiple writers are possible, read the row, retain its revision, and send `expected_revision` on the update or delete operation. Treat a conflict as a signal to re-read and reconcile rather than blindly retrying the old document.

## Python

[`../sdk/python/madis_carrier.py`](../sdk/python/madis_carrier.py) uses only the Python standard library. It provides capabilities, event publication/acknowledgement, CDR reads, control methods, resource methods, and document validation.

```python
import os
from madis_carrier import MadisCarrier

client = MadisCarrier(
    os.environ["MADIS_API_URL"],  # e.g. https://proxy.example.net/admin
    os.environ["SIP_CARRIER_API_TOKEN"],
    timeout=2.0,
)

event = {
    "schema": "https://carrier.example/schemas/voice-usage.v1",
    "event_id": "call-123:final",
    "event_type": "voice.usage.final",
    "session_id": "call-123",
    "data": {"seconds": 42},
}
client.publish(event)
```

For a control client, construct it with the control token and use `control_resources`, `create_control_resource`, `update_control_resource`, `delete_control_resource`, `set_control_resource_enabled`, `validate_routing_rule`, or `validate_dialplan` as appropriate.

## Go

[`../sdk/go/madiscarrier.go`](../sdk/go/madiscarrier.go) is a source-level example using `net/http`, `context`, and `encoding/json`. It is not a published Go module. Copy or vendor it into the application and review its retry, timeout, and error handling.

Use a shared `http.Client`, a request-scoped context deadline, and a durable queue for event publication. Do not create a new client for every event or block the SIP request path on a long-running rating job.

## JavaScript and TypeScript

[`../sdk/javascript/madis-carrier.mjs`](../sdk/javascript/madis-carrier.mjs) uses the platform `fetch` API and works in current server-side Node.js environments. It can be wrapped by Express, Fastify, NestJS, or a Next.js server route.

Never import it into a browser bundle when the instance contains a Madis bearer token. Browser code should call an application-owned backend endpoint, and that backend should enforce the application’s user and tenant authorization before calling Madis.

## Lua and Erlang

[`../sdk/lua/madis_carrier.lua`](../sdk/lua/madis_carrier.lua) uses LuaSocket, and [`../sdk/erlang/madis_carrier.erl`](../sdk/erlang/madis_carrier.erl) uses OTP `inets`. Both are small reference clients; JSON encoding, durable storage, retries, and application-specific validation remain with the caller.

## Protobuf and OpenAPI

[`../api/openapi.yaml`](../api/openapi.yaml) is the HTTP/JSON starting contract. [`../api/madis-carrier.proto`](../api/madis-carrier.proto) defines language-neutral message shapes for applications that want a Protobuf representation. The repository exposes the HTTP/JSON service; it does not provide a separate built-in gRPC listener. Review generated clients against the deployed API and preserve the bearer-token and at-least-once semantics.

## Live SIP applications and modules

Use the signed live application contract when an external application must participate in a SIP decision within a bounded timeout. Use the module contract for external speech, media, model, fraud, recording, or billing workers. These services must return quickly or use an asynchronous correlation pattern; Madis does not hold SIP transactions open for an unbounded external job.

See [`modules.md`](modules.md) for event and command schemas, signing, allowlists, timeout behavior, and failure modes.
