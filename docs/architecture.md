# Architecture

Madis normally runs as two processes that share PostgreSQL but do not share in-memory state.

```text
SIP endpoints and trunks
        │ UDP / TCP / TLS / WS / WSS
        ▼
  madis.service ───────────── PostgreSQL
        │                         │
        │ local health,           │ registrations, routing,
        │ metrics, and state      │ policy, CDR, outbox
        ▼                         │
  madis-admin.service ◄───────────┘
        │
        └── WebUI, live dashboard, and /admin/api/v1/
```

The installer uses `SIP_ADMIN_PORT=9090` for the worker’s local HTTP surface and `ADMIN_PORT=8080` for the standalone WebUI. The WebUI reaches the worker through `SIP_METRICS_HOST`/`SIP_METRICS_PORT`. A Docker deployment may expose the worker HTTP port directly, but the browser WebUI still requires a separately built admin process.

## SIP worker

The worker owns:

- UDP, TCP, TLS, WS, and WSS listeners and outbound transport selection.
- SIP parsing, authentication, registration contacts, transactions, retransmissions, dialogs, forks, and response routing.
- Database-backed routes, dispatch groups, dialplans, gateways, access control, security bans, header rules, ANI ranges, and optional B2BUA policy.
- Bounded CDR/outbox writes, optional preauthorization, metrics, and worker-local health/state endpoints.

The main modular entry point is [`../main.mko`](../main.mko). It pulls parser, header, authentication, registration, routing, transport, billing, charging, application, module, event package, TLS reuse, outbound, and operations components. The codebase is pure Mako with no C bridge code. [`../sipproxy_full.mko`](../sipproxy_full.mko) is a legacy monolithic reference and is not the deployment target.

## Request path

For an inbound SIP message, the worker broadly:

1. Bounds and parses framing, headers, URI targets, `Content-Length`, CSeq, Via, and Max-Forwards.
2. Applies database-backed security, access, authentication, rate, scanner, and ban policy.
3. Creates or finds transaction state and handles retransmissions and duplicate messages.
4. Processes REGISTER, dialog requests, responses, routing, dispatch, dialplan, and optional charging policy.
5. Resolves the next hop using explicit transport policy and RFC 3263-style DNS selection where configured.
6. Sends the message, updates bounded state and metrics, and emits lifecycle/billing records where enabled.
7. For SUBSCRIBE requests with `SIP_EVENT_PACKAGES=1`, the event package notifier manages subscription state and generates NOTIFY for presence and message-summary packages.
8. With `SIP_TLS_REUSE=1`, inbound TLS connections with Via `;alias` are cached for outbound reuse.
9. With `SIP_OUTBOUND=1`, outbound flow tokens route requests through established flows using `+sip.instance` and `reg-id`.

The exact behavior is implemented in [`../parser.mko`](../parser.mko), [`../rfc.mko`](../rfc.mko), [`../routing.mko`](../routing.mko), [`../registration.mko`](../registration.mko), [`../transport.mko`](../transport.mko), [`../stream.mko`](../stream.mko), and [`../main.mko`](../main.mko). The known protocol gaps are in [`../RFC_COMPLIANCE.md`](../RFC_COMPLIANCE.md).

## WebUI and machine API

The admin process owns browser sessions, role-gated pages, HTMX updates, WebSocket live updates with polling fallback, CDR export, dashboards, and configuration views. It also owns the versioned machine API at `/admin/api/v1/`.

The API has separate bearer scopes:

- `SIP_CARRIER_API_TOKEN` for capabilities, billing events, acknowledgements, and CDR reads.
- `SIP_CONTROL_API_READ_TOKEN` for read-only status, validation, and control/resource reads.
- `SIP_CONTROL_API_TOKEN` for control writes as well as reads.

The machine API is intentionally allowlisted and bounded. It accepts routing and SIP resource documents, not SQL, Mako, shell commands, or arbitrary code. Resource responses include revisions for optimistic concurrency. See [`../api/README.md`](../api/README.md).

## External application and module boundaries

The MADIS Application Fabric (MAF) is the language-neutral boundary for
external application services. Its versioned HTTP routes and replayable event
WebSocket persist tenant-scoped call resources, bridge relationships, media
operations, header policy, replayable events, and asynchronous commands in
PostgreSQL.
The standalone admin process accepts and authenticates those commands; the SIP
worker remains the owner of signaling state and processes outbound originate,
early-dialog cancellation, confirmed-dialog hangup, bridge state, and
media-module dispatch through the MAF worker queue. With
`SIP_MAF_INBOUND_MODE=control`, it can also publish an
authenticated initial INVITE as a tenant-scoped ringing call and execute
`calls.answer` by validating `answer_sdp` and sending the tagged `200 OK`.
Bridge operations create durable relationships after answer. Media operations
dispatch through signed external `media` or `recording` modules and fail
explicitly without a safe backend. Its contract is documented in
[`../api/maf.md`](../api/maf.md).

The optional application gateway sends signed, bounded SIP event documents to an external HTTP(S) service and accepts only validated commands such as continue, route, reply, redirect, reject, B2BUA policy, and constrained header/body changes. The module dispatcher uses a separate signed contract for TTS, STT, LLM, media, recording, fraud, and billing operations.

These are network contracts, not in-process plugin ABIs. The external service owns its framework, credentials, queues, model/media workers, durable state, and business authorization. The SIP worker retains transaction and dialog ownership and applies command allowlists, size bounds, timeouts, and failure modes. See [`modules.md`](modules.md).

## Persistence and ownership

PostgreSQL stores the SIP state needed by the worker and admin process: registrations, routing policy, gateways, dispatch data, dialplans, security state, CDRs, and the billing event outbox. It is not an application-owned billing database.

The application remains responsible for:

- Tenant, product, tariff, rating, ledger, invoice, tax, and settlement data.
- Durable handling and deduplication of billing events.
- HSS/UDM, complete IMS service logic, and carrier-specific Diameter policy.
- Media relay, RTP, ICE, DTLS-SRTP, codecs, and recording.
- Native SS7/SIGTRAN gateway operation.

## Concurrency and failure behavior

Listener workers and scheduler settings are bounded through the `SIP_*_WORKERS` and `SIP_SCHED_WORKERS` configuration. Attacker-controlled caches, transaction state, dialog state, routing state, and integration payloads have implementation limits.

Billing delivery is at least once: an application must commit its own transaction before acknowledging an event. Optional live applications and modules have bounded synchronous timeouts. Application failures can be configured open or closed; module failures are closed by default. Online preauthorization is fail-closed unless the operator explicitly enables `SIP_CHARGING_FAIL_OPEN=1`.

These controls reduce common failure modes but do not replace operating-system isolation, database permissions, secret management, network policy, backup/restore testing, or external security review.
TCP, TLS, and WSS workers multiplex non-blocking connections in one event loop
instead of holding a worker inside one connection. `SIP_TCP_MAX_CONNECTIONS`
bounds each stream worker. Worker counts are configurable per transport:
`SIP_UDP_WORKERS`, `SIP_TCP_WORKERS`, `SIP_TLS_WORKERS`, `SIP_WSS_WORKERS`.
Multiple workers use SO_REUSEPORT for kernel-level load distribution. TLS
workers share a single OpenSSL `SSL_CTX` and drive handshakes non-blocking
inside the same event loop as data I/O — no connection blocks the accept path.

HAProxy PROXY protocol v1 is supported on TCP, TLS, and WSS listeners when
`SIP_PROXY_PROTOCOL=1`. The PROXY header is parsed before TLS handshake (TLS)
or before WebSocket upgrade (WSS), preserving the original client IP/port.
Only peers listed in `SIP_PROXY_TRUSTED_IPS` (default: loopback) may send
PROXY headers; untrusted peers are rejected to prevent source-IP spoofing.

Per-IP connection limits (`SIP_PER_IP_CONN_LIMIT`, default 100) bound
concurrent stream connections from a single source address. Connection counts
are tracked as a Prometheus-style gauge (`madis_sip_connections_total`) labeled
by transport.

SIP call/dialog records are bounded by `SIP_CALL_STATE_CAPACITY`;
new calls are rejected at that limit so active state is not evicted silently.
HEP wire packets use a per-process bounded `chan[string]` controlled by
`SIP_HEP_QUEUE_CAPACITY`; a detached sender performs collector I/O, and queue
overflow drops capture only.
