# Madis

A SIP proxy and registrar written in [Mako](https://github.com/mako-lang).

## What is this?

Madis started as an internal tool we needed for handling SIP routing, registration, and authentication. It does the usual proxy things — forwards requests, manages registrations, handles NAT, talks to RTPEngine for media relay — and tries to stay reasonably close to the relevant RFCs while doing it.

It's still a work in progress. Some parts are more polished than others.

## Quick start

For a Linux host, the shortest path is:

```sh
sudo ./install.sh
madis status
madis health
madis webui
```

The installer creates PostgreSQL state, systemd units, the SIP worker, the
standalone WebUI, and the `madis` CLI. Keep the WebUI on loopback and put
HTTPS/WSS termination in a reverse proxy before exposing it outside the host.
For a local source build, use the native build and CI commands below.

If you are deciding where to start:

| Need | Start here |
| --- | --- |
| Install and operate a host | [`install.sh`](install.sh), [`madis`](scripts/madis) |
| Build and validate Madis | [`scripts/build-native.sh`](scripts/build-native.sh), [`scripts/ci.sh`](scripts/ci.sh) |
| Add a carrier application | [`api/README.md`](api/README.md), [`sdk/README.md`](sdk/README.md) |
| Configure the WebUI | [`admin/README.md`](admin/README.md) |
| Compare CPS and concurrency | [`bench/README.md`](bench/README.md) |
| Review Diameter/IMS and SS7 boundaries | [`api/diameter.md`](api/diameter.md), [`api/ims-diameter.md`](api/ims-diameter.md) |

The longer guides are in [`docs/`](docs/):
[`architecture.md`](docs/architecture.md) explains the process and data flow,
[`configuration.md`](docs/configuration.md) lists runtime settings,
[`operations.md`](docs/operations.md) covers installation and upgrades, and
[`testing.md`](docs/testing.md) describes the validation and benchmark gates.
[`PRODUCTION.md`](PRODUCTION.md) and [`RFC_COMPLIANCE.md`](RFC_COMPLIANCE.md)
are the concise production and protocol-status references.

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
- Versioned carrier integration API with an idempotent billing outbox
- Extensible CDR, online-charging, IMS, and SS7/SIGTRAN adapter contracts

## Modules

The proxy is split across a handful of `.mko` files. `main.mko` is the entry point and pulls everything else in:

`parser` `headers` `auth` `registration` `routing` `dialplan` `nat` `transport` `stream` `rtpengine` `shaken` `security` `rfc` `billing` `charging` `db` `log` `ops`

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

Check the container before sending traffic:

```sh
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/healthz
```

Both endpoints belong to the SIP worker's internal HTTP control plane in this
single-process image. The Docker image does not start the standalone WebUI;
use the Linux installer, or run the separately built `admin-bin`, when browser
administration is required.

## Building from source

You'll need Mako 0.4.16.

The current Madis release version is recorded in [`VERSION`](VERSION),
separately from the required Mako compiler/runtime version.

```sh
MAKO_BIN=mako MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko madis
```

`scripts/build-native.sh` emits C with Mako 0.4.16 and links the small native
CMap ownership bridge used by the transaction timers. To run the checks,
tests, native links, and schema validation together:

```sh
MAKO_BIN=mako MAKO_RUNTIME=/path/to/mako/runtime ./scripts/ci.sh
```

## Configuration

Madis reads its config from environment variables (or `/etc/madis/madis.env` when installed via the script). The main ones:

- `SIP_DB_URL` — PostgreSQL connection string
- `SIP_ADMIN_PORT` — port for the SIP worker's local health/metrics interface;
  the installer uses `9090` so the standalone WebUI can read live metrics
- `SIP_METRICS_HOST` / `SIP_METRICS_PORT` — WebUI target for that internal
  worker endpoint; keep it aligned with `SIP_ADMIN_PORT` and separate from
  `ADMIN_PORT`; use `SIP_ADMIN_PORT=0` only to disable the endpoint
- `ADMIN_BIND` / `ADMIN_PORT` — bind address and port for the standalone Mako
  SIP WebUI (defaults to `127.0.0.1:8080`)
- `SIP_ADMIN_TOKEN` — if set, admin endpoints require a bearer token
- `SIP_CONFIG_FILE` — path to a watched file; touching it triggers a config reload
- `SIP_IPV6` — `1` by default, set to `0` if your host doesn't have IPv6
- `SIP_TLS_CERT` / `SIP_TLS_KEY` — paths to TLS certificate and key
- `SIP_UPSTREAM_CA` — CA bundle used to verify outbound TLS/WSS peers
- `SIP_UPSTREAM_TLS_INSECURE=1` — lab-only opt-in to skip outbound TLS verification
- `SIP_WSS_IDLE_MS` — idle lifetime for outbound WSS associations; defaults to 600000 ms
- `SIP_SCHED_WORKERS` — optional bounded Mako scheduler pool for `crew`/`kick`; values
  below the listener count are raised automatically, while `0` keeps one pthread per kick
- `SIP_CARRIER_API_TOKEN` — bearer token for the versioned machine API
- `SIP_BILLING_MODE` — `outbox` (default), `preauth`, or `off`
- `SIP_BILLING_TENANT` — tenant value placed in the billing envelope
- `SIP_CHARGING_PROTOCOL` — `http` (default) or native `diameter`
- `SIP_CHARGING_URL` — HTTPS online-charging adapter URL when `preauth` is enabled
- `SIP_CHARGING_TIMEOUT_MS` — bounded pre-authorization timeout, 20–1000 ms
- `SIP_CHARGING_FAIL_OPEN=1` — explicit availability-over-revenue policy override
- `SIP_DIAMETER_HOST` / `SIP_DIAMETER_PORT` — Diameter CC peer (`5658` with TLS,
  `3868` with plaintext when the port is not set)
- `SIP_DIAMETER_TLS=1` — use verified TLS/TCP by default; plaintext requires an explicit opt-in
- `SIP_DIAMETER_TRANSPORT=sctp` — use SCTP when Mako and the host platform provide it;
  protect the association externally and explicitly set `SIP_DIAMETER_ALLOW_PLAINTEXT=1`
- `SIP_DIAMETER_PERSISTENT=1` — reuse one serialized verified-TLS peer for RFC 8506 exchanges
- `SIP_DIAMETER_CA` — CA bundle for the Diameter peer; `SIP_DIAMETER_CLIENT_CERT` and
  `SIP_DIAMETER_CLIENT_KEY` enable mTLS
- `SIP_DIAMETER_ORIGIN_HOST` / `SIP_DIAMETER_ORIGIN_REALM` / `SIP_DIAMETER_DEST_REALM`
  — Diameter identities
- `SIP_IMS_CX=1` — enable fail-closed Cx UAR/SAR checks for REGISTER
- `SIP_IMS_VISITED_NETWORK` / `SIP_IMS_SERVER_NAME` / `SIP_IMS_DEST_HOST` — optional IMS
  routing identities used by the Cx and Sh builders

## Outbound WSS and WebRTC signaling

SIP contacts with `transport=wss` are sent through a persistent TLS/WebSocket
association. The proxy keeps the association available for provisional and
final responses, ACK/BYE traffic, and subsequent requests to the same WSS
peer. RFC 6455 framing, masking, control frames, and connection cleanup are
handled by Mako 0.4.16.

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

The Mako SIP WebUI is included under [`admin/`](admin/). Build and run it as a
separate service with Mako 0.4.16:

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
standalone admin service owns port 8080, keep the SIP worker's internal metrics
endpoint on a different port (the installer uses `127.0.0.1:9090`) and set
`SIP_METRICS_HOST/PORT` to it.

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
Mako 0.4.16 when that compiler is available, or accepts a prebuilt
`admin-bin` for offline packaging.

## Carrier applications, billing, and charging

The machine API and schemas are in [`api/`](api/); small clients for Python,
JavaScript, Go, Lua, and Erlang are in [`sdk/`](sdk/). The API uses JSON/HTTP
for universal reach and includes a Protobuf contract for teams using gRPC.
Applications own their business schema: the envelope is versioned, while
`data`, `extensions`, and additional fields are open and stored as JSONB.

The proxy writes CDR lifecycle events to `billing_events` with deterministic
event IDs. Delivery is at-least-once: consume, commit, deduplicate by
`event_id`, and then acknowledge. The page limit is 100 and the JSON request
limit is 64 KiB. These bounds are part of the contract, not suggestions.

`SIP_BILLING_MODE=preauth` is the opt-in online charging path. With the default
`SIP_CHARGING_PROTOCOL=http`, it sends a bounded HTTPS JSON request before
routing an INVITE. With `SIP_CHARGING_PROTOCOL=diameter`, it performs RFC 6733
CER/CEA negotiation and RFC 8506 CCR/CCA over verified TLS/TCP, including
initial and termination requests and bounded request/answer validation. Set
`SIP_DIAMETER_PERSISTENT=1` to reuse a serialized peer connection. With both
client certificate variables above, persistent Diameter uses pooled mTLS. Plain
TCP is a lab override only and must be explicitly
enabled. Post-call failures do not block SIP completion; initial authorization
is fail-closed unless `SIP_CHARGING_FAIL_OPEN=1` is set.

The native Diameter layer also contains the 3GPP Cx/Dx and Sh wire contracts.
When `SIP_IMS_CX=1`, REGISTER performs Cx UAR followed by SAR and rejects the
registration if the HSS does not authorize it. See
[`api/diameter.md`](api/diameter.md) and [`api/ims-diameter.md`](api/ims-diameter.md)
for the supported matrix and the interfaces that still require an external
IMS component.

## IMS and SS7/SIGTRAN integration boundaries

Madis is a hardened SIP edge/proxy and registrar, not a complete 3GPP IMS
core. [`api/ims-session.schema.json`](api/ims-session.schema.json) defines the
boundary for P-/I-/S-CSCF, HSS/UDM, PCRF/PCF, TAS/MMTel, media, and charging
services. Deploy those functions as carrier services and connect them through
the versioned API rather than coupling them to the SIP worker.

[`api/ss7-m3ua-envelope.schema.json`](api/ss7-m3ua-envelope.schema.json)
defines the external SIGTRAN boundary for routing context, point codes, SLS,
service indicator, and SCCP/ISUP/TCAP payloads. Mako 0.4.16 exposes SCTP
primitives, and Madis can use SCTP for Diameter when the platform provides it;
it still does not terminate M3UA, so capabilities report
`native_sctp_m3ua=false`. An SS7 gateway must terminate SCTP/M3UA and enforce
RFC 4666, RFC 4960, and carrier-specific SS7 interworking requirements.

All new integration code must preserve the memory-safety boundary: bounded
inputs, no raw pointer or unsafe application extensions, parameterized SQL,
idempotent retries, and explicit timeout/failure policies. Passing the local
tests does not by itself certify an IMS, Diameter, or SS7 deployment.

## License

[MIT](LICENSE)
