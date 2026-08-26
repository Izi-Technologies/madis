# MADIS Application Fabric

The **MADIS Application Fabric (MAF)** is MADIS's language-neutral application
surface. External services written in Go, JavaScript/TypeScript, Python, Erlang,
or another language can observe bounded communication resources and submit
authenticated commands without writing Mako, SQL, SIP bytes, or worker memory.

## Contract status

The MAF HTTP surface is enabled in the standalone admin process. It persists
calls, channels, bridges, media operations, commands, per-call header policy,
and replayable events in PostgreSQL. The machine-readable contract is
[`maf.openapi.yaml`](maf.openapi.yaml).

Mutating requests are durable command-acceptance boundaries: `202` means that
MADIS accepted the command for asynchronous worker processing, not that a SIP
dialog has already changed. The SIP worker remains the owner of signaling
state.

## Operations

### Call lifecycle

| Operation | What it does |
| --- | --- |
| `calls.create` | Originate an outbound INVITE to a SIP URI |
| `calls.answer` | Send 200 OK with `answer_sdp` to an inbound caller |
| `calls.reject` | Send a final error response (486/603) while ringing |
| `calls.hangup` | CANCEL (ringing) or BYE (answered) to end the call |
| `calls.route` | Forward an inbound INVITE to a target, bypassing built-in routing |
| `calls.bridge` | Create a durable bridge between 2-8 channels |
| `calls.transfer` | Blind (REFER) or attended (REFER+Replaces) call transfer |
| `calls.hold` | Place a call on hold (re-INVITE with sendonly) |
| `calls.unhold` | Resume a held call (re-INVITE with sendrecv) |
| `calls.dtmf` | Send a DTMF digit via SIP INFO (dtmf-relay) |
| `calls.media` | Play, record, stop, pause, resume via external media module |
| `calls.headers` | Set per-call SIP header policy (add/set/remove/copy/move) |
| `calls.rtp` | Direct RTPEngine control: offer, answer, delete, query |
| `calls.identity` | STIR/SHAKEN identity: external signing, verification, attestation |

### Caller presentation

`calls.create` and `calls.route` accept optional caller-presentation fields:

- `caller_uri`: full SIP URI to place in the outbound `From` header.
- `caller_id`: telephone number used to build a `sip:` URI on the existing
  From domain when `caller_uri` is omitted.
- `caller_name`: display name for the outbound `From` header.
- `p_asserted_identity`: SIP URI for `P-Asserted-Identity`.
- `privacy`: bounded `Privacy` header value.

These fields are the supported way for applications to control caller ID and
presentation. Generic `calls.headers` rules still protect dialog-owned headers
such as `From`, `To`, `Call-ID`, `CSeq`, `Via`, and `Contact`.

Validation rules:

- `caller_uri` and `p_asserted_identity` must be `sip:` or `sips:` URIs.
- `caller_id` is reduced to digits plus `+` before a URI is generated.
- `caller_name` and `privacy` are bounded text fields and cannot contain CR,
  LF, null bytes, or escaped CR/LF sequences.
- If `caller_uri` is omitted, `caller_id` uses the current From domain.

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/route" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: route-$CALL_ID" \
  --data '{
    "target": "sip:dest@gateway.example.com",
    "transport": "udp",
    "caller_id": "+15551230000",
    "caller_name": "Example Service",
    "p_asserted_identity": "sip:+15551230000@example.net",
    "privacy": "none"
  }'
```

### External STIR/SHAKEN signing

The `calls.identity` operation lets SDKs manage STIR/SHAKEN through external
signing services instead of local key material:

| Action | What it does |
| --- | --- |
| `sign` | Attach a pre-signed Identity header from an external signing API |
| `verify` | Return verification result for an inbound call (orig, dest, attest, alg, iat) |
| `attest` | Set attestation level (A/B/C) for this call |
| `clear` | Remove Identity and P-Attestation-Indicator headers |

**Workflow with an external STI service:**

1. Inbound INVITE arrives → MAF creates call with `call.created` event
2. SDK reads SIP details via `GET /calls/{id}/sip` (includes Identity header)
3. SDK sends the Identity to the external verifier
4. SDK calls `calls.identity` with `action: verify` to emit the result as an event
5. For outbound signing, SDK obtains a signed header from the external signer and calls
   `calls.identity` with `action: sign` + the pre-signed Identity value

```sh
# Attach externally-signed Identity
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/identity" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: identity-$CALL_ID" \
  --data '{
    "action": "sign",
    "identity": "eyJhbGciOiJFUzI1NiIsInBwdCI6InNoYWtlbiIsInR5cCI6InBhc3Nwb3J0IiwieDV1IjoiaHR0cHM6Ly9jZXJ0cy5leGFtcGxlLmNvbS9zdGkucGVtIn0.eyJhdHRlc3QiOiJBIiwiZGVzdCI6eyJ0biI6WyIxNTU1MTIzNDU2NyJdfSwiaWF0IjoxNzE5NjQ4MDAwLCJvcmlnIjp7InRuIjoiMTU1NTk4NzY1NDMifSwib3JpZ2lkIjoiYWJjMTIzIn0.signature;info=<https://certs.example.com/sti.pem>;alg=ES256;ppt=shaken"
  }'

# Get verification result for an inbound call
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/identity" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: verify-$CALL_ID" \
  --data '{"action": "verify"}'
```

**Security:**
- Identity values are validated for CRLF/null injection before header insertion
- Attestation level is derived from the JWT payload, not client-supplied (prevents
  attestation fraud)
- Auto-mode verification respects the `;alg=` parameter from the Identity header
  (prevents HS256 downgrade attacks)
- Verify events emit metadata only (orig, dest, attest, alg) — not the raw JWT

Events: `identity.signed`, `identity.verified`, `identity.attest`, `identity.cleared`.

### Custom SIP headers (X-headers, UUI, etc.)

The `calls.headers` operation lets SDKs add, set, remove, copy, or move any
non-protected SIP header. This includes:

- **X-headers**: `X-Customer-ID`, `X-Billing-Code`, `X-Route-Tag`, etc.
- **User-to-User** (RFC 7433): UUI data passed end-to-end
- **P-Early-Media** (RFC 5009): early media policy
- **Reason** (RFC 3326): call release cause
- **Alert-Info**: distinctive ringing
- **Diversion** (RFC 5806): call forwarding history
- Any RFC-compliant header that is not in the protected list

**Protected headers** (cannot be modified — proxy/dialog integrity):
`Via`, `Route`, `Record-Route`, `Path`, `Content-Length`, `Content-Type`,
`Max-Forwards`, `Call-ID`, `CSeq`, `From`, `To`, `Contact`, `Authorization`,
`Proxy-Authorization`, `WWW-Authenticate`, `Proxy-Authenticate`

Example — add User-to-User and a custom billing header:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/headers" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: headers-$CALL_ID" \
  --data '{
    "headers": [
      {"action": "add", "name": "User-to-User", "value": "323435363738;encoding=hex"},
      {"action": "add", "name": "X-Billing-Code", "value": "acct-12345"},
      {"action": "set", "name": "Alert-Info", "value": "<http://example.com/ring.wav>"},
      {"action": "remove", "name": "P-Early-Media"},
      {"action": "add", "name": "Reason", "value": "SIP;cause=302;text=\"Moved\"", "method": "BYE", "direction": "outbound"}
    ]
  }'
```

Header policies are:
- **Per-call**: scoped to one MAF call, not global
- **Method-filtered**: apply only to specific SIP methods (`*` = all)
- **Direction-filtered**: `inbound`, `outbound`, or `both`
- **Priority-ordered**: applied in the order specified
- **Bounded**: max 32 operations per call, 4KB per value, 128-byte names

### Capacity policies

MAF can hold generic call admission policies in PostgreSQL and enforce a global
active-call ceiling for API-originated calls. Set `SIP_MAF_MAX_ACTIVE_CALLS`
for an environment-level limit, or create a policy:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/capacity/policies" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "name": "global-default",
    "selector_type": "global",
    "max_active_calls": 10000,
    "max_cps": 500,
    "reject_sip_code": 503,
    "enabled": true
  }'
```

Applications can use source or target policies for their own admission logic,
while Madis enforces the global active-call ceiling in the MAF create path.

The current worker implementation enforces:

- Environment-level global active-call limit from `SIP_MAF_MAX_ACTIVE_CALLS`.
- Database-backed enabled global policies from `maf_capacity_policies`.
- The lowest non-zero configured active-call limit wins.
- API-originated calls over the active-call ceiling return `503`.

Policy fields:

| Field | Purpose |
| --- | --- |
| `name` | Tenant-scoped unique policy name |
| `selector_type` | `global`, `tenant`, `source_ip`, or `target` |
| `selector_value` | Optional selector value for application-side policy use |
| `max_active_calls` | Maximum active calls; `0` disables this limit |
| `max_cps` | Calls-per-second value stored for application-side policy use |
| `reject_sip_code` | Preferred reject code for application-side policy use |
| `enabled` | Enables or disables the policy |

### Route Attempts And Final State

Call resources include `route_attempts`, `final_sip_code`, `final_reason`, and
`ended_by`. This makes answered, rejected, canceled, failed, and timed-out calls
visible without reconstructing state from command rows.

Route attempts are inserted when a `calls.route` command starts worker-side
delivery and are updated when delivery is sent, fails, receives a terminal SIP
response, or times out. Each attempt records target URI, transport, mode,
status, SIP code, error code, error message, and timestamps.

Final states are normalized as:

| Condition | Final state | Ended by |
| --- | --- | --- |
| BYE/CANCEL transaction completes | `ended` | `remote` |
| 487 final response | `canceled` | `remote` |
| 486 or 603 final response | `rejected` | `remote` |
| Other 3xx-6xx final response | `failed` | `remote` |
| INVITE transaction timeout | `timeout` or `canceled` | `timer` |
| Application reject command | `rejected` | `application` |

Example call resource fragment:

```json
{
  "call_id": "call-abc",
  "state": "failed",
  "from_uri": "sip:alice@example.net",
  "to_uri": "sip:bob@example.net",
  "application_data": {
    "rtp_status": "offered",
    "rtp_action": "offer"
  },
  "final_sip_code": 503,
  "final_reason": "Service Unavailable",
  "ended_by": "remote",
  "route_attempts": [
    {
      "target": "sip:gateway.example.net",
      "transport": "udp",
      "mode": "proxy",
      "status": "failed",
      "sip_code": 503,
      "error_code": "sip_final_response",
      "error_message": "Service Unavailable"
    }
  ]
}
```

### SDK-controlled routing

With `SIP_MAF_INBOUND_MODE=control` or `SIP_MAF_INBOUND_MODE=route`, an
authenticated initial INVITE becomes a tenant-scoped MAF call. The SDK can
then decide where to route it using `calls.route`:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/route" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: route-$CALL_ID" \
  --data '{"target":"sip:dest@gateway.example.com","transport":"udp"}'
```

This completely bypasses the built-in routing engine (dialplan, routing rules,
dispatch sets, LCR). The SDK makes the routing decision based on its own
business logic, external databases, or real-time signals.

Set `"mode": "b2bua"` in the route request to terminate both SIP legs locally
instead of proxy forwarding. Requires `SIP_B2BUA=1`.

### RTPEngine media control

The `calls.rtp` operation gives the SDK direct control over the RTPEngine
media relay:

| Action | Request fields | Description |
| --- | --- | --- |
| `offer` | `sdp`, `from_tag`, `flags?` | Send SDP to RTPEngine, get rewritten SDP with relay addresses |
| `answer` | `sdp`, `from_tag`, `to_tag`, `flags?` | Complete media session with answerer's SDP |
| `delete` | — | Tear down the RTP relay session |
| `query` | — | Check current RTP state for the call |

Per-call flags override the global RTPEngine profile (`ICE=force`, `DTLS=passive`, etc.):

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/rtp" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: rtp-offer-$CALL_ID" \
  --data '{"action":"offer","sdp":"v=0\r\n...","from_tag":"abc123","flags":"ICE=force DTLS=passive"}'
```

### SIP message inspection

`GET /admin/api/v1/maf/calls/{call_id}/sip` returns full SIP-level details
from the call's `application_data`. For inbound calls:

```json
{
  "sip_call_id": "abc@192.0.2.10",
  "direction": "inbound",
  "transport": "UDP",
  "nat": "true",
  "source_ip": "203.0.113.10",
  "source_port": 5060,
  "request_uri": "sip:+15551234567@proxy.example.com",
  "user_agent": "Ooma/2.3.0",
  "p_asserted_identity": "sip:+15559876543@carrier.example.com",
  "identity": "<base64-passport>",
  "identity_verified": "true",
  "sdp": "v=0\r\n...",
  "emergency": true,
  "p_access_network_info": "3GPP-E-UTRAN-FDD;network-provided"
}
```

When the call is answered, the remote party's details are merged:

```json
{
  "remote_sdp": "v=0\r\n...",
  "remote_contact": "sip:bob@203.0.113.20:5060",
  "remote_user_agent": "Ooma/2.3.0"
}
```

This gives SDKs full visibility into caller identity, STIR/SHAKEN attestation,
codec negotiation, and NAT topology without parsing raw SIP.

### Emergency call detection

Inbound INVITEs to emergency URIs (`urn:service:sos`) or well-known numbers
(911, 112, 999, etc.) are flagged in the SIP inspection data with
`"emergency": true`. Emergency calls bypass SIP authentication and route
directly to `SIP_EMERGENCY_TARGET` (the E-CSCF).

SDKs can detect emergency calls via the `call.created` event or the
`GET /calls/{id}/sip` endpoint and apply special handling (priority routing,
location services, mandatory recording).

Configure additional emergency numbers via the MAF config API:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/config" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"key":"security_emergency_numbers","value":"933,988,211"}'
```

### Registration and presence

```sh
# List all online users
curl "$MAF_BASE_URL/api/v1/maf/presence" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Check if a specific user is online
curl "$MAF_BASE_URL/api/v1/maf/presence/alice@example.com" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# List active SIP registration bindings
curl "$MAF_BASE_URL/api/v1/maf/registrations?aor=alice@example.com&limit=50" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

The presence endpoint returns AOR, contact count, and last-seen timestamp.
The per-user endpoint returns all active contacts with transport, source IP,
expiry, and update time. The registrations endpoint returns raw binding data.

### Call detail records

```sh
curl "$MAF_BASE_URL/api/v1/maf/cdr?call_id=call-abc&limit=10" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

Returns caller, callee, status, gateway, SIP code, timestamps, and duration.

### Security control

SDKs can manage IP bans programmatically:

```sh
# List active bans
curl "$MAF_BASE_URL/api/v1/maf/security/bans" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Ban an IP (write scope required)
curl -X POST "$MAF_BASE_URL/api/v1/maf/security/bans" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"source_ip":"192.0.2.99","reason":"abuse","permanent":"false","duration_min":60}'

# Unban an IP
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/security/bans/192.0.2.99" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Routing rules

Full CRUD for the routing rules engine:

```sh
# List all routing rules
curl "$MAF_BASE_URL/api/v1/maf/routing/rules" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create a routing rule
curl -X POST "$MAF_BASE_URL/api/v1/maf/routing/rules" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"match_prefix":"+1212","action":"route:nyc-gateway","priority":5,"description":"NYC local calls"}'

# Delete a routing rule
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/routing/rules/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

Rules support all match conditions (prefix, caller, source IP, time-of-day,
day-of-week, ANI group) and actions (route, dispatch, reject, redirect,
forward, lcr, failover, b2bua, continue).

### Gateways

```sh
# List gateways
curl "$MAF_BASE_URL/api/v1/maf/gateways" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create/update a gateway
curl -X POST "$MAF_BASE_URL/api/v1/maf/gateways" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"carrier-a","address":"10.0.1.100","port":5060,"transport":"UDP"}'

# Delete a gateway
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/gateways/7" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### DIDs (inbound numbers)

```sh
# List DIDs
curl "$MAF_BASE_URL/api/v1/maf/dids" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Map a DID to a user
curl -X POST "$MAF_BASE_URL/api/v1/maf/dids" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"number":"+15551234567","destination_user":"alice","description":"Main line"}'

# Delete a DID
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/dids/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Dispatch sets (load balancing)

```sh
# List dispatch sets with members
curl "$MAF_BASE_URL/api/v1/maf/dispatch-sets" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create a dispatch set
curl -X POST "$MAF_BASE_URL/api/v1/maf/dispatch-sets" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"us-east-carriers","algorithm":"round-robin"}'
```

Algorithms: `round-robin`, `weight`, `priority`, `hash`, `hash-user`, `broadcast`.

### Dialplan management

CRUD for tenant-scoped dialplans (number translation, prefix stripping, etc.):

```sh
curl "$MAF_BASE_URL/api/v1/maf/dialplans" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/dialplans" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"strip-plus1","match_prefix":"+1","strip_digits":2,"prepend":"1"}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/dialplans/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### IP auth management

Manage IP-based authentication entries (trusted peers, carrier IPs):

```sh
curl "$MAF_BASE_URL/api/v1/maf/ip-auth" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/ip-auth" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"ip":"10.0.1.100","description":"Carrier A trunk"}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/ip-auth/7" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Access control

Full CRUD for access control entries (allow/deny rules by IP or subnet):

```sh
curl "$MAF_BASE_URL/api/v1/maf/access-control" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/access-control" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"rule":"allow","source":"10.0.0.0/8","description":"Internal network"}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/access-control/5" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Global header rules

Full CRUD for header manipulation rules applied globally:

```sh
curl "$MAF_BASE_URL/api/v1/maf/header-rules" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/header-rules" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"action":"remove","name":"X-Debug","direction":"outbound"}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/header-rules/3" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Billing event outbox

Read pending billing events and acknowledge processing. Events stay in the
outbox until acknowledged, ensuring at-least-once delivery to billing systems:

```sh
curl "$MAF_BASE_URL/api/v1/maf/billing/events" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/billing/events/ack" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"event_ids":["evt_01J...","evt_01K..."]}'
```

### Security audit events

Read security audit events (auth failures, ban triggers, rate limit hits):

```sh
curl "$MAF_BASE_URL/api/v1/maf/security/events" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

### ANI groups

Manage ANI (caller ID) groups for routing rule matching:

```sh
curl "$MAF_BASE_URL/api/v1/maf/ani-groups" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

curl -X POST "$MAF_BASE_URL/api/v1/maf/ani-groups" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"vip-callers","numbers":["+15551234567","+15559876543"]}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/ani-groups/2" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### Active calls

List all active (non-ended) calls across the tenant:

```sh
curl "$MAF_BASE_URL/api/v1/maf/calls/active" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

The active-call list excludes `ended`, `failed`, `canceled`, `rejected`, and
`timeout` calls. Each row includes from/to URI, application data, final state
fields when present, and timestamps so dashboards can render live call state
without fetching every individual call resource.

### Dispatch membership

Add or remove gateways from dispatch sets:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/dispatch-members" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"dispatch_set_id":3,"gateway_id":7,"weight":100,"priority":1}'

curl -X DELETE "$MAF_BASE_URL/api/v1/maf/dispatch-members/12" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

### User management

Full CRUD for SIP digest authentication users:

```sh
# List users
curl "$MAF_BASE_URL/api/v1/maf/users" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Create or update a user (password is hashed to HA1 server-side)
curl -X POST "$MAF_BASE_URL/api/v1/maf/users" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"username":"alice","password":"secret123"}'

# Disable a user (soft delete — preserves CDR references)
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/users/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

Passwords are never stored in plaintext — the API computes the SIP Digest
HA1 hash (`MD5(username:realm:password)`) server-side and stores only the hash.

### Runtime log level

Change the log verbosity at runtime without restarting:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/log-level" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"level":"debug"}'
```

Levels: `error` (quietest), `warn`, `info` (default), `debug` (verbose).
Write scope required.

### Call webhooks

Register HTTP endpoints that receive real-time push notifications when call
events occur. No polling needed — Madis POSTs to your URL.

```sh
# Register a webhook
curl -X POST "$MAF_BASE_URL/api/v1/maf/webhooks" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "url": "https://app.example.com/webhooks/calls",
    "events": ["call.created", "call.answered", "call.ended"],
    "secret": "whsec_your_signing_secret"
  }'

# List webhooks
curl "$MAF_BASE_URL/api/v1/maf/webhooks" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Delete a webhook
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/webhooks/3" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

When a matching event fires, Madis POSTs the event JSON to the webhook URL
with HMAC-SHA256 signature verification:

```http
POST /webhooks/calls HTTP/1.1
Content-Type: application/json
X-Madis-Signature: sha256=abc123...

{"call_id":"call-abc","state":"answered","sip_code":200,...}
```

Verify the signature in your handler: `sha256(secret + "|" + body)`.

### Call tags

Attach arbitrary key-value metadata to any call. Tags are stored in
`application_data` and visible in the call resource and SIP inspection:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/tags" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"tags":{"priority":"high","department":"sales","campaign_id":"camp-2026Q3","customer_id":"cust-42"}}'
```

Use tags for:
- Call routing decisions (`calls.route` based on tag values)
- Billing correlation (attach account/rate-card IDs)
- Analytics (department, campaign, priority tracking)
- Custom business logic in your event handlers

### Number intelligence

Built-in number database for carrier, type, country, and spam scoring.
Query during call routing for intelligent decisions:

```sh
# Look up a number
curl "$MAF_BASE_URL/api/v1/maf/number/+15551234567" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Response:
# {"number":"+15551234567","carrier":"AT&T","type":"mobile","country":"US","spam_score":0}

# Populate number intelligence
curl -X POST "$MAF_BASE_URL/api/v1/maf/number" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"number":"+15551234567","carrier":"AT&T","type":"mobile","country":"US","spam_score":0}'
```

Use number intelligence for:
- Spam call blocking (reject calls with high spam_score)
- Carrier-specific routing (route AT&T numbers through AT&T trunk)
- Geographic routing (route US numbers to US gateways)
- Number type handling (mobile vs landline vs VoIP)

**SDK example — intelligent call routing:**

```python
from madis_maf import MadisMaf

client = MadisMaf("https://proxy.example.net/admin", token)

for event in client.subscribe(event_type="call.created"):
    call_id = event["call_id"]
    caller = event["payload"].get("from", "")
    
    # Look up the caller's number
    info = client.number_lookup(caller)
    
    # Tag the call with intelligence
    client.tag_call(call_id, {
        "carrier": info.get("carrier", "unknown"),
        "spam_score": info.get("spam_score", 0),
        "country": info.get("country", "unknown"),
    })
    
    # Route based on intelligence
    if info.get("spam_score", 0) > 80:
        client.reject_call(call_id, sip_code=603)
    elif info.get("country") == "US":
        client.route_call(call_id, "sip:us-gateway.example.com")
    else:
        client.route_call(call_id, "sip:intl-gateway.example.com")
```

### Declarative call flows

Define call logic as a JSON state machine. The proxy executes steps
sequentially — if a step times out or is rejected, it advances to the next:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/flow" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: flow-$CALL_ID" \
  --data '{
    "steps": [
      {"action": "ring", "target": "sip:alice@example.com", "timeout": 30},
      {"action": "ring", "target": "sip:bob@example.com", "timeout": 20},
      {"action": "play", "resource": "voicemail-greeting.wav"},
      {"action": "record", "max_duration": 60},
      {"action": "hangup"}
    ]
  }'
```

**SDK example — ring group with voicemail fallback:**

```python
client.set_call_flow(call_id, steps=[
    {"action": "ring", "target": "sip:sales-1@pbx.example.com", "timeout": 15},
    {"action": "ring", "target": "sip:sales-2@pbx.example.com", "timeout": 15},
    {"action": "ring", "target": "sip:sales-3@pbx.example.com", "timeout": 15},
    {"action": "play", "resource": "all-agents-busy.wav"},
    {"action": "hangup"},
])
```

### Scheduled calls

Schedule outbound calls for a future time. The proxy originates the call
at the scheduled time:

```sh
# Schedule a call for 3pm today
curl -X POST "$MAF_BASE_URL/api/v1/maf/scheduled-calls" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{
    "from": "sip:reminder@example.com",
    "to": "sip:+15551234567@carrier.example.com",
    "scheduled_at": "2026-08-26T15:00:00Z",
    "application_data": {"purpose": "appointment-reminder", "patient_id": "P-12345"}
  }'

# List scheduled calls
curl "$MAF_BASE_URL/api/v1/maf/scheduled-calls" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Cancel a scheduled call
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/scheduled-calls/42" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

Use cases: appointment reminders, scheduled callbacks, time-zone-aware
outbound campaigns, automated follow-up calls.

### Call queues

Programmable call queues with agent routing strategies:

```sh
# Create a queue
curl -X POST "$MAF_BASE_URL/api/v1/maf/queues" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"support","strategy":"round-robin","max_wait_sec":300}'

# Add agents to the queue
curl -X POST "$MAF_BASE_URL/api/v1/maf/queues/1/members" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"agent_uri":"sip:agent1@pbx.example.com","priority":1}'

# List queues
curl "$MAF_BASE_URL/api/v1/maf/queues" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Remove an agent
curl -X DELETE "$MAF_BASE_URL/api/v1/maf/queues/1/members/3" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

Strategies: `round-robin`, `ring-all`, `longest-idle`, `random`.

### Conference rooms

Programmable conference bridges with PIN access and recording:

```sh
# Create a conference room
curl -X POST "$MAF_BASE_URL/api/v1/maf/conferences" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"name":"standup","pin":"1234","max_participants":10,"record":true}'

# List conferences
curl "$MAF_BASE_URL/api/v1/maf/conferences" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

### Cluster health

```sh
curl "$MAF_BASE_URL/api/v1/maf/cluster" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"
```

Returns all cluster nodes with ID, address, port, region, status
(`active`/`stale`), last heartbeat, and start time.

### Runtime config — programmable proxy behavior

Operators configure Madis entirely through the MAF API. Config changes take
effect within 5 seconds via the heartbeat DB sync — no restart needed.

```sh
# Read all config
curl "$MAF_BASE_URL/api/v1/maf/config" \
  -H "Authorization: Bearer $SIP_MAF_API_READ_TOKEN"

# Set a config value
curl -X POST "$MAF_BASE_URL/api/v1/maf/config" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"key":"sip_invite_rate_limit","value":"50"}'
```

**Configurable at runtime via MAF (no restart):**

| Category | Keys | Examples |
| --- | --- | --- |
| Rate limits | `sip_rate_limit`, `sip_invite_rate_limit`, `sip_register_rate_limit`, `sip_user_rate_limit` | Per-IP and per-method throttling |
| Security | `security_*` | Auth failure threshold, ban duration, whitelist IPs |
| Fraud | `sip_fraud_prefixes` | Comma-separated premium/IRSF prefixes |
| Scanners | `sip_scanner_ua_list` | Comma-separated scanner User-Agent substrings |
| Emergency | `sip_emergency_*` | Emergency numbers, E-CSCF target |
| Registration | `sip_max_reg_expires`, `sip_min_expires` | Registration expiry bounds |
| Capacity | `sip_call_state_capacity`, `sip_per_ip_conn_limit`, `sip_conn_idle_timeout`, `sip_max_message_size` | Call and connection limits |
| Media | `rtpengine_*` | RTPEngine host/port/flags/profile |
| STIR/SHAKEN | `stir_shaken_enabled`, `stir_shaken_attestation`, `stir_shaken_cert_url`, `stir_shaken_mode` | Identity signing and verification |
| Session timers | `sip_session_timer_*` | RFC 4028 session interval bounds |
| Auth | `sip_digest_algorithm` | Digest authentication profile |
| Features | `sip_outbound`, `sip_event_package*`, `sip_tls_reuse`, `sip_b2bua`, `sip_cluster*`, `sip_drain` | Feature toggles |
| IMS | `sip_ims_*` | All IMS configuration |
| HEP | `sip_hep_*` | HEP capture settings |
| Apps/modules | `sip_app_*`, `sip_module_*` | External application and module endpoints |

**Not changeable at runtime (requires restart):**
bind IP, ports, worker counts, TLS cert/key paths, DB URLs, private keys.

#### SDK examples

```python
# Python — configure a carrier's rate limits and fraud protection
client = MadisMaf("https://proxy.example.net/admin", token)
client.set_config("sip_invite_rate_limit", "30")
client.set_config("sip_register_rate_limit", "5")
client.set_config("sip_fraud_prefixes", "+900,+809,+870,+881")
client.set_config("sip_scanner_ua_list", "sipvicious,friendly-scanner")
client.set_config("sip_max_reg_expires", "1800")
```

```typescript
// TypeScript — enable STIR/SHAKEN for a deployment
await client.setConfig("stir_shaken_enabled", "true");
await client.setConfig("stir_shaken_mode", "es256");
await client.setConfig("stir_shaken_cert_url", "https://certs.example.com/sti.pem");
await client.setConfig("stir_shaken_attestation", "A");
```

```go
// Go — configure RTPEngine and enable features
client.SetConfig(ctx, "rtpengine_enabled", "true", "")
client.SetConfig(ctx, "rtpengine_host", "10.0.1.50", "")
client.SetConfig(ctx, "rtpengine_port", "2223", "")
client.SetConfig(ctx, "sip_event_packages", "1", "")
client.SetConfig(ctx, "sip_b2bua", "1", "")
```

#### Full programmable proxy example

A complete operator setup using only the SDK — no config files, no restarts:

```python
from madis_maf import MadisMaf

client = MadisMaf("https://proxy.example.net/admin", "write-token-here")

# 1. Configure the proxy
client.set_config("sip_invite_rate_limit", "100")
client.set_config("sip_register_rate_limit", "20")
client.set_config("sip_fraud_prefixes", "+900,+809")
client.set_config("stir_shaken_enabled", "true")
client.set_config("stir_shaken_mode", "es256")
client.set_config("rtpengine_enabled", "true")
client.set_config("rtpengine_host", "10.0.1.50")

# 2. Add infrastructure
client.create_gateway("carrier-a", "10.0.1.100", 5060, "UDP")
client.create_gateway("carrier-b", "10.0.2.100", 5060, "UDP")
client.create_dispatch_set("us-carriers", "round-robin")
client.create_dispatch_member(dispatch_set_id=1, gateway_id=1, weight=100)
client.create_dispatch_member(dispatch_set_id=1, gateway_id=2, weight=50)

# 3. Add routing
client.create_routing_rule(action="dispatch:us-carriers", match_prefix="+1", priority=5)
client.create_routing_rule(action="reject:403:Blocked", match_prefix="+900", priority=1)
client.create_dialplan(match_prefix="+1", callee_action="strip:1", direction="outbound")

# 4. Add DIDs and users
client.create_did("+15551234567", "alice")
client.create_did("+15559876543", "bob")
client.create_user("alice", "alice-secret")
client.create_user("bob", "bob-secret")

# 5. Add IP auth for carrier trunks
client.create_ip_auth("10.0.1.100", description="Carrier A trunk")
client.create_ip_auth("10.0.2.100", description="Carrier B trunk")

# 6. Add access control
client.create_access_control("allow", "10.0.0.0/8", description="Internal")
client.create_access_control("deny", "192.0.2.0/24", description="Known bad range")

# 7. Monitor
for event in client.subscribe(event_type="call.created"):
    print(f"New call: {event['payload']}")
```

This replaces config files entirely. Each carrier runs the same Madis binary
with different SDK-driven configuration. The proxy is a programmable platform,
not a config-file appliance.

All other keys (TLS paths, credentials, DB URLs, private keys) are blocked
with `403`.

### Charging authorization

SDKs can authorize or deny charges for MAF-controlled calls:

```sh
# Authorize charge
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/charge" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"

# Deny charge
curl -X POST "$MAF_BASE_URL/api/v1/maf/calls/$CALL_ID/charge-deny" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN"
```

The decision is stored in the call's `application_data` as
`charge_authorized: true/false` and can be read via the call resource or
SIP inspection endpoint.

### Database independence

MAF can use its own PostgreSQL database via `SIP_MAF_DB_URL`, separate from
the core SIP proxy database (`SIP_DB_URL`). This lets operators:

- Isolate MAF state (calls, events, commands) from proxy tables
- Point MAF at a different database cluster for independent scaling
- Run MAF without any core SIP database when using SDK-controlled routing

If `SIP_MAF_DB_URL` is not set, MAF uses `SIP_DB_URL` as before.

### NAT awareness

MAF calls include NAT metadata in creation events. Inbound INVITEs are
NAT-fixed (Contact URI + SDP c=/o= rewrite) before caching. Outbound 200 OK
responses have their SDP NAT-fixed before storage. The SDK sees clean,
routable addresses regardless of endpoint topology.

### Custom application events

SDKs can publish their own events into the MAF event stream. Custom events
must use the `app.` prefix:

```sh
curl -X POST "$MAF_BASE_URL/api/v1/maf/events" \
  -H "Authorization: Bearer $SIP_MAF_API_TOKEN" \
  -H "Content-Type: application/json" \
  --data '{"event_type":"app.workflow.step_selected","call_id":"call-abc","payload":"{\"step\":\"sales\"}"}'
```

Custom events appear in the same event stream and WebSocket subscription as
system events. The `call_id` must reference an existing call in the tenant.

## Enabled HTTP routes

```text
POST   /admin/api/v1/maf/calls                          — create call
GET    /admin/api/v1/maf/calls/{call_id}                 — get call
POST   /admin/api/v1/maf/calls/{call_id}/answer          — answer
POST   /admin/api/v1/maf/calls/{call_id}/reject          — reject
POST   /admin/api/v1/maf/calls/{call_id}/hangup          — hangup
POST   /admin/api/v1/maf/calls/{call_id}/route           — SDK routing
POST   /admin/api/v1/maf/calls/{call_id}/bridges         — bridge channels
POST   /admin/api/v1/maf/calls/{call_id}/transfer        — blind/attended transfer
POST   /admin/api/v1/maf/calls/{call_id}/hold            — hold
POST   /admin/api/v1/maf/calls/{call_id}/unhold          — unhold
POST   /admin/api/v1/maf/calls/{call_id}/dtmf            — send DTMF
POST   /admin/api/v1/maf/calls/{call_id}/media           — media control
POST   /admin/api/v1/maf/calls/{call_id}/headers         — header policy
POST   /admin/api/v1/maf/calls/{call_id}/rtp             — RTPEngine control
POST   /admin/api/v1/maf/calls/{call_id}/identity        — STIR/SHAKEN identity
GET    /admin/api/v1/maf/calls/{call_id}/sip             — SIP inspection
POST   /admin/api/v1/maf/calls/{call_id}/charge          — authorize charge
POST   /admin/api/v1/maf/calls/{call_id}/charge-deny     — deny charge
GET    /admin/api/v1/maf/registrations                    — active registrations
GET    /admin/api/v1/maf/presence                         — online users
GET    /admin/api/v1/maf/presence/{aor}                   — user presence
GET    /admin/api/v1/maf/cdr                              — call detail records
GET    /admin/api/v1/maf/security/bans                    — active bans
POST   /admin/api/v1/maf/security/bans                   — ban IP
DELETE /admin/api/v1/maf/security/bans/{ip}               — unban IP
GET    /admin/api/v1/maf/routing/rules                    — list routing rules
POST   /admin/api/v1/maf/routing/rules                   — create routing rule
DELETE /admin/api/v1/maf/routing/rules/{id}               — delete routing rule
GET    /admin/api/v1/maf/gateways                         — list gateways
POST   /admin/api/v1/maf/gateways                        — create/update gateway
DELETE /admin/api/v1/maf/gateways/{id}                    — delete gateway
GET    /admin/api/v1/maf/dids                             — list DIDs
POST   /admin/api/v1/maf/dids                            — create/update DID
DELETE /admin/api/v1/maf/dids/{id}                        — delete DID
GET    /admin/api/v1/maf/dispatch-sets                    — list dispatch sets
POST   /admin/api/v1/maf/dispatch-sets                   — create dispatch set
GET    /admin/api/v1/maf/cluster                          — cluster health
GET    /admin/api/v1/maf/config                           — read config
POST   /admin/api/v1/maf/config                          — set config
GET    /admin/api/v1/maf/events                           — event replay
POST   /admin/api/v1/maf/events                          — publish custom event
GET    /admin/api/v1/maf/events/ws                        — WebSocket subscription
DELETE /admin/api/v1/maf/access-control/{id}              — delete ACL entry
DELETE /admin/api/v1/maf/header-rules/{id}                — delete header rule
DELETE /admin/api/v1/maf/ani-groups/{id}                  — delete ANI group
DELETE /admin/api/v1/maf/dispatch-members/{id}            — remove dispatch member
GET    /admin/api/v1/maf/users                            — list users
POST   /admin/api/v1/maf/users                           — create/update user
DELETE /admin/api/v1/maf/users/{id}                       — disable user
POST   /admin/api/v1/maf/log-level                       — set log level
GET    /admin/api/v1/maf/dialplans                        — list dialplans
POST   /admin/api/v1/maf/dialplans                       — create dialplan
DELETE /admin/api/v1/maf/dialplans/{id}                   — delete dialplan
GET    /admin/api/v1/maf/ip-auth                          — list IP auth entries
POST   /admin/api/v1/maf/ip-auth                         — create IP auth
DELETE /admin/api/v1/maf/ip-auth/{id}                     — delete IP auth
GET    /admin/api/v1/maf/access-control                   — list access control
POST   /admin/api/v1/maf/access-control                  — create ACL entry
GET    /admin/api/v1/maf/header-rules                     — list global header rules
POST   /admin/api/v1/maf/header-rules                    — create header rule
GET    /admin/api/v1/maf/billing/events                   — pending billing events
POST   /admin/api/v1/maf/billing/events/ack              — acknowledge billing event
GET    /admin/api/v1/maf/security/events                  — security audit events
GET    /admin/api/v1/maf/ani-groups                       — list ANI groups
POST   /admin/api/v1/maf/ani-groups                      — create ANI group
GET    /admin/api/v1/maf/calls/active                     — active (non-ended) calls
POST   /admin/api/v1/maf/dispatch-members                — add gateway to dispatch set
GET    /admin/api/v1/maf/capacity/policies                — list capacity policies
POST   /admin/api/v1/maf/capacity/policies               — create/update capacity policy
```

## Authentication and tenant scoping

Read routes use `SIP_MAF_API_READ_TOKEN`. Write routes require
`SIP_MAF_API_TOKEN` (which also permits reads):

```http
Authorization: Bearer <MAF token>
```

Mutating call commands require an `Idempotency-Key` header or body
`command_id`. The key is bound to a request hash; reusing it with a
different body returns `409`. Commands are tenant-scoped by the
`SIP_MAF_TENANT` process setting.

### Tenant isolation

All MAF resources are scoped to the configured tenant (`SIP_MAF_TENANT`):

| Resource | Tenant-scoped | Notes |
| --- | --- | --- |
| Calls, channels, bridges, media, events, commands | Yes | Per-call state |
| Routing rules, gateways, DIDs, dispatch sets, dispatch members | Yes | Infrastructure per tenant |
| Dialplans, IP auth, access control, header rules, ANI groups | Yes | Infrastructure per tenant |
| Billing events | Yes | Per-tenant outbox |
| Registrations, presence | Yes | Per-tenant registration bindings |
| Config | Yes | Per-tenant config keys |
| Cluster nodes | No | Platform-level health monitoring |
| Security bans, security audit events | No | Platform-level; protect all tenants |
| CDR | No | Filterable by call_id; shared audit trail |

A MAF read token in tenant A cannot see tenant B's gateways, routing rules,
registrations, or call state. Write operations insert with the configured
tenant and delete/update only within it.

## Inbound call modes

| Mode | Behavior |
| --- | --- |
| `disabled` | Default. Normal proxy routing; MAF does not intercept INVITEs. |
| `control` | Intercept initial INVITEs. SDK can answer/reject. Built-in routing available for non-MAF calls. |
| `route` | Intercept initial INVITEs. SDK must route via `calls.route`. Built-in routing bypassed. |

### Inbound answer lifecycle

1. An authenticated initial INVITE is persisted as a tenant-scoped `ringing`
   call and emits `call.created` with full SIP metadata (caller, callee,
   User-Agent, P-Asserted-Identity, STIR/SHAKEN Identity, SDP, NAT status).
2. The application reads the call resource, SIP inspection endpoint, or event
   stream and submits `calls.answer` with `answer_sdp`.
3. The worker validates the SDP, creates the dialog tag, records the server
   transaction, sends `200 OK`, and transitions to `answered`.
4. `calls.reject` sends a final response while ringing; `calls.hangup` sends
   `487` before answer or `BYE` after. Remote ACK/BYE/CANCEL remain worker-owned.

## Event system

Events are versioned, replayable, and durable:

```json
{
  "schema": "madis.maf.event.v1",
  "event_id": "evt_01J...",
  "event_type": "call.answered",
  "event_version": 1,
  "call_id": "call_01J...",
  "sequence": 42,
  "occurred_at": "2026-07-29T12:00:00Z",
  "trace_id": "trace_01J...",
  "payload": {}
}
```

### Event types

| Event type | Emitted when | Key payload fields |
| --- | --- | --- |
| `call.created` | New call (outbound or inbound) | `direction`, `nat`, `source_ip` |
| `call.ringing` | Provisional response | `sip_code`, `remote_party` |
| `call.answered` | 2xx received/sent | `sip_code`, `remote_sdp`, `remote_contact` |
| `call.routed` | SDK routed a call | `target`, `transport` |
| `call.transferring` | Transfer initiated | `type` (blind/attended) |
| `call.held` | Call placed on hold | — |
| `call.unheld` | Call resumed | — |
| `call.dtmf` | DTMF digit sent | `digit`, `duration` |
| `call.ended` | BYE/CANCEL/terminal | `ended_by`, `duration_ms`, `sip_code` |
| `call.failed` | Call failed | `sip_code`, `sip_reason` |
| `call.canceled` | Call canceled before answer | `sip_code`, `reason`, `ended_by` |
| `call.rejected` | Application or remote rejection | `sip_code`, `reason`, `ended_by` |
| `call.timeout` | Worker timer expired before final answer | `sip_code`, `reason`, `ended_by` |
| `command.accepted` | Command queued | `operation`, `command_id` |
| `command.completed` | Worker finished | `command_id` |
| `command.failed` | Worker failed | `error_code`, `error_message` |
| `bridge.created` | Bridge created | `bridge_id`, `mode` |
| `media.completed` | Media op done | `media_id`, `operation` |
| `media.failed` | Media op failed | `error_code` |
| `rtp.offer` | RTPEngine offer OK | `action` |
| `rtp.answer` | RTPEngine answer OK | `action` |
| `rtp.deleted` | RTP session torn down | — |
| `rtp.query` | RTP state queried | `state` |
| `identity.signed` | External Identity header attached | `attest`, `source` |
| `identity.verified` | Verification result returned | `result`, `orig`, `dest`, `attest`, `alg` |
| `identity.attest` | Attestation level set | `attest` |
| `identity.cleared` | Identity headers removed | — |
| `app.*` | Custom application events | User-defined |

### Rich event payloads

State transition events include SIP-level detail:

```json
{
  "call_id": "call-abc",
  "state": "ended",
  "source": "sip-worker",
  "ended_by": "BYE",
  "duration_ms": 45230,
  "sip_code": 200
}
```

### WebSocket event streaming

`GET /admin/api/v1/maf/events/ws` provides real-time event streaming over
WebSocket. Bearer-authenticated, read-only, with the `sip` subprotocol.

**Filters:** `?call_id=...`, `?event_type=...`, `?cursor=...`

**Behavior:**
- Each text frame is a JSON event page (same schema as the HTTP endpoint)
- Adaptive poll: 50ms when events flow, backs off to 2s when idle
- 30-second heartbeat frames (`"heartbeat": true`)
- Resume from `next_cursor` on reconnect — no event loss
- Dead-client detection via read polling

**SDK streaming (HTTP long-poll — no WebSocket dependency):**

```python
# Python — blocking generator
for event in client.subscribe(event_type="call.answered"):
    print(event["call_id"], event["payload"])
```

```typescript
// TypeScript — async generator
for await (const event of client.subscribe({ eventType: "call.answered" })) {
  console.log(event.call_id);
}
```

```javascript
// JavaScript — async generator
for await (const event of client.subscribe({ eventType: "call.ended" })) {
  console.log(event.payload.duration_ms);
}
```

```go
// Go — channel-based with context cancellation
ch := make(chan map[string]any, 100)
go client.Subscribe(ctx, 0, "call.answered", "", ch)
for evt := range ch {
    fmt.Println(evt["call_id"])
}
```

**Direct WebSocket (for SIP.js, JsSIP, or custom WebSocket clients):**

```python
# Python — build the WSS URL for websockets library
url = client.ws_url(event_type="call.created")
# → wss://proxy.example.com/admin/api/v1/maf/events/ws?cursor=0&event_type=call.created
```

```typescript
// TypeScript/JavaScript — native WebSocket
const ws = new WebSocket(client.wsUrl({ eventType: "call.answered" }));
ws.onmessage = (e) => {
  const page = JSON.parse(e.data);
  for (const event of page.events) {
    console.log(event.event_type, event.call_id);
  }
};
```

```go
// Go — gorilla/websocket
url := client.WSUrl(0, "call.answered", "")
// Connect with Authorization header
```

## SIP over WebSocket (RFC 7118)

Madis fully implements RFC 7118 for SIP-over-WebSocket transport, compatible
with SIP.js, JsSIP, and other WebRTC SIP stacks:

**Handshake (§4):**
- Standard HTTP Upgrade with `Sec-WebSocket-Key` / `Sec-WebSocket-Accept`
- `Sec-WebSocket-Protocol: sip` echoed in 101 response
- Validates upgrade request structure before accepting

**Transport binding (§5):**
- Via header uses `SIP/2.0/WSS` transport parameter
- Responses to WSS-originated requests route back through WebSocket text
  frames (not raw TCP) — tracked per-transaction with transport type
- Connection-oriented: the proxy maintains the WebSocket association for the
  duration of the dialog

**Connection reuse (§6):**
- Server-side connection tracking stores transport type alongside FD
- `sip_forward_reply` checks transport: WSS connections use `ws_send_text`,
  TCP/TLS use `tcp_write_all`
- Both single-message and reassembly paths track WSS connections

**Security:**
- Per-IP connection limits enforced on WSS accept
- Connection counter properly decremented on cleanup
- PROXY protocol support for load balancer deployments
- Works with TLS termination at the edge (HAProxy/nginx → WSS)

**WebRTC integration:**
- RTPEngine auto-detects WebRTC SDP (ICE candidates, DTLS fingerprint, SAVPF)
- Applies `ICE=force DTLS=passive SDES-off rtcp-mux-offer rtcp-mux-accept`
  for WebRTC-to-SIP bridging
- SIP.js/JsSIP connect to `wss://<proxy>:<wss_port>` with subprotocol `sip`

**Configuration:**

```text
SIP_WSS_PORT=8443          # WebSocket listen port (default: 8443)
SIP_WSS_WORKERS=4          # Worker count
SIP_TLS_CERT=/path/cert    # TLS certificate (shared with SIP TLS)
SIP_TLS_KEY=/path/key      # TLS private key
```

SIP.js example:

```javascript
const ua = new JsSIP.UA({
  sockets: [new JsSIP.WebSocketInterface("wss://proxy.example.com:8443")],
  uri: "sip:alice@example.com",
  password: "secret"
});
ua.start();
```

## Security boundary

- Put the admin listener behind HTTPS with TLS 1.3.
- Keep MAF credentials separate from admin, carrier, and control credentials.
- Use short-lived edge-issued credentials in production.
- Config writes use an allowlist (`rtpengine_*`, `security_*`, select
  `stir_shaken_*`). All other config keys are blocked.
- Bind every request to the configured tenant.
- MAF private keys and privileged tokens stay in server-side services.

## Metrics

When the Prometheus exporter is enabled, MAF publishes counters that are useful
for operational dashboards and alerts:

| Metric | Labels | Meaning |
| --- | --- | --- |
| `madis_maf_commands_total` | `operation`, `status` | Command lifecycle counts |
| `madis_maf_route_attempts_total` | `transport`, `status` | Worker route delivery attempts |
| `madis_maf_rtp_actions_total` | `action`, `result` | RTPEngine command outcomes |
| `madis_maf_stale_cleanups_total` | `reason` | Timer-driven stale call cleanup |

Use these with active-call and event-stream data to monitor command failures,
route failures, RTP failures, stale command cleanup, and unexpected service
behavior.

## SDK clients

Official MAF SDKs in [`../sdk/maf/`](../sdk/maf/):

| Language | Path |
| --- | --- |
| Python | `sdk/maf/python/madis_maf.py` |
| Go | `sdk/maf/go/madismaf.go` |
| TypeScript | `sdk/maf/typescript/madis-maf.ts` |
| JavaScript | `sdk/maf/javascript/madis-maf.mjs` |
| Erlang | `sdk/maf/erlang/madis_maf.erl` |

All SDKs: `X-MAF-Version: 0.7.0`, auto-generated idempotency keys, 64 KiB
body limit, 16-512 char token validation.

### SDK method reference

| Category | Operation | Python | Go | TypeScript | JS | Erlang |
| --- | --- | --- | --- | --- | --- | --- |
| **Calls** | Create | `create_call()` | `CreateCall()` | `createCall()` | `createCall()` | `create_call/4` |
| | Get | `get_call()` | `GetCall()` | `getCall()` | `getCall()` | `get_call/3` |
| | Answer | `answer_call()` | `AnswerCall()` | `answerCall()` | `answerCall()` | `answer_call/4` |
| | Reject | `reject_call()` | `RejectCall()` | `rejectCall()` | `rejectCall()` | `reject_call/4` |
| | Hangup | `hangup_call()` | `HangupCall()` | `hangupCall()` | `hangupCall()` | `hangup_call/3` |
| | Route | `route_call()` | `RouteCall()` | `routeCall()` | `routeCall()` | `route_call/4` |
| | Transfer | `transfer_call()` | `TransferCall()` | `transferCall()` | `transferCall()` | `transfer_call/4` |
| | Hold | `hold_call()` | `HoldCall()` | `holdCall()` | `holdCall()` | `hold_call/3` |
| | Unhold | `unhold_call()` | `UnholdCall()` | `unholdCall()` | `unholdCall()` | `unhold_call/3` |
| | DTMF | `send_dtmf()` | `SendDTMF()` | `sendDtmf()` | `sendDtmf()` | `send_dtmf/4` |
| | Bridge | `bridge_call()` | `BridgeCall()` | `bridgeCall()` | `bridgeCall()` | `bridge_call/4` |
| **Media** | Media | `media()` | `Media()` | `media()` | `media()` | `media/4` |
| | RTP | `rtp_control()` | `RTPControl()` | `rtpControl()` | `rtpControl()` | `rtp_control/4` |
| | Identity | `identity()` | `Identity()` | `identity()` | `identity()` | `identity/4` |
| | Headers | `set_headers()` | `SetHeaders()` | `setHeaders()` | `setHeaders()` | `set_headers/4` |
| **Inspect** | SIP | `sip_inspect()` | `SIPInspect()` | `sipInspect()` | `sipInspect()` | `sip_inspect/3` |
| **Presence** | List | `presence()` | `Presence()` | `presence()` | `presence()` | `presence/2` |
| | User | `presence_user()` | `PresenceUser()` | `presenceUser()` | `presenceUser()` | `presence_user/3` |
| | Registrations | `registrations()` | `Registrations()` | `registrations()` | `registrations()` | `registrations/2` |
| **Records** | CDR | `cdr()` | `CDR()` | `cdr()` | `cdr()` | `cdr/2` |
| **Security** | Bans | `bans()` | `Bans()` | `bans()` | `bans()` | `bans/2` |
| | Ban IP | `ban_ip()` | `BanIP()` | `banIP()` | `banIP()` | `ban_ip/6` |
| | Unban IP | `unban_ip()` | `UnbanIP()` | `unbanIP()` | `unbanIP()` | `unban_ip/3` |
| **Routing** | Rules | `routing_rules()` | `RoutingRules()` | `routingRules()` | `routingRules()` | `routing_rules/2` |
| | Create rule | `create_routing_rule()` | `CreateRoutingRule()` | `createRoutingRule()` | `createRoutingRule()` | `create_routing_rule/3` |
| | Delete rule | `delete_routing_rule()` | `DeleteRoutingRule()` | `deleteRoutingRule()` | `deleteRoutingRule()` | `delete_routing_rule/3` |
| **Infra** | Gateways | `gateways()` | `Gateways()` | `gateways()` | `gateways()` | `gateways/2` |
| | Create GW | `create_gateway()` | `CreateGateway()` | `createGateway()` | `createGateway()` | `create_gateway/3` |
| | Delete GW | `delete_gateway()` | `DeleteGateway()` | `deleteGateway()` | `deleteGateway()` | `delete_gateway/3` |
| | DIDs | `dids()` | `DIDs()` | `dids()` | `dids()` | `dids/2` |
| | Create DID | `create_did()` | `CreateDID()` | `createDID()` | `createDID()` | `create_did/3` |
| | Delete DID | `delete_did()` | `DeleteDID()` | `deleteDID()` | `deleteDID()` | `delete_did/3` |
| | Dispatch sets | `dispatch_sets()` | `DispatchSets()` | `dispatchSets()` | `dispatchSets()` | `dispatch_sets/2` |
| | Create set | `create_dispatch_set()` | `CreateDispatchSet()` | `createDispatchSet()` | `createDispatchSet()` | `create_dispatch_set/3` |
| **Cluster** | Nodes | `cluster()` | `Cluster()` | `cluster()` | `cluster()` | `cluster/2` |
| **Config** | Read | `config()` | `Config()` | `config()` | `config()` | `config/2` |
| | Set | `set_config()` | `SetConfig()` | `setConfig()` | `setConfig()` | `set_config/3` |
| **Charging** | Authorize | `charge_authorize()` | `ChargeAuthorize()` | `chargeAuthorize()` | `chargeAuthorize()` | `charge_authorize/3` |
| | Deny | `charge_deny()` | `ChargeDeny()` | `chargeDeny()` | `chargeDeny()` | `charge_deny/3` |
| **Dialplans** | List | `dialplans()` | `Dialplans()` | `dialplans()` | `dialplans()` | `dialplans/2` |
| | Create | `create_dialplan()` | `CreateDialplan()` | `createDialplan()` | `createDialplan()` | `create_dialplan/3` |
| | Delete | `delete_dialplan()` | `DeleteDialplan()` | `deleteDialplan()` | `deleteDialplan()` | `delete_dialplan/3` |
| **IP Auth** | List | `ip_auth()` | `IPAuth()` | `ipAuth()` | `ipAuth()` | `ip_auth/2` |
| | Create | `create_ip_auth()` | `CreateIPAuth()` | `createIPAuth()` | `createIPAuth()` | `create_ip_auth/3` |
| | Delete | `delete_ip_auth()` | `DeleteIPAuth()` | `deleteIPAuth()` | `deleteIPAuth()` | `delete_ip_auth/3` |
| **ACL** | List | `access_control()` | `AccessControl()` | `accessControl()` | `accessControl()` | `access_control/2` |
| | Create | `create_acl()` | `CreateACL()` | `createACL()` | `createACL()` | `create_acl/3` |
| **Headers** | Global rules | `header_rules()` | `HeaderRules()` | `headerRules()` | `headerRules()` | `header_rules/2` |
| | Create rule | `create_header_rule()` | `CreateHeaderRule()` | `createHeaderRule()` | `createHeaderRule()` | `create_header_rule/3` |
| **Billing** | Events | `billing_events()` | `BillingEvents()` | `billingEvents()` | `billingEvents()` | `billing_events/2` |
| | Acknowledge | `ack_billing_event()` | `AckBillingEvent()` | `ackBillingEvent()` | `ackBillingEvent()` | `ack_billing_event/3` |
| **Security** | Audit events | `security_events()` | `SecurityEvents()` | `securityEvents()` | `securityEvents()` | `security_events/2` |
| **ANI** | List groups | `ani_groups()` | `ANIGroups()` | `aniGroups()` | `aniGroups()` | `ani_groups/2` |
| | Create group | `create_ani_group()` | `CreateANIGroup()` | `createANIGroup()` | `createANIGroup()` | `create_ani_group/3` |
| **Calls** | Active | `active_calls()` | `ActiveCalls()` | `activeCalls()` | `activeCalls()` | `active_calls/2` |
| **Dispatch** | Add member | `create_dispatch_member()` | `CreateDispatchMember()` | `createDispatchMember()` | `createDispatchMember()` | `create_dispatch_member/3` |
| **Capacity** | List policies | `capacity_policies()` | `CapacityPolicies()` | `capacityPolicies()` | `capacityPolicies()` | `capacity_policies/2` |
| | Upsert policy | `upsert_capacity_policy()` | `UpsertCapacityPolicy()` | `upsertCapacityPolicy()` | `upsertCapacityPolicy()` | `upsert_capacity_policy/3` |
| **Events** | Publish | `publish_event()` | `PublishEvent()` | `publishEvent()` | `publishEvent()` | `publish_event/5` |
| | List | `events()` | `Events()` | `events()` | `events()` | `events/3` |
| | Subscribe | `subscribe()` | `Subscribe()` | `subscribe()` | `subscribe()` | — (use events/5) |
| | WS URL | `ws_url()` | `WSUrl()` | `wsUrl()` | `wsUrl()` | `ws_url/4` |
| **Users** | List | `users()` | `Users()` | `users()` | `users()` | — |
| | Create | `create_user()` | `CreateUser()` | `createUser()` | `createUser()` | — |
| | Delete | `delete_user()` | `DeleteUser()` | `deleteUser()` | `deleteUser()` | — |
| **Logging** | Set level | `set_log_level()` | `SetLogLevel()` | `setLogLevel()` | `setLogLevel()` | `set_log_level/3` |
| **Ops** | Health | `health()` | `Health()` | `health()` | `health()` | `health/2` |
| | Reload | `reload()` | `Reload()` | `reload()` | `reload()` | `reload/2` |
| | Delete GW | `delete_gateway()` | `DeleteGateway()` | `deleteGateway()` | `deleteGateway()` | `delete_gateway/3` |
| | Delete DID | `delete_did()` | `DeleteDID()` | `deleteDid()` | `deleteDid()` | `delete_did/3` |
| | Delete set | `delete_dispatch_set()` | `DeleteDispatchSet()` | `deleteDispatchSet()` | `deleteDispatchSet()` | `delete_dispatch_set/3` |
| | Delete config | `delete_config()` | `DeleteConfig()` | `deleteConfig()` | `deleteConfig()` | `delete_config/3` |

### Contract tests

58 route handlers served by the admin process. 56 Python tests in `sdk/maf/tests/` validate the SDK-to-OpenAPI contract:

- **OpenAPI contract** — route coverage, required fields, enum consistency, body limits, auth headers
- **Command lifecycle** — state machine (accepted→processing→completed|failed), staleness, idempotency
- **Cursor recovery** — ordering, resume-from-cursor, duplicate prevention, truncation, heartbeat
- **Load/backpressure** — 1000 rapid commands, 64KB boundary, 100-event pages
- **Tenant auth** — token validation, 401/403 handling, token never in URL or error messages

### Application examples

- `sdk/maf/examples/click_to_call.py` — CLI call originator with event polling
- `sdk/maf/examples/event_monitor.py` — streaming event consumer with reconnection

## Configuration

| Variable | Purpose |
| --- | --- |
| `SIP_MAF_API_TOKEN` | MAF write credential (also permits reads) |
| `SIP_MAF_API_READ_TOKEN` | MAF read-only credential |
| `SIP_MAF_TENANT` | Tenant namespace; defaults to `default` |
| `SIP_MAF_INBOUND_MODE` | `disabled` (default), `control`, or `route` |
| `SIP_MAF_DB_URL` | Separate PostgreSQL for MAF tables; falls back to `SIP_DB_URL` |
| `SIP_MAF_CONTACT_URI` | Override Contact URI in MAF-generated SIP responses |
| `SIP_MAF_MAX_ACTIVE_CALLS` | Environment-level active-call admission ceiling; `0` disables |

## Worker-side implementation

- **Adaptive poll backoff**: 100ms→2s idle, resets on work
- **Transport-aware outbound**: derives transport from target URI scheme
- **Atomic claim**: single `UPDATE WHERE status='accepted'`
- **Single-query state transitions**: no SELECT+UPDATE
- **Event ID uniqueness**: payload hash tiebreaker for sub-millisecond collisions
- **Non-MAF fast path**: skips DB query for non-MAF Call-IDs
- **Rich event payloads**: SIP code, remote SDP, duration in state transitions
- **NAT-aware caching**: Contact + SDP rewritten before storage
- **B2BUA routing mode**: `calls.route` with `mode=b2bua` terminates both legs
- **RFC 7118 WSS transport**: `Sec-WebSocket-Protocol: sip` handshake,
  transport-aware response routing (WebSocket frames vs raw TCP),
  per-transaction transport tracking, per-IP connection limits on WSS
- **Tenant-scoped infrastructure**: routing rules, gateways, DIDs, dispatch
  sets, config, and registrations are all filtered by `SIP_MAF_TENANT`
- **Caller presentation controls**: `calls.create` and `calls.route` can set
  From display/name, P-Asserted-Identity, and Privacy through validated fields
- **Route attempt accounting**: every worker route attempt records target,
  transport, mode, terminal status, SIP code, and failure details
- **Final call state**: rejected, canceled, failed, timed-out, and ended calls
  carry final SIP code, reason, ending party, and ended timestamp
- **RTP status tracking**: RTPEngine offer, answer, and delete update per-call
  application data and metrics
