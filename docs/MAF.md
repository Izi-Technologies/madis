# Madis Application Framework (MAF)

MAF is the programmable boundary of the Madis SIP proxy. It lets you build
telephony applications in **any language** — Python, Go, Node.js, Rust, Java,
PHP, Ruby — by handling JSON over HTTPS. The proxy owns SIP complexity; your
app makes decisions.

## Architecture

```
                    ┌──────────────────────────────┐
                    │        Your Application       │
                    │   (Python / Go / Node / Rust) │
                    └──────────┬───────────────────┘
                               │ HTTPS + JSON
              ┌────────────────┼────────────────────┐
              │                ▼                     │
              │  ┌──────────────────────────┐       │
              │  │   App Gateway (webhook)   │       │
              │  │  SIP_APP_URL / _TOKEN     │       │
              │  └──────────────────────────┘       │
              │                                      │
  SIP ──────▶│  ┌──────────────────────────┐       │
  phones     │  │     Madis SIP Proxy       │       │
  trunks     │  │   (registrar + router)    │       │
  gateways   │  └──────────────────────────┘       │
              │                                      │
              │  ┌──────────────────────────┐       │
              │  │   MAF REST API            │       │
              │  │  /admin/api/v1/maf/*      │       │
              │  └──────────────────────────┘       │
              │                                      │
              │  ┌──────────────────────────┐       │
              │  │   Webhooks (async events) │       │
              │  │  maf_webhooks table       │       │
              │  └──────────────────────────┘       │
              └──────────────────────────────────────┘
```

Three integration surfaces:

| Surface | Direction | Use case |
|---------|-----------|----------|
| **App Gateway** | Proxy → App → Proxy (sync) | Real-time call control: route, reject, modify headers |
| **REST API** | App → Proxy | Originate calls, hangup, transfer, hold, query state |
| **Webhooks** | Proxy → App (async) | Event notifications: call.created, call.answered, etc. |

## Quick start

### 1. Set environment variables

```bash
# App Gateway — your HTTP server receives SIP events
export SIP_APP_URL=https://your-app.example.com/sip
export SIP_APP_TOKEN=your-secret-token-min-16-chars
export SIP_APP_CA=/path/to/ca.pem          # optional, for custom CA
export SIP_APP_CLIENT_CERT=/path/to/cert.pem  # optional, for mTLS
export SIP_APP_CLIENT_KEY=/path/to/key.pem    # optional, for mTLS
export SIP_APP_TIMEOUT_MS=100              # max latency budget (10-1000ms)
export SIP_APP_FAIL_CLOSED=0               # 1 = reject calls when app unreachable

# MAF REST API
export SIP_MAF_API_TOKEN=write-token-min-16-chars
export SIP_MAF_API_READ_TOKEN=read-only-token-min-16-chars
export SIP_MAF_TENANT=default

# Webhooks configured via REST API (see below)
```

### 2. Write your app (any language)

**Python (Flask)**
```python
from flask import Flask, request, jsonify

app = Flask(__name__)

@app.route('/sip', methods=['POST'])
def handle_sip():
    event = request.json
    method = event.get('method', '')
    from_uri = event.get('from', '')
    to_uri = event.get('to', '')

    # Block premium-rate numbers
    if method == 'INVITE':
        callee = to_uri.split('@')[0].replace('sip:', '').replace('<', '')
        if callee.startswith(('900', '976', '1-900')):
            return jsonify(action='reject', status=403, reason='Premium rate blocked')

    # Add billing header
    if method == 'INVITE':
        return jsonify(
            action='continue',
            set_headers='X-Account-ID: 12345\nX-Billing-Plan: premium'
        )

    return jsonify(action='continue')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8090, ssl_context='adhoc')
```

**Go (net/http)**
```go
package main

import (
    "encoding/json"
    "net/http"
    "strings"
)

type SIPEvent struct {
    Schema    string `json:"schema"`
    Event     string `json:"event"`
    Method    string `json:"method"`
    CallID    string `json:"call_id"`
    From      string `json:"from"`
    To        string `json:"to"`
    SourceIP  string `json:"source_ip"`
    RequestURI string `json:"request_uri"`
    Signature string `json:"signature"`
}

type SIPResponse struct {
    Action       string `json:"action"`
    Status       int    `json:"status,omitempty"`
    Reason       string `json:"reason,omitempty"`
    Target       string `json:"target,omitempty"`
    SetHeaders   string `json:"set_headers,omitempty"`
    AddHeaders   string `json:"add_headers,omitempty"`
    RemoveHeaders string `json:"remove_headers,omitempty"`
}

func handler(w http.ResponseWriter, r *http.Request) {
    var event SIPEvent
    json.NewDecoder(r.Body).Decode(&event)

    resp := SIPResponse{Action: "continue"}

    if event.Method == "INVITE" {
        callee := extractUser(event.To)
        // Route to specific gateway based on prefix
        if strings.HasPrefix(callee, "1800") {
            resp = SIPResponse{Action: "route", Target: "sip:tollfree-gw.local:5060"}
        }
    }

    if event.Method == "REGISTER" {
        // Block registrations from unknown IPs
        if !isTrustedIP(event.SourceIP) {
            resp = SIPResponse{Action: "reject", Status: 403, Reason: "Forbidden"}
        }
    }

    w.Header().Set("Content-Type", "application/json")
    json.NewEncoder(w).Encode(resp)
}

func main() {
    http.HandleFunc("/sip", handler)
    http.ListenAndServeTLS(":8090", "cert.pem", "key.pem", nil)
}
```

**Node.js (Express)**
```javascript
const express = require('express');
const app = express();
app.use(express.json());

app.post('/sip', (req, res) => {
  const { method, from, to, call_id, source_ip } = req.body;

  // Business hours routing
  const hour = new Date().getHours();
  if (method === 'INVITE' && (hour < 9 || hour >= 17)) {
    return res.json({
      action: 'redirect',
      target: 'sip:voicemail@vm.example.com'
    });
  }

  // Whitelist-based registration
  if (method === 'REGISTER') {
    const allowedIPs = ['10.0.0.0/8', '192.168.1.0/24'];
    // ... check source_ip against allowedIPs
  }

  res.json({ action: 'continue' });
});

app.listen(8090, () => console.log('MAF app on :8090'));
```

**Rust (axum)**
```rust
use axum::{routing::post, Json, Router};
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
struct SipEvent {
    method: String,
    call_id: String,
    from: String,
    to: String,
    source_ip: String,
}

#[derive(Serialize)]
struct SipResponse {
    action: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    status: Option<i32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    target: Option<String>,
}

async fn handle(Json(event): Json<SipEvent>) -> Json<SipResponse> {
    if event.method == "INVITE" {
        // Rate limit per source IP using your own logic
        return Json(SipResponse {
            action: "continue".into(),
            status: None, reason: None, target: None,
        });
    }
    Json(SipResponse { action: "continue".into(), status: None, reason: None, target: None })
}

#[tokio::main]
async fn main() {
    let app = Router::new().route("/sip", post(handle));
    axum::Server::bind(&"0.0.0.0:8090".parse().unwrap())
        .serve(app.into_make_service()).await.unwrap();
}
```

---

## App Gateway — synchronous call control

Every SIP request/response passes through your app gateway (when configured).
Your app has **100ms** (default) to respond with a routing decision.

### Inbound event (proxy → app)

```json
{
  "schema": "madis.sip.event.v1",
  "event": "request",
  "request_id": "a1b2c3d4...",
  "method": "INVITE",
  "status": 0,
  "transport": "UDP",
  "source_ip": "10.0.0.5",
  "source_port": 5060,
  "request_uri": "sip:bob@example.com",
  "call_id": "abc123@host",
  "from": "<sip:alice@example.com>;tag=xyz",
  "to": "<sip:bob@example.com>",
  "cseq": "1 INVITE",
  "user_agent": "Obi200/2.0",
  "body": "v=0\r\no=...",
  "truncated": false,
  "raw": "INVITE sip:bob@example.com SIP/2.0\r\n...",
  "signature": "sha256-hex-64-chars"
}
```

For responses, `method` is empty and `status` is the SIP response code (e.g., 200).

### Response actions (app → proxy)

| Action | Fields | Effect |
|--------|--------|--------|
| `continue` | `set_headers`, `add_headers`, `remove_headers` | Route normally, optionally modify headers |
| `reject` | `status`, `reason` | Reject with SIP error (e.g., 403 Forbidden) |
| `redirect` | `target` | SIP 302 redirect to target URI |
| `route` | `target` | Override routing — forward to specific target |
| `dispatch` | `target` | Route through named dispatch set |
| `b2bua` | `target` | Back-to-back UA — terminate both legs |
| `replace` | `status`, `reason`, `body` | Replace response (for responses only) |
| `reply` | `status`, `reason`, `body` | Generate response directly |
| `drop` | — | Silently discard the message |
| `module` | `module`, `operation`, `payload` | Invoke a module gateway |

**Example: route + add header**
```json
{
  "schema": "madis.sip.command.v1",
  "request_id": "a1b2c3d4...",
  "action": "continue",
  "set_headers": "X-Account-ID: 42\nX-Billing-Code: PREMIUM",
  "signature": "sha256-hex-64-chars"
}
```

**Example: reject with custom reason**
```json
{
  "schema": "madis.sip.command.v1",
  "request_id": "a1b2c3d4...",
  "action": "reject",
  "status": 486,
  "reason": "User Busy",
  "signature": "sha256-hex-64-chars"
}
```

**Example: redirect to voicemail**
```json
{
  "schema": "madis.sip.command.v1",
  "request_id": "a1b2c3d4...",
  "action": "redirect",
  "target": "sip:voicemail@vm.example.com",
  "signature": "sha256-hex-64-chars"
}
```

### Header manipulation

Headers are newline-separated `Name: value` pairs:

- `set_headers` — replace header if exists, add if not
- `add_headers` — always add (even if header exists)
- `remove_headers` — remove by name (newline-separated names)

**Protected headers** (cannot be modified by the app):
`Via`, `From`, `To`, `Call-ID`, `CSeq`, `Content-Length`, `Max-Forwards`,
`Route`, `Record-Route`

### Signature verification

Every outbound event carries:
```
signature = sha256("madis.sip.event.v2|" + sha256(token) + "|" + sha256(canonical_fields))
```

Every inbound command must carry:
```
signature = sha256("madis.sip.command.v2|" + sha256(token) + "|" + sha256(canonical_fields))
```

Where `canonical_fields` is:
```
request_id|action|target|status|reason|set_headers|add_headers|remove_headers|body|module|operation|payload
```

Signatures use **constant-time comparison** to prevent timing attacks.

---

## REST API — programmatic call control

Base URL: `https://<admin-host>:<admin-port>/admin/api/v1/maf/`

### Authentication

```
Authorization: Bearer <SIP_MAF_API_TOKEN>
```

Two token scopes:
- **Write** (`SIP_MAF_API_TOKEN`) — full access: originate, hangup, transfer
- **Read** (`SIP_MAF_API_READ_TOKEN`) — read-only: query calls, events, registrations

### Endpoints

#### Calls

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/maf/calls` | Originate a new call |
| `GET` | `/maf/calls/{id}` | Get call state |
| `POST` | `/maf/calls/{id}/answer` | Answer (for inbound-controlled calls) |
| `POST` | `/maf/calls/{id}/reject` | Reject with status code |
| `POST` | `/maf/calls/{id}/hangup` | Hang up |
| `POST` | `/maf/calls/{id}/transfer` | Blind or attended transfer |
| `POST` | `/maf/calls/{id}/hold` | Put on hold (re-INVITE with sendonly) |
| `POST` | `/maf/calls/{id}/unhold` | Resume from hold |
| `POST` | `/maf/calls/{id}/dtmf` | Send DTMF (INFO method) |
| `POST` | `/maf/calls/{id}/bridges` | Bridge two calls |
| `POST` | `/maf/calls/{id}/route` | Override routing for pending call |
| `POST` | `/maf/calls/{id}/headers` | Modify SIP headers |
| `POST` | `/maf/calls/{id}/media` | Media control |
| `POST` | `/maf/calls/{id}/rtp` | RTPEngine control |
| `POST` | `/maf/calls/{id}/identity` | Set P-Asserted-Identity |
| `GET` | `/maf/calls/{id}/sip` | Get raw SIP messages |

#### Events

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/maf/events` | List events (paginated) |
| `GET` | `/maf/events?event_type=call.answered` | Filter by type |
| `POST` | `/maf/events` | Post custom event |

#### Resources

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/maf/registrations` | List active registrations |
| `GET` | `/maf/cdr` | List CDR records |
| `GET` | `/maf/presence` | List presence state |
| `GET` | `/maf/presence/{aor}` | Get presence for AOR |
| `GET` | `/maf/routing/rules` | List routing rules |
| `POST` | `/maf/routing/rules` | Create routing rule |
| `DELETE` | `/maf/routing/rules/{id}` | Delete routing rule |
| `GET` | `/maf/gateways` | List gateways |
| `POST` | `/maf/gateways` | Create gateway |
| `GET` | `/maf/security/bans` | List security bans |
| `POST` | `/maf/security/bans` | Create ban |
| `DELETE` | `/maf/security/bans/{id}` | Delete ban |

### Examples

**Originate a call (Python)**
```python
import requests

headers = {'Authorization': 'Bearer your-write-token'}
resp = requests.post('https://admin:8080/admin/api/v1/maf/calls', json={
    'from': 'sip:service@example.com',
    'to': 'sip:+15551234567@example.com',
    'timeout': 30,
    'caller_id': '+15559876543',
    'variables': {'account_id': '42'}
}, headers=headers)
call = resp.json()
print(f"Call ID: {call['call_id']}")
```

**Hang up a call (Go)**
```go
req, _ := http.NewRequest("POST",
    "https://admin:8080/admin/api/v1/maf/calls/"+callID+"/hangup",
    strings.NewReader(`{"reason":"normal_clearing"}`))
req.Header.Set("Authorization", "Bearer "+token)
req.Header.Set("Content-Type", "application/json")
http.DefaultClient.Do(req)
```

**Transfer a call (Node.js)**
```javascript
await fetch(`https://admin:8080/admin/api/v1/maf/calls/${callId}/transfer`, {
  method: 'POST',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  },
  body: JSON.stringify({
    type: 'blind',
    target: 'sip:support@example.com'
  })
});
```

**Query events (curl)**
```bash
curl -H "Authorization: Bearer $READ_TOKEN" \
  "https://admin:8080/admin/api/v1/maf/events?event_type=call.answered&limit=50"
```

---

## Webhooks — async event delivery

Register webhooks via the REST API or directly in the `maf_webhooks` database
table. Events are delivered as signed HTTPS POST requests.

### Register a webhook (curl)

```bash
curl -X POST https://admin:8080/admin/api/v1/maf/webhooks \
  -H "Authorization: Bearer $WRITE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://your-app.example.com/webhooks/madis",
    "events": ["call.created", "call.answered", "call.ended"],
    "secret": "your-webhook-signing-secret"
  }'
```

### Event types

| Event | When | Payload |
|-------|------|---------|
| `call.created` | INVITE initiated | `{call_id, from, to, direction}` |
| `call.ringing` | 180 Ringing received | `{call_id, from, to}` |
| `call.answered` | 200 OK received | `{call_id, from, to, answer_time}` |
| `call.ended` | BYE or timeout | `{call_id, from, to, duration, reason}` |
| `call.routed` | Call forwarded to target | `{call_id, target, transport}` |
| `call.transferring` | REFER sent | `{call_id, type, state}` |
| `call.held` | Put on hold | `{call_id}` |
| `call.unheld` | Resumed from hold | `{call_id}` |
| `call.dtmf` | DTMF digit received | `{call_id, digit}` |
| `bridge.created` | Two calls bridged | `{call_id, bridge_id}` |
| `refer.received` | REFER request arrived | `{call_id, refer_to}` |
| `message.received` | SIP MESSAGE arrived | `{call_id, from, to}` |
| `dialog.state_changed` | BLF state change | `{aor, state, call_id}` |

### Webhook payload

```json
{
  "event_id": "sha256-unique-id",
  "tenant_id": "default",
  "event_type": "call.answered",
  "call_id": "abc123@host",
  "payload": {
    "call_id": "abc123@host",
    "from": "sip:alice@example.com",
    "to": "sip:bob@example.com"
  }
}
```

### Signature verification

Each webhook carries:
```
X-Madis-Signature: sha256=<hex>
```

Verify in your app:
```python
import hashlib
expected = hashlib.sha256((secret + '|' + body).encode()).hexdigest()
assert request.headers['X-Madis-Signature'] == f'sha256={expected}'
```

```go
mac := sha256.Sum256([]byte(secret + "|" + body))
expected := "sha256=" + hex.EncodeToString(mac[:])
// compare with r.Header.Get("X-Madis-Signature")
```

```javascript
const crypto = require('crypto');
const expected = 'sha256=' + crypto.createHash('sha256')
    .update(secret + '|' + body).digest('hex');
// compare with req.headers['x-madis-signature']
```

### Retry policy

Failed webhook deliveries are retried with exponential backoff:
- Attempt 1: immediate
- Attempt 2: after 1 second
- Attempt 3: after 5 seconds
- Attempt 4: after 25 seconds
- Then discarded

---

## Security model

### Authentication layers

| Layer | Mechanism | Config |
|-------|-----------|--------|
| App Gateway | SHA-256 signed payloads + bearer token | `SIP_APP_TOKEN` |
| App Gateway (mTLS) | Client certificate | `SIP_APP_CLIENT_CERT`, `SIP_APP_CLIENT_KEY` |
| REST API (write) | Bearer token | `SIP_MAF_API_TOKEN` |
| REST API (read) | Bearer token | `SIP_MAF_API_READ_TOKEN` |
| Webhooks | HMAC signature per webhook | `secret` field in webhook config |
| Admin UI | Session cookie + password hash | `SIP_ADMIN_PASSWORD` |
| Carrier API | Separate bearer token | `SIP_CARRIER_API_TOKEN` |
| Control API | Separate bearer token | `SIP_CONTROL_API_TOKEN` |

### Security properties

- **Constant-time token comparison** — all bearer and signature checks use XOR
  accumulation, preventing timing side-channels
- **Request ID binding** — app gateway responses must echo the `request_id`,
  preventing replay attacks
- **Protected SIP headers** — Via, From, To, Call-ID, CSeq, Route, Record-Route
  cannot be modified by applications
- **Fail-closed mode** — `SIP_APP_FAIL_CLOSED=1` rejects calls when the app is
  unreachable (default: fail-open, route normally)
- **Payload size limits** — 64KB event payload, 8KB headers, 16 header max
- **API rate limiting** — per-IP token bucket, default 100 req/s
  (`SIP_API_RATE_LIMIT`)
- **Transport security** — HTTPS required for app gateway in production
  (`SIP_APP_ALLOW_HTTP=0` default)

---

## Configuration reference

### App Gateway

| Variable | Default | Description |
|----------|---------|-------------|
| `SIP_APP_URL` | — | HTTPS URL of your app (required to enable) |
| `SIP_APP_TOKEN` | — | Shared secret, min 16 chars (required) |
| `SIP_APP_CA` | — | CA bundle for server verification |
| `SIP_APP_CLIENT_CERT` | — | Client certificate for mTLS |
| `SIP_APP_CLIENT_KEY` | — | Client key for mTLS |
| `SIP_APP_TIMEOUT_MS` | `100` | Max response time (10-1000ms) |
| `SIP_APP_FAIL_CLOSED` | `0` | Reject calls when app unreachable |
| `SIP_APP_ALLOW_HTTP` | `0` | Allow plain HTTP (not recommended) |

### MAF REST API

| Variable | Default | Description |
|----------|---------|-------------|
| `SIP_MAF_API_TOKEN` | — | Write token (originate, hangup, transfer) |
| `SIP_MAF_API_READ_TOKEN` | — | Read-only token (query calls, events) |
| `SIP_MAF_TENANT` | `default` | Tenant identifier for multi-tenant |
| `SIP_MAF_DB_URL` | `SIP_DB_URL` | Separate DB for MAF tables |
| `SIP_MAF_MAX_ACTIVE_CALLS` | `0` | Global call limit (0 = unlimited) |
| `SIP_MAF_INBOUND_MODE` | `disabled` | `control` / `route` / `disabled` |
| `SIP_MAF_CONTACT_URI` | auto | Contact URI for MAF-originated calls |
| `SIP_MAF_COMMAND_TIMEOUT_SECS` | `30` | Command execution timeout |
| `SIP_MAF_COMMAND_MAX_ATTEMPTS` | `3` | Max command retry attempts |

### Rate limiting

| Variable | Default | Description |
|----------|---------|-------------|
| `SIP_API_RATE_LIMIT` | `100` | Admin API requests per second per IP |

---

## Common patterns

### IVR / Auto-attendant

```python
@app.route('/sip', methods=['POST'])
def handle():
    e = request.json
    if e['method'] == 'INVITE':
        return jsonify(action='reply', status=200, reason='OK',
            body='v=0\r\no=ivr 1 1 IN IP4 10.0.0.1\r\ns=-\r\n'
                 'c=IN IP4 10.0.0.1\r\nt=0 0\r\n'
                 'm=audio 10000 RTP/AVP 0\r\na=rtpmap:0 PCMU/8000\r\n')
    return jsonify(action='continue')
```

### Call recording trigger

```python
@app.route('/sip', methods=['POST'])
def handle():
    e = request.json
    if e['method'] == 'INVITE':
        return jsonify(action='continue',
            set_headers='X-Record: true\nX-Record-Format: wav')
    return jsonify(action='continue')
```

### Geographic routing

```python
import geoip2.database

reader = geoip2.database.Reader('/path/to/GeoLite2-City.mmdb')

@app.route('/sip', methods=['POST'])
def handle():
    e = request.json
    if e['method'] == 'INVITE':
        try:
            resp = reader.city(e['source_ip'])
            country = resp.country.iso_code
            if country == 'US':
                return jsonify(action='route', target='sip:us-gw.example.com:5060')
            elif country == 'GB':
                return jsonify(action='route', target='sip:uk-gw.example.com:5060')
        except:
            pass
    return jsonify(action='continue')
```

### CRM integration on inbound call

```python
@app.route('/sip', methods=['POST'])
def handle():
    e = request.json
    if e['method'] == 'INVITE':
        caller = e['from'].split(':')[1].split('@')[0]
        # Look up in CRM
        customer = crm_lookup(caller)
        if customer:
            return jsonify(action='continue',
                set_headers=f'X-Customer-ID: {customer.id}\n'
                            f'X-Customer-Name: {customer.name}\n'
                            f'X-Account-Tier: {customer.tier}')
        return jsonify(action='continue',
            set_headers='X-Customer-ID: unknown')
    return jsonify(action='continue')
```

### Webhook consumer (call analytics)

```python
from flask import Flask, request
import hashlib

app = Flask(__name__)
SECRET = 'your-webhook-secret'

@app.route('/webhooks/madis', methods=['POST'])
def webhook():
    body = request.get_data(as_text=True)
    sig = request.headers.get('X-Madis-Signature', '')
    expected = 'sha256=' + hashlib.sha256((SECRET + '|' + body).encode()).hexdigest()
    if sig != expected:
        return 'invalid signature', 403

    event = request.json
    event_type = event.get('event_type', '')

    if event_type == 'call.created':
        # Log to analytics DB
        analytics.log_call_start(event['call_id'], event['payload'])
    elif event_type == 'call.ended':
        analytics.log_call_end(event['call_id'], event['payload'])
    elif event_type == 'dialog.state_changed':
        # Update BLF dashboard
        dashboard.update_blf(event['payload']['aor'], event['payload']['state'])

    return 'ok', 200
```

---

## Glossary

| Term | Definition |
|------|-----------|
| **AOR** | Address of Record — the canonical SIP identity (e.g., `sip:alice@example.com`) |
| **App Gateway** | Synchronous webhook that intercepts every SIP message for real-time decisions |
| **BLF** | Busy Lamp Field — phone indicator showing if a line is in use |
| **B2BUA** | Back-to-Back User Agent — proxy terminates both call legs independently |
| **CDR** | Call Detail Record — billing/accounting data for completed calls |
| **CSeq** | Command Sequence — identifies and orders SIP transactions |
| **DTMF** | Dual-Tone Multi-Frequency — keypad tones (0-9, *, #) |
| **MAF** | Madis Application Framework — the programmable integration layer |
| **mTLS** | Mutual TLS — both client and server present certificates |
| **REFER** | SIP method for call transfer |
| **re-INVITE** | In-dialog INVITE for session modification (hold, codec change) |
| **Tenant** | Isolation boundary for multi-tenant deployments |
| **Webhook** | Async HTTP POST notification for events |
