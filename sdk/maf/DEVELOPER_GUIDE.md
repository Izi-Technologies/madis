# Building Applications with the MADIS Application Fabric (MAF)

## 1. Overview

The **MADIS Application Fabric (MAF)** provides a language-neutral, programmatic control plane for MADIS SIP Proxy. External services written in **Python**, **JavaScript / TypeScript**, **Go**, **Erlang**, or any language with HTTP and WebSocket support can observe communication events in real time and execute fine-grained call control commands without writing Mako code, SQL queries, or raw SIP bytes.

With MAF, your application completely controls:
- **Inbound Call Handling**: Intercept inbound calls, inspect caller identities, and programmatically answer, reject, or route.
- **Outbound Origination**: Initiate outbound calls with customized caller IDs, P-Asserted-Identity, and custom SIP headers.
- **Interactive IVR & Bots**: Answer with custom audio SDP, receive real-time DTMF keypad digits, play announcements, and bridge calls.
- **Dynamic Routing & Softswitch**: Route calls to dynamic gateways with transport selection (UDP, TCP, TLS, WSS) and failover.
- **Call Transfers & Bridging**: Perform blind (REFER) and attended (REFER with Replaces) transfers, or bridge 2–8 channels.
- **Header & Media Policies**: Manipulate SIP headers per call and control RTPEngine transcoders or external media engines.
- **STIR/SHAKEN Identity**: Integrate external STIR/SHAKEN cryptographic signing and verification services.

---

## 2. Architecture & Decoupling

MADIS separates high-speed network signaling from business application logic:

```text
 SIP Telephony World                  MADIS SIP Core                  Your Application (MAF)
 ───────────────────                  ──────────────                  ──────────────────────
 Inbound Call (INVITE) ─────────────► [SIP Worker]
                                             │
                                     Durable State & Events
                                             ▼
                                     [PostgreSQL DB] ◄──────────────► [Your Application]
                                             ▲                         (Python, Node.js, Go)
                                             │                         - Listens to events
                                     Command Queue                     - Decides call policy
                                             │                         - Issues commands
 Downstream Gateway    ◄───────────── [SIP Worker] ◄────────────────── (Answer, Route, Hangup)
```

1. **Signaling State Ownership**: The SIP worker maintains SIP transactions, retransmissions, timer sweeps, NAT pinholes, and TLS sockets.
2. **Durable Command Acceptance**: Applications submit commands via the HTTP API (`POST /api/v1/maf/calls/{id}/...`). The API responds with `202 Accepted` and a unique idempotency receipt, and the SIP worker executes the command asynchronously.
3. **Replayable Real-Time Events**: Signaling state transitions (`call.ringing`, `call.answered`, `call.dtmf`, `call.ended`) are persisted and streamed via WebSocket, Webhooks, or HTTP cursor polling.

---

## 3. Configuration & Getting Started

### Enabling MAF on the SIP Worker

In your environment or configuration file (`/etc/madis/madis.env`):

```bash
# Enable MAF inbound call interception
# Modes: "control" (app answers/rejects/routes), "route" (app decides destination)
SIP_MAF_INBOUND_MODE=control

# Database connection shared between worker and admin API
DATABASE_URL="postgres://madis:secret@127.0.0.1:5432/madis?sslmode=disable"

# Admin API listener (where MAF HTTP and WebSocket routes are served)
ADMIN_PORT=8080
SIP_MAF_API_TOKEN="your-secure-maf-token-at-least-16-chars"
```

> [!TIP]
> `SIP_MAF_INBOUND_MODE` can also be updated dynamically at runtime without restarting the proxy using the config API:
> `curl -X POST http://127.0.0.1:8080/admin/api/v1/config -H "Authorization: Bearer $SIP_ADMIN_TOKEN" -d '{"sip_maf_inbound_mode": "control"}'`

---

## 4. MAF Operations & Capabilities

| Operation | Route | Description |
| --- | --- | --- |
| **`calls.create`** | `POST /api/v1/maf/calls` | Originate a new outbound call. |
| **`calls.answer`** | `POST /api/v1/maf/calls/{id}/answer` | Answer an inbound call with custom `answer_sdp`. |
| **`calls.reject`** | `POST /api/v1/maf/calls/{id}/reject` | Reject an incoming call with a SIP status code (486, 603, 404, 503). |
| **`calls.hangup`** | `POST /api/v1/maf/calls/{id}/hangup` | Terminate an active call (CANCEL if ringing, BYE if answered). |
| **`calls.route`** | `POST /api/v1/maf/calls/{id}/route` | Forward an inbound call to a target URI, with caller ID overrides. |
| **`calls.transfer`** | `POST /api/v1/maf/calls/{id}/transfer` | Blind (REFER) or attended (REFER+Replaces) transfer. |
| **`calls.bridge`** | `POST /api/v1/maf/calls/{id}/bridges` | Bridge 2 to 8 channels together. |
| **`calls.hold`** | `POST /api/v1/maf/calls/{id}/hold` | Place an active call on hold (`sendonly` SDP). |
| **`calls.unhold`** | `POST /api/v1/maf/calls/{id}/unhold` | Resume a held call (`sendrecv` SDP). |
| **`calls.dtmf`** | `POST /api/v1/maf/calls/{id}/dtmf` | Transmit a DTMF digit via SIP INFO (`application/dtmf-relay`). |
| **`calls.headers`** | `POST /api/v1/maf/calls/{id}/headers` | Apply custom SIP header policy (add, set, remove, copy). |
| **`calls.media`** | `POST /api/v1/maf/calls/{id}/media` | Dispatch play/record/pause/stop to external media backend. |
| **`calls.rtp`** | `POST /api/v1/maf/calls/{id}/rtp` | Control RTPEngine flags (offer, answer, delete, query). |
| **`calls.identity`** | `POST /api/v1/maf/calls/{id}/identity` | STIR/SHAKEN external signing and verification. |

---

## 5. Event Handling & Streaming

MAF produces durable, sequential events identified by an increasing cursor:

### Event Types
- `call.created`: New inbound or outbound call initiated.
- `call.ringing`: Ringing progress (180/183 received or local ringing started).
- `call.answered`: Call established (200 OK exchanged).
- `call.routed`: Inbound call forwarded to destination target.
- `call.dtmf`: Keypad DTMF digit received or transmitted (contains `digit`, `direction`).
- `call.ended`: Call terminated cleanly via BYE.
- `call.canceled`: Call terminated before answer via CANCEL.
- `call.rejected`: Call rejected with final error code (4xx/5xx/6xx).

### Stream Options
1. **WebSocket Streaming**: Connect to `ws://127.0.0.1:8080/admin/api/v1/maf/events/ws?cursor=0` with `Authorization: Bearer <TOKEN>` header.
2. **Webhooks**: Register webhooks in `maf_webhooks` table; MADIS posts events as HTTPS JSON with `X-Madis-Signature: sha256=...`.
3. **Cursor Polling**: Use `GET /api/v1/maf/events?cursor=0&limit=50`.

---

## 6. Code Examples

### A. Python Example (Interactive Voice Agent / IVR)

```python
from madis_maf import MadisMaf

client = MadisMaf("http://127.0.0.1:8080/admin", "your-maf-api-token")

cursor = 0
while True:
    page = client.events(cursor=cursor)
    for event in page.get("events", []):
        etype = event["type"]
        call_id = event["call_id"]

        if etype == "call.created":
            # Answer incoming call with AI voice bot SDP
            answer_sdp = (
                "v=0\r\no=bot 1 1 IN IP4 127.0.0.1\r\ns=AI\r\n"
                "c=IN IP4 127.0.0.1\r\nt=0 0\r\nm=audio 16384 RTP/AVP 0 101\r\n"
                "a=rtpmap:0 PCMU/8000\r\na=rtpmap:101 telephone-event/8000\r\na=sendrecv\r\n"
            )
            client.answer_call(call_id, answer_sdp)

        elif etype == "call.dtmf":
            digit = event["payload"].get("digit")
            if digit == "1":
                # Transfer caller to agent
                client.transfer_call(call_id, "sip:agent@callcenter.example.net")
            elif digit == "9":
                client.hangup_call(call_id, reason="Caller Finished")

    cursor = page.get("next_cursor", cursor)
```

### B. JavaScript / TypeScript Example (Smart Softswitch Routing)

```javascript
import { MadisMaf } from './sdk/maf/javascript/madis-maf.mjs';

const maf = new MadisMaf('http://127.0.0.1:8080/admin', 'your-maf-api-token');

let cursor = 0;
while (true) {
  const page = await maf.events({ cursor });
  for (const event of page.events || []) {
    if (event.type === 'call.created') {
      const { from_uri, to_uri } = event.payload;

      // Smart carrier routing with custom caller ID
      await maf.routeCall(event.call_id, 'sip:gw.carrier.com:5060', {
        transport: 'udp',
        callerId: '+15551234567',
        callerName: 'Enterprise Voice Gateway',
        pAssertedIdentity: 'sip:+15551234567@example.net',
      });
    }
  }
  cursor = page.next_cursor ?? cursor;
}
```

### C. Go Example (Call Origination & Bridging)

```go
package main

import (
    "context"
    "log"
    "../sdk/maf/go"
)

func main() {
    client, err := madismaf.New("http://127.0.0.1:8080/admin", "your-maf-api-token")
    if err != nil { log.Fatal(err) }

    ctx := context.Background()

    // 1. Originate outbound call to Customer
    receipt, err := client.CreateCall(ctx, "sip:sales@company.com", "sip:customer@carrier.net", "")
    if err != nil { log.Fatal(err) }

    log.Printf("Call initiated: %v", receipt["command_id"])
}
```

---

## 7. Pre-Built Reference Implementations

Complete, runnable applications are available in the repository:
- **[ivr_auto_attendant.py](examples/ivr_auto_attendant.py)**: Full IVR auto-attendant with DTMF navigation, transfer queues, screening, and hangup.
- **[call_router.mjs](examples/call_router.mjs)**: Smart softswitch router with DID routing tables, caller ID manipulation, and failover.
- **[call_controller.go](examples/call_controller.go)**: High-performance Go call controller.
- **[click_to_call.py](examples/click_to_call.py)**: Automated dual-leg click-to-call script.
- **[event_monitor.py](examples/event_monitor.py)**: Real-time event streaming CLI.
