# MADIS SDKs

The SDKs are small reference clients for the versioned HTTP/JSON surfaces.
They do not bypass MAF authorization, inject SIP, or expose worker memory.

## MAF clients

MAF clients cover the enabled call, bridge, media, header-policy, and
replayable-event routes. All mutating calls remain asynchronous and return a
durable command receipt.

| Language | File | Reference App | Tests |
| --- | --- | --- | --- |
| Python | [`maf/python/madis_maf.py`](maf/python/madis_maf.py) | [`maf/examples/ivr_auto_attendant.py`](maf/examples/ivr_auto_attendant.py) | [`maf/tests/test_maf_sdk.py`](maf/tests/test_maf_sdk.py) |
| JavaScript | [`maf/javascript/madis-maf.mjs`](maf/javascript/madis-maf.mjs) | [`maf/examples/call_router.mjs`](maf/examples/call_router.mjs) | [`maf/tests/test_maf_sdk.mjs`](maf/tests/test_maf_sdk.mjs) |
| TypeScript | [`maf/typescript/madis-maf.ts`](maf/typescript/madis-maf.ts) | [`maf/examples/call_router.mjs`](maf/examples/call_router.mjs) | [`maf/typescript/test_maf_sdk.ts`](maf/typescript/test_maf_sdk.ts) |
| Go | [`maf/go/madismaf.go`](maf/go/madismaf.go) | [`maf/examples/call_controller.go`](maf/examples/call_controller.go) | [`maf/go/madismaf_test.go`](maf/go/madismaf_test.go) |
| Erlang | [`maf/erlang/madis_maf.erl`](maf/erlang/madis_maf.erl) | — | — |
| Weft | [`maf/weft/madis_maf.weft`](maf/weft/madis_maf.weft) | — | — |

For a complete step-by-step tutorial covering IVR, AI voice bots, smart softswitches, and call center ACD routing, see the **[MAF Developer Guide](maf/DEVELOPER_GUIDE.md)**.


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
 
| Language | Runtime | File | Tests |
| --- | --- | --- | --- |
| Python | Standard library | [`python/madis_carrier.py`](python/madis_carrier.py) | [`python/test_carrier_sdk.py`](python/test_carrier_sdk.py) |
| JavaScript | Server-side `fetch` | [`javascript/madis-carrier.mjs`](javascript/madis-carrier.mjs) | [`javascript/test_carrier_sdk.mjs`](javascript/test_carrier_sdk.mjs) |
| Go | `net/http`, `context`, `encoding/json` | [`go/madiscarrier.go`](go/madiscarrier.go) | [`go/madiscarrier_test.go`](go/madiscarrier_test.go) |
| Lua | LuaSocket; caller supplies JSON | [`lua/madis_carrier.lua`](lua/madis_carrier.lua) | — |
| Erlang | OTP `inets`; caller supplies JSON | [`erlang/madis_carrier.erl`](erlang/madis_carrier.erl) | — |


The machine-readable contracts are [`../api/maf.openapi.yaml`](../api/maf.openapi.yaml)
and [`../api/openapi.yaml`](../api/openapi.yaml).
