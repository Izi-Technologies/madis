# Operations

## Linux installation

The installer supports Debian/Ubuntu and RHEL-family distributions. It installs or prepares PostgreSQL, compiler and native dependencies, the SIP worker, optional standalone WebUI, systemd units, log rotation, firewall entries, and the `madis`/`madisctl` CLI aliases.

```sh
sudo ./install.sh
madis status
madis health
madis webui
```

The installer writes `/etc/madis/madis.env`, normally installs under `/opt/madis`, and creates `madis.service` and `madis-admin.service` when the admin binary is available. It generates database, admin, carrier API, control API, application, module, and WebUI credentials if they were not provided. Store and protect the generated values; the environment file contains secrets.

Useful installer overrides include:

```sh
sudo MADIS_DB_NAME=mysipdb \
  MADIS_SIP_PORT=5080 \
  MADIS_ADMIN_PORT=8080 \
  ./install.sh
```

Mako 0.5.0 is required. For an offline or prebuilt install, place `main` and `admin-bin` beside the installer. Otherwise provide `MADIS_MAKO_BIN` and `MAKO_RUNTIME` so the installer can build the processes.

## Docker

The compose file starts the SIP worker and PostgreSQL:

```sh
: "${MADIS_DB_PASS:?set via secret manager}" \
: "${MADIS_ADMIN_TOKEN:?set via secret manager}" \
: "${MADIS_CARRIER_API_TOKEN:?set via secret manager}" \
: "${MADIS_CONTROL_API_TOKEN:?set via secret manager}" \
: "${MADIS_CONTROL_API_READ_TOKEN:?set via secret manager}" \
docker compose up -d --build
```

The default container publishes UDP/TCP 5060, TLS 5061, WSS 8443, and the worker HTTP port 8080. PostgreSQL is bound to loopback by the compose file. The defaults are for local testing; replace all secrets and put any public WebUI behind a TLS reverse proxy.

The container does not start `madis-admin.service`. Build and run `admin/main.mko` separately when browser administration is required. Keep `SIP_APP_URL` and `SIP_MODULE_URL` empty until the external services are configured and their signing/timeout policy is verified.

Verify the worker:

```sh
curl -fsS http://localhost:8080/readyz
curl -fsS http://localhost:8080/healthz
docker compose ps
docker compose logs --tail=100 madis
```

## Service management

```sh
sudo systemctl status madis madis-admin
sudo systemctl restart madis madis-admin
sudo journalctl -u madis -u madis-admin -n 100 --no-pager

madis status
madis health
madis logs sip
madis logs admin
```

The worker’s local HTTP endpoints are `/healthz`, `/readyz`, `/metrics`, `/state`, and `POST /reload` on `SIP_ADMIN_PORT`. The WebUI is normally at `/admin/login`; its machine API is `/admin/api/v1/` on `ADMIN_PORT`. Do not assume either listener is safe to publish without reviewing its token, bind address, firewall, and reverse-proxy policy.

## Reverse proxy

Terminate public HTTPS and browser WebSocket traffic in nginx, Caddy, HAProxy, or an equivalent edge. Forward the WebUI to `ADMIN_BIND`/`ADMIN_PORT` and preserve:

- `Host` and `Origin` for browser request validation.
- `Upgrade` and `Connection` for `/admin/ws/live`.
- The original scheme/host headers if the proxy uses secure cookies or redirects.

Keep the admin process loopback-bound unless a private network and explicit identity policy protect it. SIP WSS is a signaling listener on `SIP_WSS_PORT`; its certificate and public host must match the SIP/WebRTC client’s trust and SNI expectations. RTP, ICE, and DTLS-SRTP still require a separate media system.

## Configuration changes

1. Back up `/etc/madis/madis.env` and any affected PostgreSQL data.
2. Change the environment or database setting using the documented interface.
3. Restart the affected process for environment changes.
4. For the worker’s watched configuration path, touch `SIP_CONFIG_FILE` or use the local reload endpoint according to the deployment policy.
5. Check `/readyz`, recent logs, and an authenticated OPTIONS/REGISTER/representative INVITE flow.

Do not put passwords, private keys, bearer tokens, database URLs,
environment-specific IP addresses, or private hostnames in Git. Use file
permissions and a secret manager where available; documentation examples must
use placeholders or environment-provided values.

## Reload and cache flush

`POST /reload` on the worker HTTP port increments the configuration epoch and
flushes the in-memory ban, ACL, whitelist, IP-auth, fraud-prefix, and
rate-limit caches. The next lookup for each category re-queries the database,
so security policy changes take effect immediately without a full restart.

## Metrics

`/metrics` exposes Prometheus-format counters and gauges. Labeled metrics
include:

- `madis_sip_requests_total{method,transport}` — per-method, per-transport request counts.
- `madis_sip_responses_total{code,class}` — per-status-code response counts with class label (e.g. `2xx`).
- `madis_sip_connections_total{transport}` — gauge of active stream connections by transport.

The labeled counters supplement the fixed metric slots (backward-compatible);
both are emitted in every `/metrics` scrape.

## Graceful shutdown

On `SIGTERM` the worker stops accepting new connections and enters a drain
period controlled by `SIP_SHUTDOWN_DRAIN_MS` (default 5000, clamped
0–30000 ms). During drain the worker continues flushing transactions and
cleaning registrations. If the active call count reaches zero before the timer
expires, drain exits early. After drain the worker begins server shutdown.

## Registration keepalive

`SIP_KEEPALIVE=1` (default) enables periodic OPTIONS keepalive probes to
registered contacts. `SIP_KEEPALIVE_INTERVAL` sets the probe interval in
seconds (default 25). Disable with `SIP_KEEPALIVE=0` when a downstream
keepalive mechanism already exists.

## Cluster call state

When `SIP_CLUSTER_CALLS=1` the worker periodically syncs its active call map
to a shared `cluster_calls` PostgreSQL table keyed by `(call_id, node_id)`.
Each row stores `dialog_dst`, `transport`, `from_tag`, `to_tag`, and
`confirmed_at`. On BYE, if the owning node is unreachable, a sibling can look
up the dialog destination from the table and attempt failover delivery. Stale
rows (>30 s without refresh) are pruned automatically; node-specific rows are
removed on clean shutdown.

## API operations

The machine API is at `/admin/api/v1/` and uses separate bearer scopes:

- Carrier token: capabilities, billing event outbox, acknowledgements, and CDR reads.
- Control read token: status, validation, and non-mutating policy/resource reads.
- Control write token: all control writes, including routing, dialplans, gateways, dispatch sets, DIDs, access control, ANI ranges, and header rules. Security bans are currently listed and created/upserted by source IP; the generic numeric-ID update/delete/state routes do not apply to them.

List calls are capped at 100 records and JSON bodies at 64 KiB. Billing consumers must commit before acknowledgement. Resource updates should use the returned `revision`/`expected_revision` mechanism when multiple writers exist. See [`../api/README.md`](../api/README.md).

## Upgrade and rollback

Build and test the exact source revision with Mako 0.5.0 before replacing the live processes:

```sh
MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko /tmp/madis

MAKO_BIN=/path/to/mako MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh admin/main.mko /tmp/madis-admin
```

Before an upgrade, save the current binaries, environment file, unit files, and a tested PostgreSQL backup. Replace binaries atomically, restart one service at a time where the topology allows, and verify readiness plus a representative SIP transaction. If checks fail, restore the previous binaries and restart. Database migrations require their own tested rollback or restore plan; the repository does not provide automatic zero-downtime migration rollback.

## Incident checklist

When traffic fails, check in this order:

1. `systemctl is-active madis madis-admin` and the last 100 log lines.
2. Listener bindings, firewall/security-group rules, and reverse-proxy upstream health.
3. Local `/readyz`, `/healthz`, `/state`, and `/metrics` responses.
4. PostgreSQL reachability and authentication errors.
5. SIP DNS NAPTR/SRV results, certificate names, and outbound CA configuration.
6. Registration expiry, gateways/routes/dispatch records, and transaction traces.
7. Charging/Diameter peer health and request/answer correlation when preauthorization is enabled.
8. Application/module endpoint latency, signature failures, and configured fail mode.

Do not “fix” a Diameter incident by disabling TLS verification or enabling plaintext globally. Any explicit lab override should be recorded in the incident and deployment change record.

## Security baseline

- Run both services as a dedicated non-login `madis` user.
- Keep the WebUI, worker HTTP port, and PostgreSQL off public interfaces unless a reviewed reverse proxy/network policy requires otherwise.
- Use operator-managed certificates and verified CA bundles for outbound TLS/WSS/Diameter/application/module calls.
- Rotate admin/API credentials and database passwords.
- Allow only the SIP ports and proxy paths required by the deployment.
- Back up PostgreSQL and test restoration.
- Monitor memory, file descriptors, transaction/dialog cache high-water marks, failed authentication, integration latency, and outbound association churn.
- Treat local tests and RFC gates as regression evidence, not security certification.
