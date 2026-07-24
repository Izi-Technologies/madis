# Madis

A SIP proxy and registrar written in [Mako](https://github.com/mako-lang).

## What is this?

Madis started as an internal tool we needed for handling SIP routing, registration, and authentication. It does the usual proxy things — forwards requests, manages registrations, handles NAT, talks to RTPEngine for media relay — and tries to stay reasonably close to the relevant RFCs while doing it.

It's still a work in progress. Some parts are more polished than others.

## What it does

- Proxies and registers SIP endpoints (RFC 3261)
- Digest auth (MD5, SHA-256) with nonce expiry
- STIR/SHAKEN scaffolding (the current HMAC placeholder is not production ES256)
- NAT handling via `rport`/`received` (RFC 3581)
- RTPEngine integration for media relay
- UDP, TCP, TLS, and WebSocket transports
- Outbound WebRTC SIP signaling over persistent WSS
- Separate Mako SIP WebUI/admin service under `admin/`
- IPv6 support
- DNS resolution with NAPTR/SRV lookups (RFC 3263)
- Dialplan with pattern matching and rewriting
- Transaction state machines, forking, retransmission
- A small HTTP admin interface for health checks, metrics, and config reload

## Modules

The proxy is split across a handful of `.mko` files. `main.mko` is the entry point and pulls everything else in:

`parser` `headers` `auth` `registration` `routing` `dialplan` `nat` `transport` `stream` `rtpengine` `shaken` `security` `rfc` `db` `log` `ops`

## Installation

### Linux (Debian/Ubuntu, RHEL/CentOS/Fedora/Rocky/Alma)

The install script handles everything — system packages, PostgreSQL, database schema, credentials, systemd service, firewall rules, and log rotation.

```sh
sudo ./install.sh
```

It generates the database password and admin API token for you and prints them at the end. Everything goes into `/etc/madis/madis.env`.
The installer also installs the Mako SIP WebUI source/binary and the `madis`
CLI (`madisctl` is an alias) for service status, health checks, logs, and
version reporting.

You can override defaults before running:

```sh
sudo MADIS_DB_NAME=mysipdb MADIS_SIP_PORT=5080 ./install.sh
```

### Docker

```sh
docker compose up -d
```

This starts Madis and a PostgreSQL instance together. See `docker-compose.yml` for details.

## Building from source

You'll need Mako 0.4.15.

The current Madis release version is recorded in [`VERSION`](VERSION),
separately from the required Mako compiler/runtime version.

```sh
MAKO_RUNTIME=/path/to/mako/runtime mako build --release --strip --no-incremental main.mko -o madis
```

To run the checks and tests:

```sh
MAKO_RUNTIME=/path/to/mako/runtime mako check --no-incremental main.mko
MAKO_RUNTIME=/path/to/mako/runtime mako lint main.mko
MAKO_RUNTIME=/path/to/mako/runtime mako test tests
```

## Configuration

Madis reads its config from environment variables (or `/etc/madis/madis.env` when installed via the script). The main ones:

- `SIP_DB_URL` — PostgreSQL connection string
- `SIP_ADMIN_PORT` — turns on the SIP worker's local health/metrics interface;
  set it to `0` when using the standalone WebUI service
- `ADMIN_BIND` / `ADMIN_PORT` — bind address and port for the standalone Mako
  SIP WebUI (defaults to `127.0.0.1:8080`)
- `SIP_ADMIN_TOKEN` — if set, admin endpoints require a bearer token
- `SIP_CONFIG_FILE` — path to a watched file; touching it triggers a config reload
- `SIP_IPV6` — `1` by default, set to `0` if your host doesn't have IPv6
- `SIP_TLS_CERT` / `SIP_TLS_KEY` — paths to TLS certificate and key
- `SIP_UPSTREAM_CA` — CA bundle used to verify outbound TLS/WSS peers
- `SIP_UPSTREAM_TLS_INSECURE=1` — lab-only opt-in to skip outbound TLS verification
- `SIP_WSS_IDLE_MS` — idle lifetime for outbound WSS associations; defaults to 600000 ms

## Outbound WSS and WebRTC signaling

SIP contacts with `transport=wss` are sent through a persistent TLS/WebSocket
association. The proxy keeps the association available for provisional and
final responses, ACK/BYE traffic, and subsequent requests to the same WSS
peer. RFC 6455 framing, masking, control frames, and connection cleanup are
handled by Mako 0.4.15.

Configure `SIP_UPSTREAM_CA` with the trusted CA bundle for production WSS
peers. Certificate verification is required by default; for an isolated
interoperability lab only, set `SIP_UPSTREAM_TLS_INSECURE=1`. Associations
that remain idle are closed after `SIP_WSS_IDLE_MS` (bounded to one minute
through 24 hours).

The end-to-end check is:

```sh
python3 bench/wss_outbound_matrix.py --binary ./main
```

This validates WebRTC SIP signaling over WSS. ICE, DTLS-SRTP, and media relay
remain separate media-plane responsibilities handled by the configured RTP
engine.

## WebUI / control plane

The Mako SIP WebUI is included under [`admin/`](admin/). Build it as a
separate service with Mako 0.4.15:

```sh
MAKO_RUNTIME=/path/to/mako/runtime \
  mako build --release --strip --no-incremental admin/main.mko -o admin-bin
```

Run the admin service on loopback (`ADMIN_BIND=127.0.0.1`,
`ADMIN_PORT=8080`) behind nginx or another TLS reverse proxy. It provides the
authenticated `/admin` control plane, HTMX views, and a WebSocket live
dashboard with polling fallback. Live dashboard snapshots use a short shared
cache and a single aggregate count query so multiple operators do not multiply
database load; the first paint is not blocked by SIP or metrics probes. If the
standalone admin service owns port
8080, set `SIP_ADMIN_PORT=0` for the SIP worker.

The control plane parses each form body once per request and uses bound SQL
parameters for request and database-derived values. The generic toggle/delete
actions accept only the fixed table/column pairs rendered by the UI; arbitrary
SQL identifiers are rejected. Routing-rule updates use the connection-local
insert id, so concurrent administrators cannot overwrite one another's new
rule.

The admin listener rejects oversized or truncated HTTP bodies, bounds sessions
and login-failure state, caps session lifetime at seven days, and escapes
database/configuration values at every HTML/JavaScript output boundary. Keep it
loopback-bound and put HTTPS/WSS termination in a reverse proxy. Browser POSTs
also require a matching `Origin`/`Host` pair; non-browser clients without an
Origin remain supported.

## Hardening and compliance scope

The supported entry point is the modular `main.mko`; `sipproxy_full.mko` is a
legacy reference archive and is not the deployment target. The proxy bounds
attacker-derived caches (auth, ACL, bans, DNS, routing, rate limiting, dialog,
RTP, and transaction state), validates explicit SIP target ports, fails closed
for database-backed IP trust when the database is unavailable, and uses
parameterized SQL for values. Transaction rings are sized for higher
concurrency and swept incrementally to keep timer work bounded.

The RFC gate exercises the implemented RFC 3261/3263/3581/6455 behavior,
malformed input, transport matrices, WSS outbound signaling, auth cases, and
fuzz traffic. Passing those checks is evidence for the tested behavior; it is
not a formal claim of universal or mathematically provable 100% RFC
compliance. Review the deployment-specific TLS, DNS, media, and interop
requirements before production use.

After installation:

```sh
madis version
madis status
madis health
madis webui
madis logs admin
```

The WebUI is a separate `madis-admin.service` process. It does not require
Leba: terminate public TLS/WebSocket traffic in nginx or another reverse proxy
and forward it to `ADMIN_BIND`/`ADMIN_PORT`. The installer builds the UI with
Mako 0.4.15 when that compiler is available, or accepts a prebuilt
`admin-bin` for offline packaging.

## License

[MIT](LICENSE)
