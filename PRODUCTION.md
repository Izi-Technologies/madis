# Madis production notes

This is the short operational reference. The detailed guides are
[`docs/architecture.md`](docs/architecture.md),
[`docs/configuration.md`](docs/configuration.md),
[`docs/operations.md`](docs/operations.md), and
[`docs/testing.md`](docs/testing.md). Integration contracts are documented in
[`docs/integrations.md`](docs/integrations.md),
[`docs/modules.md`](docs/modules.md), and [`api/README.md`](api/README.md).

The supported build entrypoint is `main.mko`. It pulls the modular SIP, state,
transport, routing, media, security, and operations modules. `sipproxy_full.mko`
is a legacy reference archive and is not part of the supported build.

## Operational endpoints

Set `SIP_ADMIN_PORT` to enable the worker's local HTTP control plane. The
installed two-process layout uses `SIP_ADMIN_PORT=9090` for this internal
endpoint and `ADMIN_PORT=8080` for the standalone WebUI. `SIP_METRICS_HOST` and
`SIP_METRICS_PORT` tell the WebUI where to read worker metrics. If
`SIP_ADMIN_TOKEN` is set, the worker endpoints require
`Authorization: Bearer <token>` and the WebUI forwards that token.

- `/healthz` — liveness and active call count
- `/readyz` — readiness state
- `/metrics` — Prometheus exposition
- `/state` — bounded in-memory map sizes
- `POST /reload` — invalidate configuration caches

Set `SIP_CONFIG_FILE` to a watched file path to trigger the same cache reload on
mtime changes. The file is a reload signal; routing and credentials remain in
the database.

## Standalone WebUI

The control-plane UI is built from `admin/main.mko` with Mako 0.4.18 and runs
as `madis-admin.service`, independently of the SIP worker.
Use loopback binding and put nginx or another TLS reverse proxy in front of
it:

```sh
ADMIN_BIND=127.0.0.1
ADMIN_PORT=8080
SIP_ADMIN_PORT=9090
SIP_METRICS_HOST=127.0.0.1
SIP_METRICS_PORT=9090
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental admin/main.mko -o admin-bin
```

The dashboard sends a live snapshot over WebSocket, falls back to
`/admin/api/live` polling, and shares the database/metrics snapshot for three
seconds across clients. The initial HTML response does not wait on SIP or
metrics probes. Keep `admin-bin` behind the reverse proxy and do not expose
the admin listener directly to the public internet.

The same admin process serves the bearer-token machine API at
`/admin/api/v1/`. `SIP_CARRIER_API_TOKEN` is limited to capabilities, billing
events, acknowledgements, and CDR reads. `SIP_CONTROL_API_READ_TOKEN` provides
read-only control status, validation, and policy/resource reads, while
`SIP_CONTROL_API_TOKEN` also permits routing, dialplan, and allowlisted SIP
resource writes. The resource API is not a generic SQL or application-database
interface; security bans are currently list/create-upsert by `source_ip`, while
the other mutable resource helpers use numeric IDs and revisions.

The installer also provides the `madis` CLI:

```sh
madis version
madis status
madis health
madis webui
madis logs admin
```

## Registration and transport behavior

Registrations support up to eight live in-memory contacts per AoR, contact-level
`expires` values, `Expires: 0` removal, database hydration at startup, and
database-backed expiry cleanup. Registered TCP, TLS, WS, and WSS contacts are
sent over their advertised transport. WSS outbound requires a trusted CA
bundle via `SIP_UPSTREAM_CA`; `SIP_UPSTREAM_TLS_INSECURE=1` is available only
for isolated interoperability labs. Outbound WSS associations are persistent
and expire after `SIP_WSS_IDLE_MS` (default 600000 ms) when idle.

Each worker retains at most 1,024 persistent outbound TCP/TLS/WSS associations;
the oldest association is closed when the cap is reached. Inbound TCP response
routing is capped at 8,192 transaction mappings and 1,024 mappings per open
connection.

IPv6 UDP is enabled by default with `SIP_IPV6=1` and runs on a separate
v6-only listener; set `SIP_IPV6=0` only on hosts where IPv6 is unavailable.
TCP and TLS listeners use the runtime's dual-stack wildcard behavior.

Digest challenges use short-lived nonces and reject nonce reuse. SIP input is
bounded to 64 KiB, limited to 128 headers, and checked for malformed header
lines and control-character injection before database work.

The in-memory state is intentionally bounded: an AoR may occupy at most eight
contacts and the process tracks at most 16,384 AoRs; a fork group may contain
at most 32 branches and the process tracks at most 16,384 fork groups. Invalid
registration sizes, ports, and transport values are rejected before state or
database writes. Transaction maintenance sweeps 2,048 slots per timer tick so
the transaction tables remain bounded without allowing retransmission work to
starve behind a full-table scan.

The admin listener rejects requests larger than 128 KiB, requires a complete
and valid `Content-Length` for POST bodies, and applies an Origin/Host check
when browsers send an `Origin` header. Login-failure, session, and admin-side
cache state are bounded; use a reverse proxy for TLS, authentication policy,
rate limiting, and public exposure.

## Mako runtime prerequisites

The supported compiler/runtime version is **Mako 0.4.18**. Use the same
0.4.18 compiler and runtime directory for C emission, native linking, the
WebUI, and the benchmark harness. Local filesystem paths are intentionally not
part of the deployment contract.

Build this proxy with `MAKO_RUNTIME=/path/to/mako/runtime` so the generated C
links against the Mako 0.4.18 runtime. Do not mix a different compiler and
runtime version. STIR/SHAKEN signing mode and key handling must be reviewed
against the deployed configuration; the repository does not provide carrier
certificate provisioning or rotation.

## Verification

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/rfc_gate.sh
```

The regular gate covers compiler checks, the Mako test suites, transport and
WSS framing, TLS/IPv6 behavior, fault injection, ABNF corpus parsing, auth
matrix checks, and fuzz cases. `RFC_FULL=1 sh bench/rfc_gate.sh` additionally
runs sanitizer and soak jobs when the host has the required tools. These gates
are adversarial regression checks, not a certification of complete compliance
with every SIP/WebRTC extension or every independent implementation.
