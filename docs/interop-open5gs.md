# Open5GS / external HSS interop runbook

Madis owns CSCF signaling and durable registration lifecycle. AKA secrets,
Milenage/TUAK, and HSS storage remain external. This runbook describes how to
wire Madis against Open5GS (or another Cx HSS) for lab evidence.

## Prerequisites

- Madis built from this repository (`mako` 0.5.0 matching runtime).
- Open5GS HSS (or lab HSS) with Cx TLS peer configuration.
- Operator-provided certificates; no hardcoded hosts or secrets.

## Madis environment (example)

```sh
export SIP_IMS_CX=1
export SIP_IMS_AKA=1
export SIP_IMS_ROLE=scscf
export SIP_IMS_SERVER_NAME=sip:scscf.example.com
export SIP_IMS_VISITED_NETWORK=example.com
export SIP_DIAMETER_HOSTS=hss1.example.com:3868,hss2.example.com:3868
export SIP_DIAMETER_TLS=1
export SIP_DIAMETER_CA=/path/to/ca.pem
export SIP_DIAMETER_CLIENT_CERT=/path/to/client.pem
export SIP_DIAMETER_CLIENT_KEY=/path/to/client.key
export SIP_DIAMETER_ORIGIN_HOST=scscf.example.com
export SIP_DIAMETER_ORIGIN_REALM=example.com
export SIP_DIAMETER_PEER_BACKOFF_MS=5000
export SIP_DIAMETER_MAX_INFLIGHT=64
export SIP_DB_URL=postgres://...
```

Optional:

| Variable | Purpose |
| --- | --- |
| `SIP_IMS_AKA_NUM_VECTORS` | Multi-vector MAR (1–5) |
| `SIP_IMS_AKA_STORE_KEYS` | Opaque CK/IK cache (default off) |
| `SIP_IMS_CX_PUSH` | Inbound RTR/PPR poll |
| `SIP_IMS_CX_PUSH_LISTEN` | mTLS Diameter listen for HSS push |
| `SIP_IMS_CX_PUSH_CLIENT_CN` | Optional exact client-certificate CN allowlist for mTLS push |
| `SIP_IMS_LIFECYCLE_HSS_RECONCILE` | Re-SAR after restart |

## Acceptance matrix (manual)

| Case | Expected SIP |
| --- | --- |
| Unknown user (Cx 5001) | 403 |
| Authorization rejected (5003) | 403 |
| HSS busy / unable (3004/5012) | 503 |
| Transport fail | 503 |
| AUTS resync | 401 stale + new challenge |
| Successful AKA REGISTER | 200 + lifecycle row |

## Optional Open5GS compose overlay

Madis does not vendor Open5GS images. Operators typically run Open5GS via its
upstream docker examples and point Madis at the freeDiameter Cx peer:

```yaml
# docker-compose.open5gs-overlay.example.yml (operator-owned)
# services:
#   open5gs-hss: ...
# networks:
#   attach Madis scscf to the Open5GS network and set:
#     SIP_DIAMETER_HOSTS: open5gs-hss:3868
#     SIP_DIAMETER_TLS: "1"   # or lab plaintext with ALLOW_PLAINTEXT=1
```

Copy and adapt; do not commit production secrets.

## IPsec SA export (access security)

Madis does not install kernel SAs. For lab access-security experiments:

```sh
export SIP_IMS_AKA_STORE_KEYS=1
export SIP_IMS_IPSEC_EXPORT=1
export SIP_IMS_IPSEC_SPI_BASE=2000
export SIP_IMS_IPSEC_PORT_C=5060
export SIP_IMS_IPSEC_PORT_S=5061
```

After successful AKA, Madis caches a bounded `madis.ims.ipsec.sa.v1` JSON
document (CK/IK base64, SPI pair, ports) in the issuing SIP worker for access
security integration tests. Madis does not yet provide an authenticated
external retrieval/export bridge or install kernel SAs; an operator must keep
this boundary disabled unless an approved enforcer bridge is deployed. Never
log the SA document in production logging paths.

When export is enabled, the loopback SIP worker admin plane exposes a
token-protected retrieval contract for an external enforcer:

```sh
curl -fsS -X POST http://127.0.0.1:9090/ims/ipsec/sa \
  -H "Authorization: Bearer $SIP_ADMIN_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"private_identity":"alice@example.com"}'
```

The route returns the bounded SA JSON only while the worker cache entry is
valid. It does not install kernel SAs; keep the admin listener private and do
not log the response.

## Rx / PCRF

```sh
export SIP_IMS_RX=1
export SIP_IMS_RX_AF_APP_ID=madis.voice
export SIP_IMS_RX_DEST_HOST=pcrf.example.com
# Diameter peer list must include a PCRF that answers Rx AAR (app 16777236)
```

Without a real PCRF, leave `SIP_IMS_RX=0` (default). Builders are covered by
`tests/ims_rx_test.mko`.

## Lab MMTel / TAS stub

```sh
python3 lab/mmtel_as.py --seed-json lab/mmtel_seed.json --port 5090
```

Provision subscriber `initial_filter_criteria` with `as_uri` pointing at
`sip:127.0.0.1:5090` (or the lab AS host) and set `SIP_IMS_3PREG=1` for
third-party REGISTER exercises. Barring returns 603; CFU returns 302.

## Out of scope for Madis CI

- Open5GS container images in default CI
- Commercial UE certification
- VoLTE dedicated bearer without external PCRF
- Kernel IPsec xfrm installation

Record external evidence separately from `./scripts/test.sh tests`.
