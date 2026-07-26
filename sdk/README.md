# Madis carrier SDK examples

These are intentionally small clients over the stable HTTP/JSON API. They
keep application state and schema ownership in the caller, so the same
contract works from Python, JavaScript, Go, Lua, Erlang, or any language with
an HTTP client. The Protobuf contract is in `api/madis-carrier.proto` for
teams that standardize on gRPC. Framework-specific adapters are not required:
FastAPI, Flask, Django, Gin, chi, Echo, Express, Fastify, NestJS, and Next.js
can all call the same server-side HTTP endpoints.

- `python/madis_carrier.py` uses only the Python standard library.
- `javascript/madis-carrier.mjs` uses the platform `fetch` API.
- `go/madiscarrier.go` uses only `net/http` and `encoding/json`.
- `lua/madis_carrier.lua` uses LuaSocket; JSON is supplied by the caller.
- `erlang/madis_carrier.erl` uses OTP `inets`; JSON is supplied by the caller.

All clients preserve the server's at-least-once semantics: process and commit
an event, then call `ack`. Treat `event_id` as an idempotency key. The client
base URL should include `/admin` (for example,
`https://madis.example/admin`); the methods append `/api/v1/...`.

The examples are deliberately small rather than full SDKs. Each one accepts a
base URL and bearer token, publishes ordinary JSON, and leaves retries,
durable storage, and application-specific validation to the caller. Start
with the Python example if you want a dependency-free reference client, then
copy the same request/acknowledge flow into your service language. Keep the
token in server-side configuration; do not ship it to browser code.

See [`../docs/integrations.md`](../docs/integrations.md) for framework wiring,
consumer patterns, error handling, and schema/versioning guidance.
