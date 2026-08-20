# Configuration

Madis reads environment variables at process start. The installer writes them to `/etc/madis/madis.env`; Docker supplies them through `docker-compose.yml`; a source run can export them in the shell or use a process manager’s environment file.

The SIP worker and standalone WebUI are separate processes. `SIP_ADMIN_PORT` is the worker’s local health/metrics HTTP port. `ADMIN_PORT` is the WebUI port. Keep them different when both processes run on one host.

## Minimal host configuration

```sh
SIP_DB_URL='postgres://<db-user>:<db-password>@<db-host>:5432/<db-name>'
SIP_BIND_IP=<signaling-bind-address>
SIP_UDP_PORT=5060
SIP_TLS_PORT=5061
SIP_WSS_PORT=8443
SIP_REALM=example.net
SIP_NODE_ID=edge-1

# Worker-local HTTP surface; do not publish this as the WebUI.
SIP_ADMIN_PORT=9090
SIP_METRICS_HOST=<worker-host>
SIP_METRICS_PORT=9090

# Standalone WebUI.
ADMIN_BIND=<admin-bind-address>
ADMIN_PORT=8080
ADMIN_SECURE_COOKIE=1

: "${SIP_ADMIN_TOKEN:?set via secret manager}"
: "${SIP_CARRIER_API_TOKEN:?set via secret manager}"
: "${SIP_CONTROL_API_TOKEN:?set via secret manager}"
: "${SIP_CONTROL_API_READ_TOKEN:?set via secret manager}"
```

Use long, random values for every token. The installer generates these credentials when they are not supplied and writes the result to the protected environment file.

## SIP listeners and identity

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_BIND_IP` | wildcard bind (set explicitly) | Local IPv4 signaling bind address for the UDP/TCP/TLS/WSS listeners. Invalid values fall back to the wildcard; IPv6 listeners remain governed by `SIP_IPV6`. |
| `SIP_PUBLIC_IP` | Empty/auto-detected by installer | Address advertised in SIP/SDP-facing values when the host is behind NAT. |
| `SIP_PUBLIC_HOST` | Empty | Public host identity used by deployment-specific checks and generated signaling values. |
| `SIP_UDP_PORT` | `5060` | UDP signaling listener. |
| `SIP_TCP_PORT` | `SIP_UDP_PORT` | TCP signaling listener; defaults to the UDP port. |
| `SIP_TLS_PORT` | `5061` | SIP over TLS listener. |
| `SIP_WSS_PORT` | `8443` | Secure WebSocket SIP listener (RFC 7118). Compatible with SIP.js, JsSIP, and other WebRTC SIP stacks. Echoes `Sec-WebSocket-Protocol: sip` subprotocol. |
| `SIP_IPV6` | `1` | Enable IPv6 listeners where the host supports them. |
| `SIP_REALM` | `madis.local` | Digest authentication realm. |
| `SIP_DOMAIN` / `SIP_FQDN` | Empty | Domain identity fallbacks. |
| `SIP_NODE_ID` | `node1` | Node identity used in registration and cluster metadata. |
| `SIP_NODE_ADDR` | configured node address | Node address metadata. |
| `SIP_REGION` | `default` | Optional region metadata. |
| `SIP_DIGEST_ALGORITHM` | `md5` | Digest profile; SHA-256 profiles are supported by the authentication layer. |
| `SIP_USER_RATE_LIMIT` | `100` | Bounded per-user security/rate policy value. |

## Worker HTTP and WebUI

The worker exposes local infrastructure endpoints such as `/healthz`, `/readyz`, `/metrics`, `/state`, and `POST /reload` on `SIP_ADMIN_PORT`. `SIP_ADMIN_TOKEN` must be a 16–512 character bearer token; worker requests fail closed when it is missing or invalid. Keep this listener protected by network policy.

The standalone WebUI serves `/admin/login`, browser pages, WebSocket live updates, and the machine API under `/admin/api/v1/`.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_ADMIN_PORT` | Installer `9090` | Worker-local HTTP port. Set to `0` only when the worker HTTP surface is intentionally disabled. |
| `SIP_ADMIN_TOKEN` | Required | 16–512 character bearer token for worker HTTP requests and WebUI-to-worker probes. |
| `SIP_METRICS_HOST` | configured worker host | Worker host targeted by the WebUI. |
| `SIP_METRICS_PORT` | `9090` in the installer layout | Worker port targeted by the WebUI. |
| `ADMIN_BIND` | configured admin bind address | Standalone WebUI bind address. |
| `ADMIN_PORT` | `8080` | Standalone WebUI port. |
| `ADMIN_SECURE_COOKIE` | `1` | Mark WebUI session cookies secure in the normal HTTPS deployment. |
| `ADMIN_SESSION_TTL_SECS` | `86400` | WebUI session lifetime, capped by the implementation. |
| `ADMIN_LOGIN_MAX_FAILS` | `5` | Failed-login threshold. |
| `ADMIN_LOGIN_LOCK_SECS` | `900` | Login lockout period. |
| `ADMIN_METRICS_TOKEN` | Empty | Optional 16–512 character bearer token for machine-only Prometheus/statistics proxy routes; query-string tokens are rejected. |

Terminate public HTTPS and WebSocket traffic in nginx, Caddy, HAProxy, or an equivalent edge. Preserve `Host`, `Origin`, and WebSocket upgrade headers. Browser POSTs use an `Origin`/`Host` check; origin-less machine requests remain supported.

## TLS and outbound transports

| Variable | Purpose |
| --- | --- |
| `SIP_TLS_CERT`, `SIP_TLS_KEY` | Operator-managed certificate and private key for SIP TLS/WSS. |
| `SIP_TLS_AUTO_CERT`, `SIP_TLS_AUTO_KEY`, `SIP_TLS_CN`, `SIP_TLS_SNI` | Optional certificate-generation and identity controls used by the deployment. |
| `SIP_UPSTREAM_CA` | CA bundle for outbound TLS/WSS verification. |
| `SIP_UPSTREAM_TLS_INSECURE=1` | Explicit lab-only bypass of outbound certificate verification. Do not use as a production fix. |
| `SIP_WSS_IDLE_MS` | Idle lifetime for reusable outbound WSS associations; the usual default is 600000 ms. |

## Worker scaling

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_UDP_WORKERS` | `1` | UDP listener worker count (max 8). |
| `SIP_TCP_WORKERS` | `1` | Stream listener worker count (max 8). |
| `SIP_TLS_WORKERS` | `1` | TLS listener worker count (max 4). |
| `SIP_WSS_WORKERS` | `1` | WebSocket-over-TLS listener worker count (max 4). |
| `SIP_SCHED_WORKERS` | `0` | Bounded Mako scheduler pool; `0` keeps the default per-kick threading behavior. |

## PROXY Protocol

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_PROXY_PROTOCOL` | `0` | Enable HAProxy PROXY Protocol v1 on stream listeners (`1`, `true`, or `yes`). |
| `SIP_PROXY_TRUSTED_IPS` | loopback only | Comma-separated IP whitelist of trusted load balancers permitted to send PROXY protocol headers. Without this, only `127.0.0.1` and `::1` are trusted. Required when `SIP_PROXY_PROTOCOL` is enabled to prevent source-IP spoofing. |

## Security and rate limiting

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_INVITE_RATE_LIMIT` | `20` | Maximum INVITE requests per second per source IP. |
| `SIP_REGISTER_RATE_LIMIT` | `10` | Maximum REGISTER requests per second per source IP. |
| `SIP_PER_IP_CONN_LIMIT` | `100` | Maximum concurrent TCP/TLS/WSS connections per source IP; bounded to `10..10000`. Excess connections are closed before SIP parsing. |
| `SIP_MAX_MESSAGE_SIZE` | `65536` | Maximum SIP message size in bytes accepted by the parser. |
| `SIP_NONCE_TTL_SEC` | `120` | Digest authentication nonce lifetime in seconds. |
| `SIP_FRAUD_PREFIXES` | built-in IRSF list | Comma-separated E.164 prefixes treated as toll-fraud destinations. Replaces the built-in premium-rate and IRSF prefix list. |
| `SIP_SCANNER_UA_LIST` | Empty | Comma-separated additional User-Agent substrings to reject as SIP scanners, extending the built-in list. |
| `SIP_ALLOW_FOREIGN_CONTACT` | `0` | Set to `1` to permit REGISTER Contact addresses that do not match the source IP or private ranges. Required for legitimate third-party registration. |
| `SIP_ALLOW_PRIVATE_TARGETS` | `0` | Set to `1` to allow routing to private/RFC 1918 target addresses. |

## Production operations

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_TX_LOG` | `0` | Set to `1` to enable per-transaction logging. |
| `SIP_SHUTDOWN_DRAIN_MS` | `5000` | Graceful shutdown drain period in milliseconds before the process exits. |
| `SIP_KEEPALIVE` | `1` | Enable SIP keepalive probes on registered endpoints (`1` enabled, `0` disabled). |
| `SIP_KEEPALIVE_INTERVAL` | `25` | Keepalive probe interval in seconds. |
| `SIP_CLUSTER_CALLS` | `0` | Set to `1` to enable cross-node call routing through the cluster. |
| `SIP_CONN_IDLE_TIMEOUT` | `120` | Idle timeout in seconds for stream (TCP/TLS/WSS) connections. |

## Registration, connection, and transaction bounds

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_TCP_MAX_CONNECTIONS` | `65536` | Per-TCP-worker accepted-connection ceiling; bounded to `1024..1048576`, with excess connections closed before SIP parsing. |
| `SIP_CALL_STATE_CAPACITY` | `262144` | Per-process SIP call/dialog state-record budget; bounded to `16384..1048576`, with new calls rejected at the limit instead of evicting live state. |
| `SIP_T1_MS` | `500` | Base transaction timer. |
| `SIP_T2_MS` | `4000` | Non-INVITE retransmission ceiling. |
| `SIP_TIMER_C_MS` | `180000` | Proxy INVITE timer C bound. |
| `SIP_TIMER_L_MS` | `32000` | Server 2xx retention bound. |
| `SIP_MAX_REG_EXPIRES` | `3600` | Maximum registration expiry in seconds. |
| `SIP_MIN_EXPIRES` | `60` | Minimum accepted registration expiry in seconds. |

| `SIP_CONFIG_FILE` | Empty | Watched path; touching it triggers the documented configuration reload path. |
| `SIP_CRASH_REPORT` | Empty | Optional crash-reporting configuration. |

Cluster INVITE fallback routes only through live `registration_bindings` rows whose `expires_at` and owning-node heartbeat are current. The legacy `registrations` table is not authoritative for active remote routing, so expired contacts fail closed.

## API credentials and live integrations

| Variable | Purpose |
| --- | --- |
| `SIP_CARRIER_API_TOKEN` | Carrier API token for capabilities, billing events, acknowledgement, and CDR reads. |
| `SIP_CONTROL_API_TOKEN` | Control write token for routing, dialplans, and mutable SIP resources. |
| `SIP_CONTROL_API_READ_TOKEN` | Optional read-only control token for status, validation, reads, and resource lists. |
| `SIP_MAF_API_TOKEN` | MAF write credential; also permits MAF reads. Keep separate from all admin, carrier, control, and worker credentials. |
| `SIP_MAF_API_READ_TOKEN` | MAF read-only credential for call and event reads. |
| `SIP_MAF_TENANT` | Tenant namespace bound to this admin process; defaults to `default`. |
| `SIP_MAF_INBOUND_MODE` | Inbound MAF ownership mode. `disabled` (default) preserves normal proxy routing; `control` publishes authenticated initial INVITEs as ringing MAF calls; `route` intercepts INVITEs and requires SDK to route via `calls.route`. |
| `SIP_MAF_DB_URL` | Separate PostgreSQL connection for MAF tables (calls, events, commands). Falls back to `SIP_DB_URL` if not set. Allows MAF state isolation or independent database scaling. |
| `SIP_MAF_CONTACT_URI` | Override the Contact URI used in MAF-generated SIP responses. Defaults to `sip:madis@<SIP_PUBLIC_IP>`. |
| `SIP_MAF_COMMAND_TIMEOUT_SECS` | Stale `processing` command timeout before worker recovery. Defaults to `30`, clamped 5–3600. |
| `SIP_MAF_COMMAND_MAX_ATTEMPTS` | Maximum processing attempts before a stale command is failed with `processing_timeout`. Defaults to `3`, clamped 1–10. |
| `SIP_APP_URL`, `SIP_APP_TOKEN` | Optional signed live SIP application endpoint. Both must be configured to enable it. |
| `SIP_APP_CA` | CA bundle for the application endpoint. |
| `SIP_APP_TIMEOUT_MS` | Application decision timeout, clamped to 10–1000 ms. |
| `SIP_APP_FAIL_MODE` | `open` preserves local SIP behavior when the optional app is unavailable; `closed` returns a failure instead. |
| `SIP_APP_ALLOW_HTTP` | Explicit opt-in for plain HTTP in a protected lab network. |
| `SIP_MODULE_URL`, `SIP_MODULE_TOKEN` | Optional signed dispatcher for TTS, STT, LLM, media, recording, fraud, and billing operations. |
| `SIP_MODULE_CA` | CA bundle for the module dispatcher. |
| `SIP_MODULES` | Comma-separated module allowlist, for example `tts,stt,llm,media,recording`. |
| `SIP_MODULE_ALLOW_CUSTOM=1` | Permit custom module names/operations in addition to the built-in allowlist. |
| `SIP_MODULE_TIMEOUT_MS` | Module timeout, clamped to 10–2000 ms. |
| `SIP_MODULE_FAIL_MODE` | `closed` by default; `open` is an explicit availability-over-enforcement policy. |
| `SIP_MODULE_ALLOW_HTTP` | Explicit opt-in for plain HTTP in a protected lab network. |

The live application and module contracts are described in [`modules.md`](modules.md). They are bounded, signed HTTP contracts, not an in-process plugin ABI.

## B2BUA policy

| Variable | Purpose |
| --- | --- |
| `SIP_B2BUA_MODE` | `proxy` by default. Set to `enabled` to allow explicit `b2bua:` routing actions. |
| `SIP_B2BUA_STATE_MS` | In-memory early/confirmed leg lifetime. |
| `SIP_B2BUA_CALLID_HOST` | Host component for generated downstream Call-IDs. |
| `SIP_B2BUA_BIND_IP` | Signaling address advertised on the generated leg. |
| `SIP_B2BUA_SIGNAL_PORT` | Signaling port used in generated Via/Contact values. |
| `SIP_B2BUA_CONTACT_HOST`, `SIP_B2BUA_CONTACT_PORT`, `SIP_B2BUA_CONTACT_USER` | Optional generated Contact overrides. |

B2BUA state is bounded in memory and owned by the SIP worker. The control API changes policy; it does not create an arbitrary call-control program.

## Billing and online charging

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_BILLING_MODE` | `outbox` | `outbox` writes durable billing events; `preauth` enables online authorization; `off` disables billing events. |
| `SIP_BILLING_TENANT` | `default` | Tenant label placed in event envelopes. |
| `SIP_CHARGING_PROTOCOL` | `http` | HTTP adapter or native `diameter` for preauthorization. |
| `SIP_CHARGING_URL` | Empty | HTTPS charging adapter URL for HTTP preauthorization. |
| `SIP_CHARGING_CA` | Empty | CA bundle for the HTTP charging adapter. |
| `SIP_CHARGING_TIMEOUT_MS` | `150` | Bounded charging timeout, clamped to the implementation range. |
| `SIP_CHARGING_FAIL_OPEN=1` | `0` | Explicitly allow an authorization dependency failure to proceed. This trades revenue protection for availability. |

Post-call outbox failures do not change a completed SIP dialog. Initial preauthorization is fail-closed unless `SIP_CHARGING_FAIL_OPEN=1` is explicitly set.

## Emergency calls

| Variable | Purpose |
| --- | --- |
| `SIP_EMERGENCY_TARGET` | SIP URI of the E-CSCF for emergency call routing (e.g., `sip:ecscf.example.com`). Empty = disabled. |
| `SIP_EMERGENCY_NUMBERS` | Comma-separated additional emergency numbers beyond the built-in set (911, 112, 999, 000, 110, 119). Example: `933,988,211`. |

Emergency calls (`urn:service:sos` URIs or configured numbers) bypass SIP authentication and route directly to the E-CSCF per TS 23.167. The MAF SIP inspection endpoint includes `"emergency": true` for detected emergency calls.

## IMS subscriber authorization

Set `SIP_IMS_SUBSCRIBER_URL` to enable the optional fail-closed HTTPS subscriber authorization contract. Configure `SIP_IMS_SUBSCRIBER_TOKEN`, and optionally `SIP_IMS_SUBSCRIBER_CA` and `SIP_IMS_SUBSCRIBER_TIMEOUT_MS`. The URL host must be a DNS name (or `localhost`); certificate verification through the runtime does not match IP-literal hosts against iPAddress SANs. The service owns IMS identities and AKA material; Madis only sends a bounded request and accepts a matching `allow` response. If both this adapter and `SIP_IMS_CX=1` are enabled, both gates must authorize REGISTER. See [`../api/ims-subscriber.md`](../api/ims-subscriber.md).

To use HSS-provided SIP AKA vectors, set `SIP_IMS_CX=1` and `SIP_IMS_AKA=1`. The current implementation uses Cx MAR/MAA and accepts `SIP_IMS_AKA_SCHEME=Digest-AKAv1-MD5` (the default). It fails closed when the HSS is unavailable, keeps only XRES in a short-lived bounded cache, derives the RFC 3310 Digest response, rejects stale or replayed credentials, and requires the subscriber service’s assigned S-CSCF to match the configured server. It does not generate or persist Milenage/TUAK secrets. Enable this only after the selected HSS/UE profile has been interoperability-tested.

For explicit REGISTER and initial-session role behavior, set `SIP_IMS_ROLE=scscf` for local S-CSCF processing (the default), `SIP_IMS_ROLE=pcscf` with `SIP_IMS_PCSCF_NEXT_HOP=sip:icscf.example.com`, or `SIP_IMS_ROLE=icscf` with `SIP_IMS_ICSCF_NEXT_HOP=sip:scscf.example.com`. Set `SIP_IMS_SESSION=1` to require an active REGISTER binding for S-CSCF-originated INVITEs. With `SIP_IMS_CX=1`, I-CSCF uses Cx LIR/LIA for the selected S-CSCF and fails closed if the HSS does not return a valid target. P-/I-CSCF roles forward initial REGISTER and INVITE requests and do not write local registrations; in-dialog requests follow SIP Route/dialog state.

For `SIP_IMS_SESSION=1`, the active-binding requirement applies to both the caller and destination during an initial local S-CSCF INVITE. A missing caller binding returns 403; a missing destination binding returns 404 before charging, application, or contact routing. The default remains `0` for compatibility with non-IMS SIP deployments.

For the opt-in RFC 4028 request boundary, set `SIP_IMS_SESSION_TIMERS=1`. INVITE and UPDATE requests with `Session-Expires` or `Min-SE` are checked for bounded decimal syntax, duplicate headers, supported `refresher=uac|uas` parameters, and configured limits. Successful opted-in INVITE/UPDATE responses receive a negotiated `Session-Expires` header when the downstream response does not provide one. The default minimum is 90 seconds and the default maximum is 86,400 seconds; override them with `SIP_IMS_SESSION_MIN_SE` and `SIP_IMS_SESSION_MAX_SE`. Malformed or out-of-range values return 400; an interval below the effective minimum returns 422 with `Min-SE`. Session-Expires state is bound on dialog (`SIP_IMS_SESSION_REFRESHER=endpoint|proxy`, default endpoint); endpoint refresher traffic remains external. Concurrent re-INVITE offers on the same dialog return 491.

For the opt-in trusted-network identity boundary, set `SIP_IMS_IDENTITY_POLICY=1`. The existing IP-authenticated or loopback source boundary is trusted; `P-Asserted-Identity` and `P-Preferred-Identity` from other sources are removed before forwarding. Trusted peers must supply at most one valid SIP identity, otherwise the request returns 400. `Privacy: id` removes asserted/preferred identity on outbound INVITEs. With `SIP_IMS_ASSERT_IDENTITY=1`, Madis may insert a validated PAI on trusted egress (never under `Privacy: id`).

To advertise one local S-CSCF route after successful REGISTER, set `SIP_IMS_SERVICE_ROUTE=sip:scscf.example.com;lr` (or a validated `sips:` URI). The value is emitted as `Service-Route: <...>` only by the local registrar path; empty or unsafe values are ignored only when unset, while configured invalid values fail REGISTER with 500. Subscriber-profile-derived route sets and third-party registration are not implemented.

For the P-CSCF REGISTER forwarding boundary, set `SIP_IMS_PATH=sip:pcscf.example.com;lr` (or a validated `sips:` URI). The value is emitted as one `Path: <...>` header only when `SIP_IMS_ROLE=pcscf`; any UE-supplied `Path` headers are removed before forwarding. Empty configuration preserves existing behavior, while a configured invalid, list-valued, control-character, or embedded name-addr value returns `500 IMS Path Misconfigured`.

With `SIP_IMS_PATH_DYNAMIC=1`, the P-CSCF mints an opaque flow token, stores `flow → (conn, transport, contact, path base, expiry)` in the worker cache, and inserts `Path` with `;ob;ft=<token>`. Incoming Route tokens and stable TCP/TLS/WS connections refresh the flow; stream close clears the association. `SIP_IMS_FLOW_KEEPALIVE_S` (default 120, clamped 30–3600) bounds flow lifetime refresh. `Require: outbound` is rejected with 420 unless dynamic Path is enabled. Multi-hop profile-derived Path sets remain out of scope.

On the local S-CSCF registrar, Path from REGISTER is durable lifecycle state used for terminating routing. Path is **fail closed** and requires **both**:

1. **Destination pin** — Path equals `SIP_IMS_PATH` exactly, or its host is listed in `SIP_IMS_PATH_HOSTS` (comma-separated hostnames). IP trust alone never accepts an arbitrary Path URI.
2. **Source trust** — REGISTER source is IP-authenticated (`ip_auth`), **or** the explicit lab override `SIP_IMS_ALLOW_UNTRUSTED_PATH=1` is set.

Untrusted or unpinned Path is stripped (not stored); malformed Path fails REGISTER with 400. Restart hydration re-applies the destination pin only (strips unpinned Path from DB rows). Capacity refuses new AORs at `SIP_IMS_LIFECYCLE_CAPACITY` (default 16384, no silent eviction). Load bound: `SIP_IMS_LIFECYCLE_LOAD_LIMIT` (default 10000). AKA vector cache lifetime: `SIP_IMS_AKA_VECTOR_TTL_MS` (default 300000, clamped 1s–1h). AUTS requires a nonce this node issued before re-challenge; free MAR from forged `auts` is rejected.

Associated public identities from the subscriber profile (`associated_uris`, max 8) are stored with the lifecycle and indexed as alias AORs for Path-aware MT lookup. Alias ownership cannot be stolen by a second primary (fail closed). Expired durable rows are deleted on heartbeat cleanup. Optional restart HSS reaffirmation: with `SIP_IMS_CX=1` and `SIP_IMS_LIFECYCLE_HSS_RECONCILE=1`, each hydrated registration issues Cx SAR assignment-type 2; SAR failure drops that AOR’s local registration, lifecycle, and iFC state.

Inbound Cx push (RTR/PPR) is opt-in: set `SIP_IMS_CX=1` and `SIP_IMS_CX_PUSH=1`. The heartbeat polls the **client** peer under the same lock as SAR/MAR. Optionally set `SIP_IMS_CX_PUSH_LISTEN=1` and `SIP_IMS_CX_PUSH_PORT` (default 3868) so the S-CSCF also **listens** for HSS-initiated TLS mTLS connections (`SIP_DIAMETER_SERVER_CERT`/`KEY` or SIP TLS certs, plus `SIP_DIAMETER_SERVER_CLIENT_CA`). Set `SIP_IMS_CX_PUSH_CLIENT_CN` to require an exact client-certificate CN in addition to the CA check. **RTR** force-deregisters lifecycle, aliases, iFC, and contacts (idempotent for unknown users). **PPR** applies a bounded JSON `service_profile` patch (`associated_uris` / `initial_filter_criteria` only); non-JSON or unsafe profile data returns `5004` and does not mutate state. Malformed identities return `5004`.

Diameter client multi-peer: `SIP_DIAMETER_HOSTS=hss1,hss2:3868` rotates preferred peer on open/exchange failure (falls back to `SIP_DIAMETER_HOST` when empty). Entries may carry a realm prefix — `example.com@hss1:3868,example.com@hss2:3868,other.net@hss3:3868` — in which case a request routes to entries pinned to its Destination-Realm (exact match first, wildcard entries otherwise), with failover rotating inside the matching set. The realm is read from the request's own Destination-Realm AVP, and an open peer for a different realm is replaced.

AKA multi-vector: `SIP_IMS_AKA_NUM_VECTORS` (default 1, max 5) requests multiple vectors in one MAR; subsequent challenges consume the local pool before a new MAR.

AKA AUTS resync: when the UE returns `auts=` against a nonce this node issued, Madis burns that vector (consume-once), sends Cx MAR with SIP-Authenticate=RAND and SIP-Authorization=AUTS, installs the new MAA vector pool, and issues a stale 401. Forged AUTS without an issued nonce does not trigger MAR.

 To advertise one local S-CSCF public identity in a successful REGISTER response, set `SIP_IMS_ASSOCIATED_URI=sip:alice@example.com` (or a validated `sips:` URI). The value is emitted as `P-Associated-URI: <...>` only by the local registrar path and is used as a fallback when an authorized subscriber response does not contain `service_profile.associated_uris`. Configured invalid, list-valued, control-character, or embedded name-addr values fail REGISTER with 500. The subscriber profile may instead provide up to eight unique SIP/SIPS identities in `associated_uris`; malformed profile data fails closed before registration state is written. Full TAS behavior and broader standard iFC feature coverage remain external; the bounded profile trigger behavior is documented below.

An authorized subscriber may return `service_profile.initial_filter_criteria` as either (legacy) up to four unique SIP/SIPS target URI strings, or (structured) up to eight objects `{priority, as_uri, default_handling, spt:{method, session_case}}`. Originating/terminating matches are priority-ordered. `default_handling=1` fails closed (503) when no AS accepts the fork; `0` continues to contact routing. Opt-in third-party REGISTER: `SIP_IMS_3PREG=1` — after a successful REGISTER, the S-CSCF originates one best-effort REGISTER per iFC AS target (identity from `SIP_IMS_SERVER_NAME`/`SIP_REALM`) and consumes the responses locally; delivery failures are logged and never block the UE registration. Empty or absent criteria clears the prior trigger; final contact expiry or explicit deregistration also clears the in-memory trigger; malformed criteria rejects REGISTER before registration state is written. TAS/MMTel service logic remains external.

Additional IMS control env:

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_IMS_IRS_DEREG_MODE` | `all` | IRS network dereg: `all` clears whole set; `single` one AOR |
| `SIP_DIAMETER_PEER_BACKOFF_MS` | `5000` | Open-circuit skip after peer failures |
| `SIP_DIAMETER_MAX_INFLIGHT` | `64` | Cap concurrent Diameter exchanges |
| `SIP_IMS_AKA_STORE_KEYS` | `0` | Opaque CK/IK cache (never log secrets) |
| `SIP_IMS_PATH_DYNAMIC` | `0` | P-CSCF flow tokens + dynamic Path |
| `SIP_IMS_FLOW_KEEPALIVE_S` | `120` | Flow lifetime bound |
| `SIP_IMS_3PREG` | `0` | Third-party REGISTER to AS targets |
| `SIP_RTPENGINE_NODES` | empty | Multi-node `host:port,...` control list |
| `SIP_RTPENGINE_FLAGS` | empty | Optional ng policy flags string |
| `SIP_DRAIN` | `0` | Reject new REGISTER/initial INVITE |
| `SIP_IMS_CHARGING_VECTOR` | `0` | Generate/propagate P-Charging-Vector |
| `SIP_IMS_ICID_GEN_ADDR` | origin host | ICID generator address |
| `SIP_IMS_SESSION_REFRESHER` | `endpoint` | `proxy` stores UAS refresher ownership |
| `SIP_IMS_ASSERT_IDENTITY` | `0` | Generate PAI on trusted egress |
| `SIP_TRUSTED_DOMAINS` | *(empty)* | Comma-separated trust domain list for RFC 3325 identity generation and privacy forwarding |
| `SIP_EVENT_PACKAGES` | `0` | Set to `1` to enable RFC 3265/6665 SUBSCRIBE/NOTIFY event package handling |
| `SIP_EVENT_PACKAGE_LIST` | `presence,message-summary` | Comma-separated list of accepted event packages |
| `SIP_EVENT_MAX_EXPIRES` | `3600` | Maximum subscription expiry in seconds |
| `SIP_TLS_REUSE` | `0` | Set to `1` to enable RFC 5923 inbound TLS connection reuse via Via `;alias` |
| `SIP_OUTBOUND` | `0` | Set to `1` to enable RFC 5626 outbound flow tokens (`+sip.instance`, `reg-id`, flow token Path URI) |
| `STIR_SHAKEN_IAT_MAX_AGE` | `60` | Maximum age in seconds for PASSporT `iat` freshness validation |
| `SIP_IMS_IPSEC_EXPORT` | `0` | Export SA JSON for external IPsec (requires store-keys) |
| `SIP_IMS_IPSEC_SPI_BASE` | `1000` | Base SPI for exported SA pair |
| `SIP_IMS_IPSEC_PORT_C` / `PORT_S` | `5060` / `5061` | Client/server protected ports |
| `SIP_IMS_RX` | `0` | Enable Rx AAR authorize on INVITE (needs PCRF peer) |
| `SIP_IMS_RX_AF_APP_ID` | `madis.voice` | AF-Application-Identifier |
| `SIP_IMS_RX_DEST_HOST` | empty | Optional PCRF Diameter host AVP |
| `SIP_RTPENGINE_PROFILE` | empty | `plain`, `ice`, `srtp`, `ice-srtp`, `webrtc`, `dtls-srtp` |

With `SIP_IMS_CX=1`, the HSS UAA must return a `Server-Name` exactly matching `SIP_IMS_SERVER_NAME`; missing or mismatched assignment fails REGISTER before SAR and no local binding is written.

Cx SAR receives `REGISTRATION` for a new binding, `RE_REGISTRATION` for a refresh of an active binding, and `USER_DEREGISTRATION` for `Contact: *` or an explicit `expires=0` removal. Mixed or malformed Contact lists remain subject to the normal SIP validation path.

PRACK and UPDATE are forwarded only for an existing early or confirmed dialog. Forked early dialogs use the response To-tag to select the matching downstream target. Madis validates PRACK against tracked RSeq/RAck state, but does not generate reliable provisional responses or claim endpoint-level conformance.

## Diameter and IMS

Diameter credit control uses the following settings as applicable:

`SIP_DIAMETER_HOST`, `SIP_DIAMETER_PORT`, `SIP_DIAMETER_TLS`, `SIP_DIAMETER_CA`, `SIP_DIAMETER_CLIENT_CERT`, `SIP_DIAMETER_CLIENT_KEY`, `SIP_DIAMETER_TRANSPORT`, `SIP_DIAMETER_ALLOW_PLAINTEXT`, `SIP_DIAMETER_PERSISTENT`, `SIP_DIAMETER_TIMEOUT_MS`, `SIP_DIAMETER_ORIGIN_HOST`, `SIP_DIAMETER_ORIGIN_REALM`, `SIP_DIAMETER_DEST_REALM`, `SIP_DIAMETER_SERVICE_CONTEXT`, `SIP_DIAMETER_SERVICE_ID`, `SIP_DIAMETER_SUBSCRIPTION_TYPE`, and `SIP_DIAMETER_REQUESTED_ACTION`/`SIP_DIAMETER_REQUESTED_SECONDS`.

TLS is the normal transport. Plain TCP or externally protected SCTP requires explicit deployment configuration. `SIP_IMS_CX=1` enables fail-closed Cx UAR/SAR authorization for REGISTER; set the corresponding `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and `SIP_IMS_DEST_HOST` values. See [`../api/diameter.md`](../api/diameter.md) and [`../api/ims-diameter.md`](../api/ims-diameter.md).

## RTP media sidecar

Madis can send bounded RTPEngine-ng `offer`, `answer`, and `delete` commands
to an external media relay. The SIP worker owns signaling and SDP hook
processing; RTP, RTCP, ICE, DTLS-SRTP, codecs, recording, and media policy
remain in the external system. Database configuration uses
`rtpengine_enabled`, `rtpengine_host`, and `rtpengine_port`.

For a standalone worker or a controlled lab override, use:

| Variable | Purpose |
| --- | --- |
| `SIP_RTPENGINE_ENABLED` | Explicit `1`, `true`, or `yes` enables; any other non-empty value disables. |
| `SIP_RTPENGINE_HOST` | RTPEngine-ng control host, bounded to 512 characters. |
| `SIP_RTPENGINE_PORT` | RTPEngine-ng UDP control port; invalid values fall back to `2223`. |
| `SIP_RTPENGINE_NODES` | Optional multi-node list `host:port,...`; hash(call-id) selection with failover. |
| `SIP_RTPENGINE_DEBUG` | `0` | Set to `1` to log ng exchange failures/rejections and answer-gate drops. |
| `SIP_RTPENGINE_FLAGS` | Optional policy flags string passed on offer (ICE/SRTP etc. remain media-side). |

Environment values override the corresponding database values for that
worker. The control protocol has no authentication layer, so bind the relay
and worker to a private network and restrict the control source allow-list.
See [`../media/README.md`](../media/README.md) for the bundled lab sidecar
and its unsupported media features.

## STIR/SHAKEN

The implementation exposes configuration for the STIR/SHAKEN verification/signing path, including `STIR_SHAKEN_ENABLED`, `STIR_SHAKEN_MODE`, `STIR_SHAKEN_ATTESTATION`, `STIR_SHAKEN_CERT_URL`, `STIR_SHAKEN_PRIVATE_KEY`, `STIR_SHAKEN_PUBLIC_KEY`, `STIR_SHAKEN_SECRET`, `STIR_SHAKEN_JWKS`, and `STIR_SHAKEN_JWKS_URL`. Review certificate custody, attestation policy, and carrier interoperability before enabling it.

## Reload and secret handling

Configuration changes generally require restarting the affected process. The watched `SIP_CONFIG_FILE` path is the supported trigger for a worker reload; verify `/readyz`, logs, and a representative OPTIONS/REGISTER/INVITE flow afterward.

Do not commit database URLs, passwords, private keys, bearer tokens, or
environment-specific IP addresses and private hostnames. Restrict
`/etc/madis/madis.env`, use a secret manager where available, and keep the
worker and WebUI listeners on private interfaces unless an authenticated
reverse proxy and firewall policy are in place.
## HEPv3 capture

HEP export is disabled by default. When enabled, each validated inbound SIP
message is encoded as a bounded HEPv3 packet and sent best-effort over UDP to
the configured collector. Capture errors are dropped and do not alter SIP
responses or transaction handling.

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_HEP_ENABLE` | `0` | Set to `1`, `true`, or `yes` to enable capture. |
| `SIP_HEP_HOST` | Empty | HEP collector hostname or IP. Empty disables sending. |
| `SIP_HEP_PORT` | `9060` | HEP UDP destination port, bounded to `1..65535`. |
| `SIP_HEP_LOCAL_IP` | `SIP_PUBLIC_IP` or configured local address | Local address encoded in HEP metadata. Current exporter requires IPv4 metadata. |
| `SIP_HEP_CAPTURE_ID` | `1` | HEP capture-agent ID, bounded to `0..65535`. |
| `SIP_HEP_MAX_PAYLOAD` | `60000` | Maximum SIP payload bytes exported per packet. |
| `SIP_HEP_QUEUE_CAPACITY` | `8192` | Per-process bounded HEP wire-packet queue; clamped `256..65536`. Full queues drop HEP capture only. |

The exporter uses one detached worker and one process-local UDP socket. SIP ingress only encodes and non-blockingly enqueues bounded wire packets; it does not wait for collector I/O.
A full queue, socket error, or collector outage drops HEP capture only and
does not change SIP responses or transaction handling. There are no retries or
collector acknowledgements, so HEP is not durable recording. Use a local or
nearby collector and scale collectors independently.
