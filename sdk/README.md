# Madis carrier SDK examples

These are small source-level clients for the Madis HTTP/JSON machine API. They are reference implementations, not published packages or complete application frameworks. Each caller remains responsible for durable storage, retries, schema validation, tenant authorization, observability, and secret management.

The base URL should include `/admin`, for example `https://madis.example/admin`; the clients append `/api/v1/...`.

| Client | Runtime | File |
| --- | --- | --- |
| Python | Standard library | [`python/madis_carrier.py`](python/madis_carrier.py) |
| JavaScript | Server-side `fetch` | [`javascript/madis-carrier.mjs`](javascript/madis-carrier.mjs) |
| Go | `net/http`, `context`, `encoding/json` | [`go/madiscarrier.go`](go/madiscarrier.go) |
| Lua | LuaSocket; caller supplies JSON | [`lua/madis_carrier.lua`](lua/madis_carrier.lua) |
| Erlang | OTP `inets`; caller supplies JSON | [`erlang/madis_carrier.erl`](erlang/madis_carrier.erl) |

## API methods covered

The clients expose the carrier operations for capabilities, pending billing events, publication, acknowledgement, and CDR reads. They also expose control operations for status, routing rules, dialplans, validation, and the generic allowlisted SIP resources.

Generic resource helpers cover:

`gateways`, `routes`, `dispatch-sets`, `dispatch-members`, `dids`, `header-rules`, `access-control`, `security-bans`, `ani-groups`, `ani-ranges`, `registrations`, `registration-bindings`, `cluster-nodes`, and `security-events`. `security-bans` is currently a source-IP create/upsert and list surface; the generic numeric-ID update/delete/state helpers do not apply to it.

The server still enforces the read/write scope. A client constructed with `SIP_CONTROL_API_READ_TOKEN` can list and validate but cannot mutate. Use `SIP_CONTROL_API_TOKEN` only in the service that is allowed to change SIP behavior.

## Event delivery semantics

The billing outbox is at least once. Applications should:

1. Read pending events.
2. Validate the envelope and authorize the tenant.
3. Deduplicate on `event_id`.
4. Commit the rating/ledger/workflow transaction.
5. Call the acknowledgement endpoint.

Do not acknowledge before the application transaction is durable. Retry connection failures and transient `503` responses with bounded backoff; fix invalid payloads and credentials instead of retrying `400`/`401` responses indefinitely.

## Resource writes

Mutable resource responses include a `revision`. When concurrent control writers are possible, send `expected_revision` on update/delete calls and reconcile a conflict by re-reading the resource. Unknown JSON fields are not persisted. Resource helpers do not expose SQL or arbitrary table names.

## Server-side use only

All clients accept bearer tokens and must remain server-side. Never ship a carrier or control token in browser JavaScript. Browser frontends should call an application-owned backend, which then applies user and tenant authorization before calling Madis.

The HTTP/JSON contract is documented in [`../api/README.md`](../api/README.md), [`../api/openapi.yaml`](../api/openapi.yaml), and [`../docs/integrations.md`](../docs/integrations.md). [`../api/madis-carrier.proto`](../api/madis-carrier.proto) provides Protobuf message shapes; the repository’s service surface is HTTP/JSON rather than a separate built-in gRPC listener.
