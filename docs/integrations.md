# Application integration

Carrier, billing, provisioning, and operations applications can call Madis over
HTTP/JSON. They can be written in Python, Go, JavaScript, or another language
without linking to Mako or embedding SIP process state.

The supported integration boundary is server-side HTTP/JSON:

```text
application service  ── HTTPS + bearer token ──>  Madis WebUI/API
       │                                             │
       └─ owns billing, workflow, retries, schema ───┘
```

Madis does not execute application code inside the SIP worker. Keep framework
code, business rules, credentials, and durable application state in the
calling service. The API is served by the standalone WebUI process; use the
SIP worker's `/healthz` and `/readyz` endpoints separately for infrastructure
health checks.

## Start with the contract

Use a base URL that includes `/admin`:

```text
https://proxy.example.net/admin
```

The carrier API then uses:

```text
GET  /api/v1/capabilities
GET  /api/v1/billing/events?limit=100
POST /api/v1/billing/events
POST /api/v1/billing/events/ack?event_id=...
```

The full public path is therefore, for example,
`https://proxy.example.net/admin/api/v1/capabilities`. Send
`Authorization: Bearer <SIP_CARRIER_API_TOKEN>` and JSON for event writes.
Keep this token on the server. Browser applications should call their own
backend, which then calls Madis; do not expose a carrier token in JavaScript
bundles or browser storage.

The API accepts an event envelope. `schema`, `event_type`, and `data` are
required; `tenant_id`, `session_id`, `occurred_at_ms`, and
`extensions` are available when useful. `data` and `extensions` are owned by
the application. Validate events against
[`../api/billing-event.schema.json`](../api/billing-event.schema.json) and
publish an explicit `event_id` and reuse it for retries.

## Control plane

Applications can also change the supported call policy through the versioned
control API. Use a separate `SIP_CONTROL_API_TOKEN`; do not give a billing
worker permission to change routing. The first control surface manages bounded
routing rules and explicit B2BUA policy:

```text
GET  /api/v1/control/status
GET  /api/v1/control/routing-rules?limit=100
POST /api/v1/control/routing-rules
POST /api/v1/control/routing-rules/{id}/enable
POST /api/v1/control/routing-rules/{id}/disable
```

For example, a carrier application can submit
`{"match_prefix":"+1555","action":"b2bua:carrier-gateway"}`. The
allowed actions are `route:`, `b2bua:`, `dispatch:`, `reject:`, `redirect:`,
`failover:`, `lcr`, and `continue`. `b2bua:` is effective only when the SIP
worker has `SIP_B2BUA_MODE=enabled`. A control request changes database policy;
it does not inject Mako, SQL, shell commands, or arbitrary language code into
the SIP worker. The worker continues to own SIP transaction state and applies
the rule on the next matching call.

The same HTTP contract is used by every supported language. In Python:

```python
control = MadisCarrier(
    os.environ["MADIS_API_URL"],
    os.environ["SIP_CONTROL_API_TOKEN"],
)
control.create_routing_rule({
    "match_prefix": "+1555",
    "action": "b2bua:carrier-gateway",
    "priority": 10,
})
```

Go, JavaScript/TypeScript, Lua, and Erlang clients expose the same operations
as `CreateRoutingRule`/`SetRoutingRuleEnabled`, `createRoutingRule`,
`create_routing_rule`/`set_routing_rule_enabled`, and
`create_routing_rule`/`set_routing_rule_enabled`. The examples under
[`../sdk/`](../sdk/) are intentionally thin so teams can wrap them in FastAPI,
Gin, Express, LuaSocket, OTP, or another application framework.

## Python

The dependency-free reference client is
[`sdk/python/madis_carrier.py`](../sdk/python/madis_carrier.py). It works in a
normal worker, Flask view, Django management command, or a synchronous FastAPI
route:

```python
import os

from sdk.python.madis_carrier import MadisCarrier

madis = MadisCarrier(
    os.environ["MADIS_API_URL"],       # https://proxy.example.net/admin
    os.environ["SIP_CARRIER_API_TOKEN"],
    timeout=2.0,
)

def publish_usage(call_id: str, seconds: int) -> dict:
    return madis.publish({
        "schema": "https://carrier.example/schemas/voice-usage.v1",
        "event_id": f"{call_id}:final",
        "event_type": "voice.usage.final",
        "session_id": call_id,
        "data": {"seconds": seconds},
    })
```

For async FastAPI or an async worker, use an async HTTP client such as
`httpx` or `aiohttp`, or run the synchronous reference client in a worker
thread. Do not perform blocking `urllib` calls directly in an async event
loop. Flask and Django views may use the reference client directly, but set a
short timeout and move long polling or billing reconciliation to a background
worker such as Celery, RQ, Dramatiq, or the platform's job system.

## Go

[`sdk/go/madiscarrier.go`](../sdk/go/madiscarrier.go) is a small source-level
package example using `net/http`, `context`, and `encoding/json`. It is not a
published Go module; copy or vendor it into the application's own module and
review its error and retry policy.

The same client fits `net/http` handlers and routers such as Gin, chi, Echo,
or Fiber. Pass request-scoped contexts and keep the HTTP client shared:

```go
client := &madiscarrier.Client{
    BaseURL: os.Getenv("MADIS_API_URL"), // .../admin
    Token:   os.Getenv("SIP_CARRIER_API_TOKEN"),
    HTTP:    &http.Client{Timeout: 2 * time.Second},
}

event := map[string]any{
    "schema":     "https://carrier.example/schemas/voice-usage.v1",
    "event_id":   callID + ":final",
    "event_type": "voice.usage.final",
    "session_id": callID,
    "data":       map[string]any{"seconds": seconds},
}

result, err := client.Publish(ctx, event)
```

In Gin/chi/Echo, call this from a server-side handler or enqueue the event in
the application's durable job system first. Do not create a new `http.Client`
for every request. Use `context.WithTimeout` for per-operation deadlines and
log the Madis status without logging the bearer token or full sensitive event
payload.

## JavaScript and TypeScript

[`sdk/javascript/madis-carrier.mjs`](../sdk/javascript/madis-carrier.mjs) uses
the platform `fetch` API and works in current Node.js releases. It can be
wrapped by Express, Fastify, NestJS, or a Next.js route handler:

```js
import { MadisCarrier } from "./sdk/javascript/madis-carrier.mjs";

const madis = new MadisCarrier(
  process.env.MADIS_API_URL,              // .../admin
  process.env.SIP_CARRIER_API_TOKEN,
  2000,
);

export async function publishUsage(callId, seconds) {
  return madis.publish({
    schema: "https://carrier.example/schemas/voice-usage.v1",
    event_id: `${callId}:final`,
    event_type: "voice.usage.final",
    session_id: callId,
    data: { seconds },
  });
}
```

For Express or Fastify, call this from a server route or queue the work before
returning to the caller. In NestJS, put the client behind an injectable
service. In Next.js, use a server route or server action; never import the
client into a browser bundle when it contains the carrier token. Browser
frontends should call an application-owned backend endpoint instead.

## Consuming events

A consumer is at-least-once, not exactly-once:

```text
read pending events
  → validate schema and authorize tenant
  → deduplicate by event_id
  → commit billing/workflow transaction
  → POST ack only after commit succeeds
```

The pending-event response is bounded and may be truncated. Poll again until
the service returns no work, then use a bounded interval. A failed request or
process restart should leave the event available for another attempt. Do not
ack before the downstream transaction is durable.

Publishing is idempotent when the same event ID is retried. Retry only
transient failures such as connection failures or `503`, with exponential
backoff and jitter. Do not blindly retry `400` or `401`; fix the payload or
credentials. A `202` means Madis accepted the event, not that a downstream
rating or invoice has completed.

## Framework responsibilities

| Responsibility | Application owns it | Madis provides |
| --- | --- | --- |
| HTTP client and framework route | Yes | Versioned JSON endpoints |
| Bearer-token storage and rotation | Yes | Token authentication |
| Event schema and validation | Yes, using the supplied envelope/schema | Bounded JSON persistence |
| Idempotency and retry policy | Yes | Idempotent event insertion by `event_id` |
| Billing/rating/invoice transaction | Yes | Outbox and online-charging integration boundaries |
| Tenant authorization | Yes | Tenant fields and authenticated API boundary |
| Long-running jobs and reconciliation | Yes | Pending-event and acknowledgement flow |

For OpenAPI-based code generation, use
[`../api/openapi.yaml`](../api/openapi.yaml) as a starting contract and review
generated clients before deployment. It describes the carrier API, not the
full SIP/WebUI surface. The API covers the endpoints listed in
their existing framework conventions, databases, queues, and observability.
