# Madis SIP Proxy

A high-performance SIP proxy and registrar written in [Mako](https://github.com/mako-lang), designed for production VoIP infrastructure.

## About

Madis is a modular SIP proxy that handles call routing, registration, authentication, NAT traversal, and media relay integration. It is built from the ground up for reliability, RFC compliance, and operational visibility.

### Key Features

- **SIP Proxy & Registrar** — Full RFC 3261 proxy and registrar with multi-contact bindings, per-contact expiry, and database-backed persistence.
- **Digest Authentication** — MD5 and SHA-256 digest auth with `auth`, `auth-int`, and `-sess` variants. Short-lived nonces with replay protection.
- **STIR/SHAKEN** — ECDSA P-256 (ES256) call identity signing and verification for caller ID attestation.
- **NAT Traversal** — Automatic `received`/`rport` handling per RFC 3581 with symmetric response routing.
- **RTPEngine Integration** — Media relay control for calls traversing NAT boundaries.
- **Multi-Transport** — UDP, TCP, TLS, and WebSocket ingress with connection pooling, idle management, and per-transport routing.
- **IPv6** — Dual-stack support with separate v6-only UDP listener and bracketed address parsing.
- **DNS Resolution** — RFC 3263 NAPTR/SRV resolution with priority/weight ordering, failover, and 60-second caching.
- **Dialplan Engine** — Configurable call routing rules with pattern matching and rewriting.
- **Forking & Transactions** — Full client/server transaction state machines with fork handling, 6xx cancellation, Timer A–J support, and retransmission.
- **Operational Control Plane** — HTTP admin endpoints for health checks, readiness, Prometheus metrics, state inspection, and live configuration reload.
- **Security Hardening** — 64 KiB message limits, 128-header cap, control-character rejection, and input validation before any database interaction.

## Project Structure

| Module | Purpose |
|---|---|
| `main.mko` | Entry point — pulls all modules into the proxy namespace |
| `parser.mko` | SIP message parsing and URI extraction |
| `headers.mko` | Header manipulation, compact-header support, validation |
| `auth.mko` | Digest authentication and credential verification |
| `registration.mko` | REGISTER handling, contact bindings, expiry management |
| `routing.mko` | Request routing, loose routing, Record-Route |
| `dialplan.mko` | Dial plan rules and number rewriting |
| `nat.mko` | NAT detection and `rport`/`received` processing |
| `transport.mko` | TCP, TLS, UDP, and WebSocket transport layer |
| `stream.mko` | Stream-based transport framing |
| `rtpengine.mko` | RTPEngine media relay integration |
| `shaken.mko` | STIR/SHAKEN identity signing and verification |
| `security.mko` | Input validation and security checks |
| `rfc.mko` | RFC compliance enforcement |
| `db.mko` | Database access layer |
| `log.mko` | Structured logging |
| `ops.mko` | Admin HTTP endpoints and operational tooling |

## Requirements

- **Mako 0.4.5** compiler and runtime

## Building

```sh
MAKO_RUNTIME=/path/to/mako/runtime mako build --release --strip --no-incremental main.mko -o madis
```

## Verification

```sh
# Type-check
MAKO_RUNTIME=/path/to/mako/runtime mako check --no-incremental main.mko

# Lint
MAKO_RUNTIME=/path/to/mako/runtime mako lint main.mko

# Run tests
MAKO_RUNTIME=/path/to/mako/runtime mako test tests
```

## Configuration

Madis is configured through environment variables:

| Variable | Description |
|---|---|
| `SIP_ADMIN_PORT` | Enable the HTTP control plane on this port |
| `SIP_ADMIN_TOKEN` | Bearer token for admin endpoint authentication |
| `SIP_CONFIG_FILE` | Watched file path for triggering configuration reload |
| `SIP_IPV6` | Set to `1` (default) to enable IPv6 UDP, `0` to disable |

## License

This project is licensed under the [MIT License](LICENSE).
