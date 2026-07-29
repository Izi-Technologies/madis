# Madis WebUI and admin service

The `admin/` directory contains the standalone Mako WebUI and the machine API gateway. It runs separately from the SIP worker and shares the configured PostgreSQL database.

## Build and run

Mako 0.5.0 is required:

```sh
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental \
  admin/main.mko -o admin-bin

SIP_DB_URL=postgres://madis:password@127.0.0.1:5432/madis \
ADMIN_BIND=127.0.0.1 ADMIN_PORT=8080 \
  ./admin-bin
```

Open `/admin/login` through the configured reverse proxy. The installer normally runs this process as `madis-admin.service` with `ADMIN_BIND=127.0.0.1` and `ADMIN_PORT=8080`. Its live dashboard reaches the worker at `SIP_METRICS_HOST`/`SIP_METRICS_PORT`; the installer’s worker port is normally `SIP_ADMIN_PORT=9090`.

Keep the admin listener private and terminate public HTTPS/WSS in nginx, Caddy, HAProxy, or an equivalent edge. Preserve `Host`, `Origin`, `Upgrade`, and `Connection` headers.

## Relevant environment

| Variable | Purpose |
| --- | --- |
| `SIP_DB_URL` | PostgreSQL connection string. |
| `ADMIN_BIND`, `ADMIN_PORT` | WebUI bind address and port. |
| `SIP_METRICS_HOST`, `SIP_METRICS_PORT` | Worker HTTP endpoint used for live metrics/state. |
| `SIP_ADMIN_TOKEN` | Required 16–512 character bearer token forwarded to protected worker probes. |
| `SIP_ADMIN_PASSWORD` | Bootstrap password when no admin user exists. |
| `ADMIN_SECURE_COOKIE` | Secure session cookie behavior; keep enabled for HTTPS. |
| `ADMIN_SESSION_TTL_SECS` | Browser session lifetime. |
| `ADMIN_LOGIN_MAX_FAILS`, `ADMIN_LOGIN_LOCK_SECS` | Login failure controls. |
| `ADMIN_METRICS_TOKEN` | Optional 16–512 character bearer token for machine-only metrics/statistics proxy routes; query-string tokens are rejected. |

## WebUI coverage

The role-gated UI includes dashboard and live metrics, dialogs, SIP traces, CDR export, users, registrations, access control, gateways, dispatch groups, routing rules, route simulation, ANI groups, DIDs, dialplan translation, header rules, security events/bans, cluster state, logs, audit history, configuration, admin users, and account/session views.

The live dashboard uses `/admin/ws/live` when WebSocket upgrade is available and falls back to `/admin/api/live`. Prometheus/statistics proxy routes are `/admin/api/prom` and `/admin/api/stats`; configure `ADMIN_METRICS_TOKEN` for token-only machine access. CDR export is `/admin/api/cdr.csv` and uses a browser session.

## Machine API

The machine API is under `/admin/api/v1/` and does not accept browser sessions. It requires bearer credentials configured in the SIP worker environment:

- `SIP_CARRIER_API_TOKEN`: capabilities, billing event outbox, acknowledgements, and CDR reads.
- `SIP_CONTROL_API_READ_TOKEN`: read-only control status, validation, policy/resource reads, and resource lists.
- `SIP_CONTROL_API_TOKEN`: those reads plus routing, dialplan, and mutable resource writes.

The resource names and field bounds are fixed by the allowlist. The API does not accept arbitrary SQL, Mako, shell commands, or application code. See [`../api/README.md`](../api/README.md), [`../api/openapi.yaml`](../api/openapi.yaml), and [`../docs/integrations.md`](../docs/integrations.md).

## Safety and performance boundaries

The admin listener rejects oversized or malformed HTTP bodies, duplicate `Content-Length`, unsupported transfer framing, and invalid browser origins. Sessions and login-failure state are bounded, database/configuration values are escaped before HTML/JavaScript output, and generic mutations use fixed table/column allowlists with bound SQL values.

The live dashboard uses a short shared snapshot cache so multiple browsers do not multiply expensive metrics queries. This improves operator visibility; it is not a replacement for an external metrics system or a multi-node control-plane coordinator.
