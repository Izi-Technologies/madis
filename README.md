# Madis

A SIP proxy and registrar written in [Mako](https://github.com/mako-lang).

## What is this?

Madis started as an internal tool we needed for handling SIP routing, registration, and authentication. It does the usual proxy things — forwards requests, manages registrations, handles NAT, talks to RTPEngine for media relay — and tries to stay reasonably close to the relevant RFCs while doing it.

It's still a work in progress. Some parts are more polished than others.

## What it does

- Proxies and registers SIP endpoints (RFC 3261)
- Digest auth (MD5, SHA-256) with nonce expiry
- STIR/SHAKEN caller ID signing (ES256)
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
- `SIP_ADMIN_PORT` — turns on the HTTP admin interface
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
database load. If the standalone admin service owns port
8080, set `SIP_ADMIN_PORT=0` for the SIP worker.

After installation:

```sh
madis version
madis status
madis health
madis webui
madis logs admin
```

## License

[MIT](LICENSE)
