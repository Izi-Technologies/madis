# MADIS SDKs

The SDKs are small reference clients for the versioned HTTP/JSON surfaces.
They do not bypass MAF authorization, inject SIP, or expose worker memory.

## MAF clients

MAF clients cover the enabled call, bridge, media, header-policy, and
replayable-event routes. All mutating calls remain asynchronous and return a
durable command receipt.

| Language | File |
| --- | --- |
| Python | [`maf/python/madis_maf.py`](maf/python/madis_maf.py) |
| JavaScript/TypeScript | [`maf/javascript/madis-maf.mjs`](maf/javascript/madis-maf.mjs) |
| Go | [`maf/go/madismaf.go`](maf/go/madismaf.go) |

Example Python usage:

```python
from madis_maf import MadisMaf

maf = MadisMaf("https://proxy.example.net/admin", token_from_secret_store)
receipt = maf.create_call("sip:app@example.net", "sip:user@example.net")
events = maf.events(cursor=0, event_type="call.answered")
```

Put the admin listener behind an HTTPS reverse proxy or service mesh with
mTLS in production. The SDK still sends the MAF bearer token because a client
certificate is transport authentication, not application authorization.
Keep tokens in server-side secret storage and never place them in browser
bundles, URLs, SIP headers, logs, or user-controlled payloads.

MAF bridge commands create durable relationships after answer. Media commands
dispatch through the configured signed `media` or `recording` module and
return an explicit failed receipt when no safe backend accepts the operation.

## Existing carrier/control clients

| Language | Runtime | File |
| --- | --- | --- |
| Python | Standard library | [`python/madis_carrier.py`](python/madis_carrier.py) |
| JavaScript | Server-side `fetch` | [`javascript/madis-carrier.mjs`](javascript/madis-carrier.mjs) |
| Go | `net/http`, `context`, `encoding/json` | [`go/madiscarrier.go`](go/madiscarrier.go) |
| Lua | LuaSocket; caller supplies JSON | [`lua/madis_carrier.lua`](lua/madis_carrier.lua) |
| Erlang | OTP `inets`; caller supplies JSON | [`erlang/madis_carrier.erl`](erlang/madis_carrier.erl) |

The machine-readable contracts are [`../api/maf.openapi.yaml`](../api/maf.openapi.yaml)
and [`../api/openapi.yaml`](../api/openapi.yaml).
