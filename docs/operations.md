# Operations

## Install on Linux

The installer supports Debian/Ubuntu and RHEL-family distributions. It needs
root and installs PostgreSQL, a C compiler, OpenSSL/libpq development files,
systemd units, log rotation, the SIP worker, the WebUI, and the `madis` CLI.

```sh
sudo ./install.sh
madis status
madis health
madis webui
```

The installer requires Mako 0.4.16 when it builds from source. Set
`MADIS_MAKO_BIN` and `MAKO_RUNTIME` when the compiler is not on the default
path, or place prebuilt `main` and `admin-bin` beside the installer for an
offline package. Confirm the compiler reports 0.4.16; do not mix a different
runtime with generated C.

The installer creates `/etc/madis/madis.env`, `/opt/madis` by default, and the
units `madis.service` and `madis-admin.service`. Save the generated database,
admin, carrier API, and WebUI credentials securely; the installer prints them
once and stores them in the protected environment file.

## Docker

```sh
MADIS_DB_PASS='long-random-password' \
MADIS_ADMIN_TOKEN='long-random-admin-token' \
MADIS_CARRIER_API_TOKEN='long-random-carrier-token' \
docker compose up -d --build
```

The compose file publishes SIP UDP/TCP 5060, TLS 5061, WSS 8443, and the SIP
worker's internal HTTP port 8080. Its default values are suitable for a local
test only. Change
the secrets and put the WebUI behind a reverse proxy before using a shared or
public host. PostgreSQL is bound to loopback by compose. The current Docker
image does not start `madis-admin.service`; use the installer or build/run
`admin-bin` separately for the browser WebUI.

Verify the container:

```sh
curl -fsS http://127.0.0.1:8080/readyz
curl -fsS http://127.0.0.1:8080/healthz
docker compose ps
docker compose logs --tail=100 madis
```

## Service management

```sh
sudo systemctl status madis madis-admin
sudo systemctl restart madis madis-admin
sudo journalctl -u madis -u madis-admin -n 100 --no-pager
madis status
madis logs sip
madis logs admin
```

The SIP worker's local endpoints are `/healthz`, `/readyz`, `/metrics`,
`/state`, and `POST /reload`. The standalone WebUI is normally at
`/admin/login`; its machine API is under `/admin/api/v1/`. Authentication and
binding depend on the chosen layout, so do not assume that a health endpoint
is public or that it is safe to expose without a reverse proxy.

## Reverse proxy

Terminate public HTTPS and browser WebSocket traffic in nginx, Caddy, HAProxy,
or the carrier's existing edge. Forward the WebUI to `ADMIN_BIND`/`ADMIN_PORT`
and preserve the `Host`, `Origin`, and `Upgrade` headers needed by the login,
HTMX, and live-dashboard paths. Keep the admin service loopback-bound unless a
separate firewall and identity policy protect it.

SIP WSS on `SIP_WSS_PORT` is a SIP signaling listener. Its TLS certificate and
proxying must match the WebRTC/SIP endpoint's trust and hostname expectations.
Media still needs the selected RTP/ICE/DTLS-SRTP system.

## Configuration changes

1. Back up `/etc/madis/madis.env` and any affected database rows.
2. Edit the environment or the WebUI-managed database setting.
3. Restart the affected service for environment changes.
4. Use `POST /reload` or touch `SIP_CONFIG_FILE` only for the documented cache
   invalidation path.
5. Check `/readyz`, logs, and one authenticated SIP OPTIONS/REGISTER flow.

Do not put passwords, private keys, bearer tokens, or database URLs in Git.
Use file permissions, a secret manager, or the host's service credential store.

## Upgrade and rollback

Build and test the exact source revision with Mako 0.4.16 before installing it:

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh main.mko /tmp/madis
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/build-native.sh admin/main.mko /tmp/madis-admin
```

Before replacing a live binary, save the current binaries, environment file,
unit files, and database backup. Install the new binaries atomically, restart
one service at a time when the topology permits it, and verify readiness and a
real SIP transaction. If the checks fail, restore the previous binaries and
restart; database changes require a tested migration rollback or restore plan.

The repository does not provide zero-downtime rolling orchestration or an
automatic database rollback. Those are deployment responsibilities.

## Health and incident checklist

When traffic fails, check in this order:

1. `systemctl is-active` for both services and the last 100 log lines.
2. Listener bindings with `ss -ltnup` and firewall/security-group rules.
3. `/readyz`, `/healthz`, `/state`, and `/metrics` locally.
4. PostgreSQL reachability and database connection errors.
5. SIP DNS NAPTR/SRV results, certificate names, and outbound CA settings.
6. Registration expiry, routing/dispatch records, and transaction traces in
   the WebUI.
7. Carrier charging/Diameter peer logs and request/answer correlation.

Avoid turning on plaintext Diameter or disabling TLS verification as a generic
fix. Those settings are explicit lab or network-protection overrides and must
be documented in the incident record.

## Security baseline

- Run both services as the dedicated non-login `madis` user.
- Keep WebUI/admin and PostgreSQL off the public interface.
- Use operator-managed TLS certificates and a trusted CA for outbound peers.
- Rotate admin/API credentials and database passwords.
- Restrict firewall rules to the SIP and reverse-proxy ports actually needed.
- Back up PostgreSQL and test restoration.
- Monitor memory, file descriptors, transaction-cache high-water marks, failed
  authentication, and outbound association churn.
- Treat the RFC gate as regression evidence, not as a security certification.
