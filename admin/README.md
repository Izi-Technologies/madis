# Mako SIP Admin Panel

This is the Mako SIP control-plane WebUI source imported from the live
`mako-admin.service` deployment. It is intentionally separate from the SIP
worker binary and does not depend on Leba.

## First run

Build from the repository root, then start the service with the same database
and token environment as the SIP worker:

```bash
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental admin/main.mko -o admin-bin
ADMIN_BIND=127.0.0.1 ADMIN_PORT=8080 ./admin-bin
```

Open `/admin/login` in a browser. For an installed host, use `madis webui`
to print the configured URL and `madis health` to check that the service is
responding. Do not bind the admin process publicly without a TLS reverse
proxy and an explicit network policy.

| File | Role |
|------|------|
| `main.mko` | HTTP server, auth, sessions, rate-limit |
| `http.mko` | Request parsing, cookies, form URL-decode |
| `ui.mko` | HTML chrome / login page |
| `pages.mko` | Dashboard and table views |
| `handlers.mko` | HTMX page routes + API mutations |
| `log.mko` | `slog` helper |

## Build

From repo root:

```bash
# Mako 0.4.16 is required.
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental admin/main.mko -o admin-bin
```

The admin service listens on `ADMIN_BIND`/`ADMIN_PORT` (loopback and `8080`
by default). Put TLS and WebSocket proxying in nginx or another reverse proxy.
The installer keeps the admin listener and the SIP worker's internal
health/metrics endpoint separate: `ADMIN_PORT=8080`, `SIP_ADMIN_PORT=9090`,
and `SIP_METRICS_HOST/PORT=127.0.0.1:9090` by default. Keep those ports
different. Set `SIP_ADMIN_PORT=0` only when the worker's local HTTP endpoint is
intentionally disabled and the WebUI does not need live SIP metrics.

## Environment

| Variable | Default | Meaning |
|----------|---------|---------|
| `SIP_DB_URL` | (required) | Postgres URL |
| `SIP_ADMIN_PASSWORD` | — | Bootstrap password when no admin users exist |
| `ADMIN_SECURE_COOKIE` | `1` | Set `0` for plain-HTTP local dev |
| `ADMIN_SESSION_TTL_SECS` | `86400` | Session lifetime |
| `ADMIN_LOGIN_MAX_FAILS` | `5` | Failures before lockout |
| `ADMIN_LOGIN_LOCK_SECS` | `900` | Lockout window |
| `ADMIN_BIND` | `127.0.0.1` | Listen address (`0.0.0.0` only if intentionally public) |
| `ADMIN_PORT` | `8080` | Listen port |
| `SIP_METRICS_HOST` | `127.0.0.1` | SIP worker host used by the live dashboard |
| `SIP_METRICS_PORT` | `9090` | SIP worker port used by the live dashboard |

The live deployment uses `/admin/login`, authenticated session cookies, HTMX
page updates, and a WebSocket live dashboard with HTTP polling fallback. The
dashboard refreshes its expensive database/metrics snapshot at most every
three seconds and shares it across connected clients; the browser still gets
one-second WebSocket updates. The first paint does not wait on SIP or metrics
probes, and the UI defers its optional browser asset so a slow third-party CDN
cannot block the control plane.

The cache is intentionally short-lived so dashboard counts remain responsive
without multiplying PostgreSQL work across operators. In the installed layout,
`madis-admin.service` reads live SIP metrics from the worker's internal
`SIP_METRICS_HOST/PORT`; the worker's `SIP_ADMIN_PORT` must match that port.
Public HTTPS/WSS termination belongs in nginx or another reverse proxy; the
admin process itself should remain loopback-bound.

## What is in the UI

The navigation covers dashboard, search, active dialogs, metrics, SIP traces,
CDR export, users, registrations, access control, gateways, dispatch groups,
routing rules, route simulation, ANI groups, DIDs, dialplan translation,
header rules, security events/bans, cluster state, logs, audit history,
configuration, admin users, and the current account. Actions are role-gated;
use a viewer for read-only access and reserve admin/super-admin accounts for
configuration changes.

The browser live view uses `/admin/ws/live` when the reverse proxy supports
WebSocket upgrade and falls back to `/admin/api/live`. Prometheus-compatible
proxy routes are `/admin/api/prom` and `/admin/api/stats`; configure
`ADMIN_METRICS_TOKEN` for token-only machine access. CDR export is
`/admin/api/cdr.csv` and requires a browser session.

The carrier machine API is separate from browser sessions and lives under
`/admin/api/v1/`. It requires `SIP_CARRIER_API_TOKEN`; a WebUI cookie is not a
substitute. See [`../api/README.md`](../api/README.md).

## Safety and performance notes

POST forms are URL-decoded into one per-request `CMap`, avoiding repeated body
scans on large mutations. Search, gateway, dispatch, and ANI lookups bind
values through Mako's SQL API. Toggle/delete uses an allowlist for every SQL
identifier because table and column names cannot be bound as parameters; any
unknown pair is rejected before SQL execution. New routing rules use the
connection-local insert id for optional updates, avoiding the concurrent
`MAX(id)` race.

The HTTP worker rejects requests larger than 128 KiB, rejects bodies without a
valid `Content-Length`, duplicate `Content-Length` headers, and unsupported
`Transfer-Encoding`, and rejects truncated or overlong bodies. Process-local sessions are capped at 65,536
entries; login-failure state is capped at 16,384 entries; session TTL is capped
at seven days. Metrics/configuration values and database-backed page content
are escaped before HTML, attribute, or JavaScript rendering. The metrics
helper also rejects invalid configured ports before opening a socket. Browser
POSTs require a matching `Origin`/`Host` pair, while Origin-less automation is
still supported.

The UI is the standalone admin service and does not require Leba. Keep it
bound to loopback and terminate public HTTPS/WSS in nginx or another reverse
proxy. The service is built and checked with Mako 0.4.16.

## Machine API

The service also exposes the bearer-token-only carrier API under
`/admin/api/v1/`: capability discovery, a bounded billing outbox page, custom
JSON event publishing, and acknowledgement. Configure
`SIP_CARRIER_API_TOKEN`; browser sessions are deliberately not accepted for
machine routes. See [`api/README.md`](../api/README.md) for schemas, retry
semantics, charging, IMS, and SS7 boundaries.
