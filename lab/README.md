# IMS lab adapters

`ims_hss.py` is an external lab process for the first IMS interoperability
profile. It provides:

- a Diameter TCP/TLS listener for the Cx UAR, SAR, LIR, and MAR requests that
  Madis already emits;
- the versioned HTTP/HTTPS subscriber authorization contract used by
  `SIP_IMS_SUBSCRIBER_URL`;
- bounded provisioning from a seed JSON file or the protected HTTP endpoint.

The adapter is intentionally not a production HSS/UDM. It returns configured
opaque XRES values for the repository's selected `Digest-AKAv1-MD5` lab
profile. It does not implement Milenage/TUAK, durable secret protection, full
Sh user data, Diameter relay/failover, or carrier policy.

### Cx MAR multi-vector and AUTS (lab)

- **Number-Of-Auth-Items** (AVP 607, 1–5): MAA returns that many
  `SIP-Auth-Data-Item` groups with distinct RAND||AUTN-like authenticate
  blobs and the configured XRES.
- **AUTS resync**: when MAR includes SIP-Authorization=AUTS and
  SIP-Authenticate=RAND, the adapter accepts only if RAND matches the last
  RAND issued for that private identity, then returns a fresh vector set.
  Unknown RAND fails closed (`5001`). This exercises Madis’s AUTS→MAR path
  without real SQN cryptography.

Evidence tests (default CI):

```sh
python3 -m unittest lab.test_ims_hss.HssAdapterTests.test_mar_multi_vector_count \
  lab.test_ims_hss.HssAdapterTests.test_mar_auts_resync_requires_issued_rand -v
```

### Multi-peer Madis client against the lab HSS

Run two adapter instances on different ports and point Madis at both:

```text
SIP_DIAMETER_HOSTS=<peer-a-host>:3868,<peer-b-host>:3869
SIP_DIAMETER_TLS=0
SIP_DIAMETER_ALLOW_PLAINTEXT=1
```

Stop the first listener to exercise preferred-peer advance on open/exchange
failure. For TLS multi-peer, use operator-managed certs on each instance.

### Open5GS / production HSS

Replace the lab adapter with a real HSS (for example Open5GS HSS + freeDiameter)
using the same Madis env (`SIP_DIAMETER_*`, `SIP_IMS_CX`, `SIP_IMS_AKA`). Expect
to validate:

1. UAR/SAR/LIR against real subscriber data
2. MAR multi-vector and AUTS SQN recovery with a real UE (Milenage)
3. RTR/PPR over the client peer and/or `SIP_IMS_CX_PUSH_LISTEN`

See [`../docs/interop-open5gs.md`](../docs/interop-open5gs.md) for env matrix,
IPsec SA export, Rx hooks, and operator compose overlay notes.

Record packet captures separately from unit tests; the lab adapter only proves
Madis wire boundaries and fail-closed policy.

## Lab MMTel / TAS stub

`mmtel_as.py` is a deterministic UDP SIP AS for iFC / 3pREG evidence:

```sh
python3 lab/mmtel_as.py --seed-json lab/mmtel_seed.json --bind <bind-address> --port 5090
```

| Seed flag | Behaviour |
| --- | --- |
| `barring_mo: true` | INVITE → 603 Decline |
| `cfu: sip:...` | INVITE → 302 Contact redirect |
| (default) | INVITE → 200; REGISTER → 200 (3pREG) |

Point subscriber `initial_filter_criteria` `as_uri` at this AS. Not production
MMTel; call-forward logic stays outside Madis.

## Smoke helpers

```sh
./scripts/lab-smoke.sh unit   # contract + lab unit tests
./scripts/lab-smoke.sh e2e    # needs Mako 0.5.0; builds Madis and runs two-subscriber Cx/AKA call
./scripts/lab-smoke.sh docker # full P/I/S compose (Docker must have enough RAM to cargo-build Mako)
```

## Run locally

Use a private seed file. Do not commit it or place real subscriber secrets in
the repository:

```sh
python3 lab/ims_hss.py \
  --seed-json /path/to/ims-lab-subscribers.json \
  --diameter-host <diameter-host> \
  --diameter-port 3868 \
  --http-host <http-host> \
  --http-port 8444
```

The local example uses loopback HTTP. Enable HTTPS by supplying an operator-
managed certificate and key:

```sh
python3 lab/ims_hss.py \
  --seed-json /path/to/ims-lab-subscribers.json \
  --http-host <http-host> \
  --http-port 8444 \
  --http-cert /path/to/subscriber.crt \
  --http-key /path/to/subscriber.key
```

For a local plaintext Diameter-only check, Madis must explicitly opt in:

```text
SIP_DIAMETER_HOST=<diameter-host>
SIP_DIAMETER_PORT=3868
SIP_DIAMETER_TLS=0
SIP_DIAMETER_ALLOW_PLAINTEXT=1
SIP_DIAMETER_ORIGIN_HOST=pcscf.lab.local
SIP_DIAMETER_ORIGIN_REALM=example.com
SIP_DIAMETER_DEST_REALM=example.com
SIP_IMS_CX=1
SIP_IMS_AKA=1
SIP_IMS_AKA_SCHEME=Digest-AKAv1-MD5
SIP_IMS_VISITED_NETWORK=example.com
SIP_IMS_SERVER_NAME=sip:scscf.example.com
```

Use Diameter TLS and HTTPS with operator-managed certificates before putting
the adapter on any shared network. The HTTP provisioning token must be at
least 16 characters. The service rejects non-loopback HTTP without an HTTP
token and never includes XRES in an authorization response.

The opt-in Diameter and HTTPS TLS wire tests generate certificates in a
temporary directory; no certificate or private key is stored in the repository:

```sh
IMS_HSS_TEST_TLS=1 python3 -m unittest \
  lab.test_ims_hss.HssDiameterTlsWireTests \
  lab.test_ims_hss.HssHttpsWireTests -v
```

## Seed shape

The seed file is read-only input and must contain a `subscribers` array. The
XRES value is base64-encoded so the file format can represent opaque bytes:

```json
{
  "subscribers": [
    {
      "public_identity": "sip:alice@example.com",
      "private_identity": "alice@example.com",
      "assigned_server_name": "sip:scscf.example.com",
      "xres_base64": "<base64 test value>",
      "service_profile": {
        "associated_uris": ["sip:alice@example.com"]
      }
    }
  ]
}
```

The seed must be supplied out of band. It is not an IMS secret-management
solution.
