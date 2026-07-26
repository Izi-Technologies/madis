# Architecture

## Process layout

Madis normally runs as two processes:

```text
SIP endpoints / trunks
        │ UDP, TCP, TLS, WSS
        ▼
  madis.service  ───── PostgreSQL
        │                  │
        │ HTTP health/     │ registrations, routing,
        │ metrics           │ users, CDR, billing outbox
        ▼                  │
  madis-admin.service ◄────┘
        │
        └─ browser WebUI and bearer-token carrier API
```

The SIP worker owns SIP listeners, transaction state, registration state,
routing, forwarding, timers, and the local health/metrics endpoint. The admin
worker owns the browser session, WebUI, live dashboard, and machine API. The
installer keeps the listeners separate by using the worker's internal
`SIP_ADMIN_PORT=9090` for metrics and the standalone WebUI's `ADMIN_PORT=8080`.
The WebUI targets the worker through `SIP_METRICS_HOST/PORT` and forwards the
worker token when one is configured.

The two processes may share PostgreSQL, but they do not share in-memory maps.
The database is the durable source for registrations and configuration that
the deployment has chosen to persist. A local multi-worker configuration is
not the same thing as a multi-node cluster.

## SIP request path

For each ingress message, the worker roughly does the following:

1. Bounds and parses the message, including framing, headers, URI targets,
   `Content-Length`, CSeq, Via, and Max-Forwards.
2. Applies security policy, authentication, rate limits, scanner/fraud checks,
   and database-backed access policy.
3. Creates or checks transaction state and handles retransmissions.
4. Processes REGISTER, responses, dialog requests, routing, dispatch groups,
   dialplan actions, and optional online charging.
5. Selects UDP, TCP, TLS, WS, or WSS for the next hop and forwards the message.
6. Records bounded state, CDR events, metrics, and the response path.

The exact behavior is implemented in `parser.mko`, `rfc.mko`, `routing.mko`,
`registration.mko`, `transport.mko`, `stream.mko`, and `main.mko`. The RFC
status and known omissions are recorded in [`../RFC_COMPLIANCE.md`](../RFC_COMPLIANCE.md).

## Concurrency model

UDP and stream listeners use Mako event and worker primitives. `crew`/`kick`
can use a bounded Mako scheduler pool through `SIP_SCHED_WORKERS`; `0` keeps
the default one-pthread-per-kick behavior. The setting changes scheduling, not
the protocol or the capacity of a host.

State that can grow from attacker-controlled input is kept behind explicit
limits: registration contacts, dialogs, forks, authentication state, DNS and
routing caches, transaction rings, and outbound associations. These limits
protect memory; they are not a promise that a particular machine can sustain a
given CPS or concurrent-call number.

## WebUI and API path

The WebUI accepts browser requests on `ADMIN_BIND`/`ADMIN_PORT`. It uses a
database-backed admin user, a bounded session cache, secure cookies by default,
Origin/Host checks for browser POSTs, and an allowlist for dynamic SQL table
and column names. The live dashboard uses WebSocket updates with HTTP polling
fallback and a short shared snapshot cache.

Machine integrations use `/admin/api/v1/` and a separate bearer token. Billing
events are at-least-once: consumers must commit their own transaction,
deduplicate by `event_id`, and then acknowledge the event. The API stores
caller-defined JSON data; it does not replace a carrier's rating, invoice, or
charging system.

The control API uses a second bearer token and exposes only bounded routing
policy operations. A client can create or disable a routing rule, including an
explicit `b2bua:` action, but cannot execute Mako, SQL, shell commands, or
arbitrary application code in the SIP worker. B2BUA state remains in the
worker's bounded in-memory map; PostgreSQL stores the policy that selects it.

The optional SIP application gateway extends this boundary to live decisions.
It sends signed, bounded SIP events to an out-of-process service and accepts
only validated commands for routing, replies, B2BUA, validated headers/body, or
module invocation. The module bus uses the same boundary for TTS, STT, LLM,
recording, media, fraud, and billing workers. External services own their
frameworks and durable state; Madis retains transaction, dialog, and transport
ownership. See [`modules.md`](modules.md) for the wire contract.

## Integration boundaries

- **Media:** RTPEngine integration is a control-plane hook. Madis does not
  terminate RTP, ICE, or DTLS-SRTP itself.
- **Diameter:** the repository contains bounded RFC 6733 peer framing, RFC 8506
  credit-control messages, and selected 3GPP Cx/Dx and Sh builders. HSS/UDM,
  policy, peer routing, failover, and autonomous quota enforcement remain
  external or incomplete.
- **IMS:** the session schema and Cx/Sh contracts are integration boundaries;
  they are not P-/I-/S-CSCF, HSS, TAS, PCRF/PCF, or a complete IMS core.
- **SS7/SIGTRAN:** the M3UA envelope is a contract for an external gateway.
  Madis does not terminate M3UA/SCCP/ISUP/TCAP on its own.
- **Billing:** the outbox and optional preauthorization adapters provide
  delivery and protocol plumbing, not rating or financial settlement.

## Memory and SQL boundaries

Mako 0.4.16 emits native C and the build links `madis_memory.c` for bounded
transaction-map helpers. Application code does not use raw pointers. SQL
values are passed as parameters; identifiers accepted by generic admin actions
are allowlisted before query construction. Inputs, request bodies, JSON, and
stored event payloads have size limits. These controls reduce common failure
modes but do not remove the need for OS isolation, database permissions,
secrets management, and external security review.
