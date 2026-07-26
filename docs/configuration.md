# Configuration

Madis reads process settings from environment variables. The installer writes
`/etc/madis/madis.env`; a container normally receives the same values from
`docker-compose.yml`. Runtime routing, user, gateway, and policy records live
in PostgreSQL when the relevant feature is enabled.

The values below describe the supported knobs. Defaults shown are source
defaults; the installer may choose a different operational value.

## Minimum configuration

```sh
SIP_DB_URL=postgres://madis:password@127.0.0.1:5432/madis
SIP_UDP_PORT=5060
SIP_TLS_PORT=5061
SIP_WSS_PORT=8443
SIP_REALM=example.net
SIP_NODE_ID=edge-1
SIP_ADMIN_PORT=9090
SIP_METRICS_HOST=127.0.0.1
SIP_METRICS_PORT=9090
SIP_ADMIN_TOKEN=replace-me
```

For the installed two-process layout, keep the worker's internal HTTP endpoint
and the WebUI listener on different ports:

```sh
SIP_ADMIN_PORT=9090
SIP_METRICS_HOST=127.0.0.1
SIP_METRICS_PORT=9090
ADMIN_BIND=127.0.0.1
ADMIN_PORT=8080
SIP_ADMIN_PASSWORD=choose-a-bootstrap-password
SIP_CARRIER_API_TOKEN=separate-machine-token
SIP_CONTROL_API_TOKEN=separate-routing-control-token
SIP_APP_TOKEN=separate-live-sip-application-token
SIP_MODULE_TOKEN=separate-module-bus-token
```

The standalone WebUI uses `SIP_METRICS_HOST/PORT` to read the worker's health,
metrics, and state data. Set `SIP_ADMIN_PORT=0` only when that local endpoint
is intentionally disabled and live SIP metrics are not needed.

Do not put real secrets in a committed compose file, shell history, or a
publicly readable environment file.

## Network and identity

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_BIND_IP` | `0.0.0.0` | SIP listener bind address. |
| `SIP_PUBLIC_IP` | source address | Address used for advertised SIP/SDP-facing values when configured. |
| `SIP_PUBLIC_HOST` | empty | WebUI/health display fallback. |
| `SIP_UDP_PORT` | `5060` | UDP and TCP SIP port. |
| `SIP_TLS_PORT` | `5061` | SIP over TLS listener. |
| `SIP_WSS_PORT` | `8443` | SIP over WebSocket listener; public TLS termination is deployment-specific. |
| `SIP_IPV6` | `1` | Enable the IPv6 UDP listener where the host supports it. |
| `SIP_REALM` | `mako.local` | Digest and SIP realm. |
| `SIP_DOMAIN` / `SIP_FQDN` | empty | Domain fallbacks used by WebUI gateway checks. |
| `SIP_NODE_ID` | `node1` | Node identity stored with registrations and cluster records. |
| `SIP_NODE_ADDR` | `127.0.0.1` | Node address for cluster metadata. |
| `SIP_REGION` | `default` | Optional cluster region label. |
| `SIP_DIAMETER_HOST_IP` | `127.0.0.1` | IPv4 address encoded in Diameter Host-IP-Address AVPs. |
| `MADIS_VERSION` | `dev` (source) | Version shown by health and CLI; the installer reads `VERSION` when present. |

The installed WebUI also uses `SIP_METRICS_HOST` (default `127.0.0.1`) and
`SIP_METRICS_PORT` (default `9090`) as its target for worker health, metrics,
and state requests. If `SIP_ADMIN_TOKEN` is set, the WebUI forwards it to that
internal endpoint.

Ports below 1 or above 65535 are rejected. Keep the standalone admin listener
on loopback unless a reverse proxy and network policy protect it.

## Workers and timers

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_UDP_WORKERS` | `1` | UDP worker count. |
| `SIP_TCP_WORKERS` | `1` | Stream worker count. |
| `SIP_SCHED_WORKERS` | `0` | Mako `crew`/`kick` pool; `0` uses the default per-kick threads. |
| `SIP_T1_MS` | `500` | RFC-style transaction base timer, bounded by the implementation. |
| `SIP_T2_MS` | `4000` | Non-INVITE retransmission ceiling. |
| `SIP_TIMER_C_MS` | `180000` | Proxy INVITE timer C. |
| `SIP_TIMER_L_MS` | `32000` | Server 2xx retention lifetime. |
| `SIP_WSS_IDLE_MS` | `600000` | Outbound WSS idle lifetime, bounded to one minute through 24 hours. |

Changing timers changes interop behavior. Use the RFC gate and an independent
SIP stack before changing them in production.

## TLS, WSS, and WebRTC signaling

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_TLS_CERT` / `SIP_TLS_KEY` | auto-generated lab cert | Use an operator-managed certificate in production. |
| `SIP_TLS_AUTO_CERT` / `SIP_TLS_AUTO_KEY` | temporary paths | Paths for the generated lab certificate. |
| `SIP_TLS_CN` | `localhost` | Name for the generated lab certificate. |
| `SIP_TLS_SNI` | empty | Optional local SNI selection. |
| `SIP_UPSTREAM_CA` | empty | CA bundle for outbound TLS/WSS verification. |
| `SIP_UPSTREAM_TLS_INSECURE` | `0` | `1` disables outbound verification; lab use only. |

Outbound WSS is SIP signaling, not a media implementation. ICE, DTLS-SRTP, and
RTP remain the responsibility of the endpoint and configured media system.
Certificate verification is enabled by default when a CA is configured; do
not use the insecure override for carrier traffic.

## Authentication and security

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_DIGEST_ALGORITHM` | `md5` | Supports the implemented digest profiles; select a stronger profile when all peers support it. |
| `SIP_USER_RATE_LIMIT` | `100` | Per-user rate limit used by dialplan/security policy. |
| `SIP_ADMIN_TOKEN` | empty | Bearer token for the SIP worker admin endpoints; empty means no token on that local endpoint. |
| `SIP_CARRIER_API_TOKEN` | empty | Bearer token for billing event and integration endpoints. |
| `SIP_CONTROL_API_TOKEN` | empty | Separate bearer token for routing-rule and B2BUA policy changes; keep it server-side. |
| `SIP_CONTROL_API_READ_TOKEN` | empty | Optional read-only bearer token for control status and resource/list calls. It cannot mutate state. |
| `SIP_APP_URL` | empty | Optional HTTPS endpoint for live signed SIP application decisions. Disabled when empty. |
| `SIP_APP_TOKEN` | empty | Shared secret for the live SIP application endpoint; never put it in browser code. |
| `SIP_APP_CA` | empty | Optional CA bundle for the application endpoint. Empty uses the platform trust paths. |
| `SIP_APP_TIMEOUT_MS` | `100` | Application decision timeout, clamped to 10–1000 ms. |
| `SIP_APP_FAIL_MODE` | `open` | `open` preserves local SIP when the optional app fails; `closed` returns 503. |
| `SIP_APP_ALLOW_HTTP` | `0` | Explicitly allow plain HTTP for a protected lab/local network only. |
| `SIP_MODULE_URL` | empty | Optional module dispatcher for TTS, STT, LLM, media, recording, fraud, or billing operations. |
| `SIP_MODULE_TOKEN` | empty | Separate shared secret for module requests and signed module commands. |
| `SIP_MODULE_CA` | empty | Optional CA bundle for the module dispatcher. |
| `SIP_MODULES` | empty | Optional allowlist, e.g. `tts,stt,llm,media,recording`; built-in names are allowed when empty. |
| `SIP_MODULE_ALLOW_CUSTOM` | `0` | Permit custom module names/operations only when explicitly enabled. |
| `SIP_MODULE_TIMEOUT_MS` | `250` | Module timeout, clamped to 10–2000 ms. |
| `SIP_MODULE_FAIL_MODE` | `closed` | Module failure behavior; `open` is appropriate only for optional enrichment. |
| `SIP_MODULE_ALLOW_HTTP` | `0` | Explicitly allow plain HTTP for a protected lab/local network only. |
| `ADMIN_METRICS_TOKEN` | empty | Optional token for standalone WebUI metrics proxy routes. |
| `SIP_CONFIG_FILE` | empty | File mtime is a reload signal; it does not contain routing credentials. |
| `SIP_CRASH_REPORT` | empty | Optional path for the native crash report facility. |

The WebUI has separate settings: `ADMIN_BIND`, `ADMIN_PORT`,
`ADMIN_SECURE_COOKIE`, `ADMIN_SESSION_TTL_SECS`, `ADMIN_LOGIN_MAX_FAILS`, and
`ADMIN_LOGIN_LOCK_SECS`. `SIP_ADMIN_PASSWORD` bootstraps the first `admin`
user only when no users exist and a database is available. Change that password
through the WebUI and keep the bootstrap value out of long-lived logs.

## Registration policy

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_MAX_REG_EXPIRES` | `3600` | Maximum requested registration lifetime, clamped to 60 seconds–24 hours. |
| `SIP_MIN_EXPIRES` | `60` | Requests below this produce 423; clamped to 0–24 hours. |

Registration state is bounded in memory and may be hydrated from PostgreSQL.
Expiry and wildcard removal behavior is covered by the proxy-state tests.

## B2BUA mode

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_B2BUA_MODE` | `proxy` | Set to `enabled` to permit explicit `b2bua:` routing actions. Ordinary routes remain proxy routes. |
| `SIP_B2BUA_STATE_MS` | `1800000` | In-memory early/confirmed leg lifetime, clamped to 64 seconds–24 hours. |
| `SIP_B2BUA_CALLID_HOST` | `madis.local` | Host part used for generated downstream Call-IDs. |
| `SIP_B2BUA_BIND_IP` | `SIP_PUBLIC_IP` or `SIP_BIND_IP` | Signaling address advertised on the generated leg. |
| `SIP_B2BUA_SIGNAL_PORT` | `SIP_UDP_PORT` | Signaling port used in generated Via and Contact values. |
| `SIP_B2BUA_CONTACT_HOST` | signal address | Optional Contact host override. |
| `SIP_B2BUA_CONTACT_PORT` | signal port | Optional Contact port override. |
| `SIP_B2BUA_CONTACT_USER` | `b2bua` | Generated Contact user part. |

The current implementation is an explicit single-target B2BUA path with
independent Call-ID/tags and bounded state. It handles the initial INVITE,
responses, caller ACK/BYE/CANCEL/re-INVITE, downstream BYE, and non-2xx ACK
generation. Forked B2BUA legs, REFER/INFO/UPDATE/PRACK/100rel, and a complete
third-party-call-control implementation remain outside this switch; test the
peer behavior before enabling it for carrier traffic.

## Runtime call control

`SIP_CONTROL_API_TOKEN` authorizes the versioned WebUI control endpoints. They
can list, create, replace, delete, enable, and disable the allowlisted Madis
SIP resources. `SIP_CONTROL_API_READ_TOKEN` can read status and lists but
cannot mutate state. Neither token can change environment variables, execute
Mako or SQL, or mutate arbitrary tables. A `b2bua:` rule is inert until
`SIP_B2BUA_MODE=enabled`; changing that environment setting requires a service
restart.

The control resource API is deliberately not a general application database
interface. External applications keep their own billing, tenant, rating,
invoice, and custom tables. Madis stores only routing and SIP state. Resource
documents contain Madis-owned fields; unknown fields are not persisted as
columns. Mutable rows expose a `revision`; clients may send
`expected_revision` to reject stale updates and deletes.

For live application control and external media/AI workers, see
[`modules.md`](modules.md). Those endpoints receive signed bounded JSON; they
do not receive SQL access or executable Mako code.

## Billing and HTTP charging

| Variable | Default | Notes |
| --- | --- | --- |
| `SIP_BILLING_MODE` | `outbox` | `outbox`, `preauth`, or `off`. |
| `SIP_BILLING_TENANT` | `default` | Tenant field in event envelopes. |
| `SIP_CHARGING_PROTOCOL` | `http` | HTTP adapter or native `diameter`. |
| `SIP_CHARGING_URL` | empty | HTTPS/HTTP charging adapter URL when preauthorization is enabled. |
| `SIP_CHARGING_CA` | empty | CA bundle for the HTTPS charging adapter. |
| `SIP_CHARGING_TIMEOUT_MS` | `150` | Bounded online charging timeout. |
| `SIP_CHARGING_FAIL_OPEN` | `0` | Explicitly allow routing when preauthorization is unavailable; review this as a revenue policy. |

The default outbox path does not make an external charging call on the SIP
critical path. Preauthorization is fail-closed unless `FAIL_OPEN` is explicitly
enabled. See [`../api/README.md`](../api/README.md) for event acknowledgment
and custom schemas.

## Diameter and IMS

The native Diameter settings are only used when the corresponding charging or
IMS path is enabled:

`SIP_DIAMETER_HOST`, `SIP_DIAMETER_PORT`, `SIP_DIAMETER_TLS`,
`SIP_DIAMETER_CA`, `SIP_DIAMETER_CLIENT_CERT`, `SIP_DIAMETER_CLIENT_KEY`,
`SIP_DIAMETER_TRANSPORT`, `SIP_DIAMETER_ALLOW_PLAINTEXT`,
`SIP_DIAMETER_PERSISTENT`, `SIP_DIAMETER_TIMEOUT_MS`,
`SIP_DIAMETER_ORIGIN_HOST`, `SIP_DIAMETER_ORIGIN_REALM`,
`SIP_DIAMETER_DEST_REALM`, `SIP_DIAMETER_SERVICE_CONTEXT`,
`SIP_DIAMETER_SERVICE_ID`, `SIP_DIAMETER_SUBSCRIPTION_TYPE`,
`SIP_DIAMETER_REQUESTED_ACTION`, and `SIP_DIAMETER_REQUESTED_SECONDS`.

`SIP_DIAMETER_TLS=1` is the default. Plaintext requires an explicit
override and a separate network protection decision. `sctp` depends on host
and Mako runtime support. `SIP_IMS_CX=1` enables the fail-closed REGISTER Cx
UAR/SAR path; `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and
`SIP_IMS_DEST_HOST` provide its identities. Read the protocol-specific limits
in [`../api/diameter.md`](../api/diameter.md) and
[`../api/ims-diameter.md`](../api/ims-diameter.md).

## STIR/SHAKEN

The optional settings are `STIR_SHAKEN_ENABLED`, `STIR_SHAKEN_MODE`,
`STIR_SHAKEN_SECRET`, `STIR_SHAKEN_CERT_URL`, `STIR_SHAKEN_ATTESTATION`,
`STIR_SHAKEN_PRIVATE_KEY`, `STIR_SHAKEN_PUBLIC_KEY`, `STIR_SHAKEN_JWKS`, and
`STIR_SHAKEN_JWKS_URL`. Keep private keys outside the repository and use a
carrier-approved certificate/JWKS rotation process. The current implementation
has explicit lab/interoperability paths; review the deployed mode before
claiming production attestation compliance.

## Database and reload behavior

`SIP_DB_URL` selects PostgreSQL. The installer creates the initial schema and
the application creates a small set of idempotent tables when needed. Treat
schema changes as migrations: back up the database, review SQL, and test the
upgrade before applying it to a carrier database.

Touching `SIP_CONFIG_FILE` invalidates selected in-memory configuration caches.
It does not reload the environment, rotate secrets, or change database rows.
Restart the relevant systemd service for environment changes.
