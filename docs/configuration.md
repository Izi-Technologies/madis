# Configuration

Madis reads environment variables at process start. The installer writes them to `/etc/madis/madis.env`; Docker supplies them through `docker-compose.yml`; a source run can export them in the shell or use a process manager’s environment file.

The SIP worker and standalone WebUI are separate processes. `SIP_ADMIN_PORT` is the worker’s local health/metrics HTTP port. `ADMIN_PORT` is the WebUI port. Keep them different when both processes run on one host.

## Minimal host configuration

```sh
SIP_DB_URL=postgres://madis:password@127.0.0.1:5432/madis
SIP_BIND_IP=0.0.0.0
SIP_UDP_PORT=5060
SIP_TLS_PORT=5061
SIP_WSS_PORT=8443
SIP_REALM=example.net
SIP_NODE_ID=edge-1

# Worker-local HTTP surface; do not publish this as the WebUI.
SIP_ADMIN_PORT=9090
SIP_METRICS_HOST=127.0.0.1
SIP_METRICS_PORT=9090

# Standalone WebUI.
ADMIN_BIND=127.0.0.1
ADMIN_PORT=8080
ADMIN_SECURE_COOKIE=1

SIP_ADMIN_TOKEN=worker-health-token
SIP_CARRIER_API_TOKEN=carrier-machine-token
SIP_CONTROL_API_TOKEN=control-write-token
SIP_CONTROL_API_READ_TOKEN=control-read-token
```

Use long, random values for every token. The installer generates these credentials when they are not supplied and writes the result to the protected environment file.

## SIP listeners and identity

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_BIND_IP` | Host-dependent | Local signaling bind address. |
| `SIP_PUBLIC_IP` | Empty/auto-detected by installer | Address advertised in SIP/SDP-facing values when the host is behind NAT. |
| `SIP_PUBLIC_HOST` | Empty | Public host identity used by deployment-specific checks and generated signaling values. |
| `SIP_UDP_PORT` | `5060` | UDP signaling listener. |
| `SIP_TLS_PORT` | `5061` | SIP over TLS listener. |
| `SIP_WSS_PORT` | `8443` | Secure WebSocket SIP listener. |
| `SIP_IPV6` | `1` | Enable IPv6 listeners where the host supports them. |
| `SIP_REALM` | `madis.local` | Digest authentication realm. |
| `SIP_DOMAIN` / `SIP_FQDN` | Empty | Domain identity fallbacks. |
| `SIP_NODE_ID` | `node1` | Node identity used in registration and cluster metadata. |
| `SIP_NODE_ADDR` | `127.0.0.1` | Node address metadata. |
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
| `SIP_METRICS_HOST` | `127.0.0.1` | Worker host targeted by the WebUI. |
| `SIP_METRICS_PORT` | `9090` in the installer layout | Worker port targeted by the WebUI. |
| `ADMIN_BIND` | `127.0.0.1` | Standalone WebUI bind address. |
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

## Worker, registration, and transaction bounds

| Variable | Default | Purpose |
| --- | --- | --- |
| `SIP_UDP_WORKERS` | `1` | UDP listener worker count. |
| `SIP_TCP_WORKERS` | `1` | Stream listener worker count. |
| `SIP_SCHED_WORKERS` | `0` | Bounded Mako scheduler pool; `0` keeps the default per-kick threading behavior. |
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

## IMS subscriber authorization

Set `SIP_IMS_SUBSCRIBER_URL` to enable the optional fail-closed HTTPS subscriber authorization contract. Configure `SIP_IMS_SUBSCRIBER_TOKEN`, and optionally `SIP_IMS_SUBSCRIBER_CA` and `SIP_IMS_SUBSCRIBER_TIMEOUT_MS`. The service owns IMS identities and AKA material; Madis only sends a bounded request and accepts a matching `allow` response. If both this adapter and `SIP_IMS_CX=1` are enabled, both gates must authorize REGISTER. See [`../api/ims-subscriber.md`](../api/ims-subscriber.md).

To use HSS-provided SIP AKA vectors, set `SIP_IMS_CX=1` and `SIP_IMS_AKA=1`. The current implementation uses Cx MAR/MAA and accepts `SIP_IMS_AKA_SCHEME=Digest-AKAv1-MD5` (the default). It fails closed when the HSS is unavailable, keeps only XRES in a short-lived bounded cache, derives the RFC 3310 Digest response, rejects stale or replayed credentials, and requires the subscriber service’s assigned S-CSCF to match the configured server. It does not generate or persist Milenage/TUAK secrets. Enable this only after the selected HSS/UE profile has been interoperability-tested.

For explicit REGISTER and initial-session role behavior, set `SIP_IMS_ROLE=scscf` for local S-CSCF processing (the default), `SIP_IMS_ROLE=pcscf` with `SIP_IMS_PCSCF_NEXT_HOP=sip:icscf.example.com`, or `SIP_IMS_ROLE=icscf` with `SIP_IMS_ICSCF_NEXT_HOP=sip:scscf.example.com`. Set `SIP_IMS_SESSION=1` to require an active REGISTER binding for S-CSCF-originated INVITEs. With `SIP_IMS_CX=1`, I-CSCF uses Cx LIR/LIA for the selected S-CSCF and fails closed if the HSS does not return a valid target. P-/I-CSCF roles forward initial REGISTER and INVITE requests and do not write local registrations; in-dialog requests follow SIP Route/dialog state.

For `SIP_IMS_SESSION=1`, the active-binding requirement applies to both the caller and destination during an initial local S-CSCF INVITE. A missing caller binding returns 403; a missing destination binding returns 404 before charging, application, or contact routing. The default remains `0` for compatibility with non-IMS SIP deployments.

With `SIP_IMS_CX=1`, the HSS UAA must return a `Server-Name` exactly matching `SIP_IMS_SERVER_NAME`; missing or mismatched assignment fails REGISTER before SAR and no local binding is written.

Cx SAR receives `REGISTRATION` for a new binding, `RE_REGISTRATION` for a refresh of an active binding, and `USER_DEREGISTRATION` for `Contact: *` or an explicit `expires=0` removal. Mixed or malformed Contact lists remain subject to the normal SIP validation path.

PRACK and UPDATE are forwarded only for an existing early or confirmed dialog. Forked early dialogs use the response To-tag to select the matching downstream target. Madis validates PRACK against tracked RSeq/RAck state, but does not generate reliable provisional responses or claim endpoint-level conformance.

## Diameter and IMS

Diameter credit control uses the following settings as applicable:

`SIP_DIAMETER_HOST`, `SIP_DIAMETER_PORT`, `SIP_DIAMETER_TLS`, `SIP_DIAMETER_CA`, `SIP_DIAMETER_CLIENT_CERT`, `SIP_DIAMETER_CLIENT_KEY`, `SIP_DIAMETER_TRANSPORT`, `SIP_DIAMETER_ALLOW_PLAINTEXT`, `SIP_DIAMETER_PERSISTENT`, `SIP_DIAMETER_TIMEOUT_MS`, `SIP_DIAMETER_ORIGIN_HOST`, `SIP_DIAMETER_ORIGIN_REALM`, `SIP_DIAMETER_DEST_REALM`, `SIP_DIAMETER_SERVICE_CONTEXT`, `SIP_DIAMETER_SERVICE_ID`, `SIP_DIAMETER_SUBSCRIPTION_TYPE`, and `SIP_DIAMETER_REQUESTED_ACTION`/`SIP_DIAMETER_REQUESTED_SECONDS`.

TLS is the normal transport. Plain TCP or externally protected SCTP requires explicit deployment configuration. `SIP_IMS_CX=1` enables fail-closed Cx UAR/SAR authorization for REGISTER; set the corresponding `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and `SIP_IMS_DEST_HOST` values. See [`../api/diameter.md`](../api/diameter.md) and [`../api/ims-diameter.md`](../api/ims-diameter.md).

## STIR/SHAKEN

The implementation exposes configuration for the STIR/SHAKEN verification/signing path, including `STIR_SHAKEN_ENABLED`, `STIR_SHAKEN_MODE`, `STIR_SHAKEN_ATTESTATION`, `STIR_SHAKEN_CERT_URL`, `STIR_SHAKEN_PRIVATE_KEY`, `STIR_SHAKEN_PUBLIC_KEY`, `STIR_SHAKEN_SECRET`, `STIR_SHAKEN_JWKS`, and `STIR_SHAKEN_JWKS_URL`. Review certificate custody, attestation policy, and carrier interoperability before enabling it.

## Reload and secret handling

Configuration changes generally require restarting the affected process. The watched `SIP_CONFIG_FILE` path is the supported trigger for a worker reload; verify `/readyz`, logs, and a representative OPTIONS/REGISTER/INVITE flow afterward.

Do not commit database URLs, passwords, private keys, or bearer tokens. Restrict `/etc/madis/madis.env`, use a secret manager where available, and keep the worker and WebUI listeners on private interfaces unless an authenticated reverse proxy and firewall policy are in place.
