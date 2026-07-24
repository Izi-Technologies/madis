# Mako SIP Admin Panel

This is the Mako SIP control-plane WebUI source imported from the live
`mako-admin.service` deployment. It is intentionally separate from the SIP
worker binary and does not depend on Leba.

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
# Mako 0.4.15 is required.
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental admin/main.mko -o admin-bin
```

The admin service listens on `ADMIN_BIND`/`ADMIN_PORT` (loopback and `8080`
by default). Put TLS and WebSocket proxying in nginx or another reverse proxy.
When this service is enabled, set `SIP_ADMIN_PORT=0` for the SIP worker so it
does not attempt to claim the same port.

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

The live deployment uses `/admin/login`, authenticated session cookies, HTMX
page updates, and a WebSocket live dashboard with HTTP polling fallback. The
dashboard refreshes its expensive database/metrics snapshot at most every
three seconds and shares it across connected clients; the browser still gets
one-second WebSocket updates. The first paint does not wait on SIP or metrics
probes, and the UI defers its optional browser asset so a slow third-party CDN
cannot block the control plane.

The cache is intentionally short-lived so dashboard counts remain responsive
without multiplying PostgreSQL work across operators. A deployment must use
`SIP_ADMIN_PORT=0` for the SIP worker when `madis-admin.service` owns the
WebUI port. Public HTTPS/WSS termination belongs in nginx or another reverse
proxy; the admin process itself should remain loopback-bound.
