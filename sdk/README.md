# Madis carrier SDK examples

These are example clients for the HTTP/JSON API. Application state and schema
remain in the caller. The API can be called from Python, JavaScript, Go, Lua,
Erlang, or any language with an HTTP client. The Protobuf contract is in
`api/madis-carrier.proto` for callers using gRPC. FastAPI, Flask, Django, Gin,
chi, Echo, Express, Fastify, NestJS, and Next.js can call the same server-side
HTTP endpoints.

- `python/madis_carrier.py` uses only the Python standard library.
- `javascript/madis-carrier.mjs` uses the platform `fetch` API.
- `go/madiscarrier.go` uses only `net/http` and `encoding/json`.
- `lua/madis_carrier.lua` uses LuaSocket; JSON is supplied by the caller.
- `erlang/madis_carrier.erl` uses OTP `inets`; JSON is supplied by the caller.

All clients preserve the server's at-least-once semantics: process and commit
an event, then call `ack`. Treat `event_id` as an idempotency key. The client
base URL should include `/admin` (for example,
`https://madis.example/admin`); the methods append `/api/v1/...`.

The clients also expose the bounded control surface: read `control_status()` /
`ControlStatus()` / `controlStatus()`, list and create routing rules, and
enable or disable a rule. They can list, create, replace, delete, enable, and
disable dialplans. Generic resource methods cover gateways, routes, dispatch
sets and members, DIDs, header rules, access control, security bans, ANI
groups/ranges, and read-only registrations, bindings, cluster nodes, and
security events. CDR reads are available through `cdr`/`CDR`/`cdr` and use the
carrier token; dialplan and routing calls use `SIP_CONTROL_API_TOKEN`.
Keep it separate from `SIP_CARRIER_API_TOKEN` and never expose either token to
browser code. Read-only list/status calls may use
`SIP_CONTROL_API_READ_TOKEN`. Control calls select allowlisted actions; they do
not execute source code or SQL in Madis.

The resource API owns only Madis's routing fields. Do not model application
billing tables or tenant-specific records in Madis. Keep those in the
application database and associate them with a Madis ID or event payload.
Updates can send `expected_revision` to reject stale writes.

For live SIP behavior, use the external application gateway described in
[`../docs/modules.md`](../docs/modules.md). It is HTTP/JSON rather than a
language-specific plugin ABI: a FastAPI, Go, Node, LuaSocket, or OTP service
can verify `madis.sip.event.v1` and return `madis.sip.command.v1`. The module
bus uses the same command shape for TTS, STT, LLM, media, recording, fraud,
and billing workers. Keep the live SIP endpoint server-side.

The examples are not full SDKs. Each one accepts a
base URL and bearer token, publishes ordinary JSON, and leaves retries,
durable storage, and application-specific validation to the caller. Start
with the Python example if you want a dependency-free reference client, then
copy the same request/acknowledge flow into your service language. Keep the
token in server-side configuration; do not ship it to browser code.

See [`../docs/integrations.md`](../docs/integrations.md) for framework wiring,
consumer patterns, error handling, and schema/versioning guidance.
