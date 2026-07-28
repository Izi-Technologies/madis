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

## Run locally

Use a private seed file. Do not commit it or place real subscriber secrets in
the repository:

```sh
python3 lab/ims_hss.py \
  --seed-json /path/to/ims-lab-subscribers.json \
  --diameter-host 127.0.0.1 \
  --diameter-port 3868 \
  --http-host 127.0.0.1 \
  --http-port 8444
```

The local example uses loopback HTTP. Enable HTTPS by supplying an operator-
managed certificate and key:

```sh
python3 lab/ims_hss.py \
  --seed-json /path/to/ims-lab-subscribers.json \
  --http-host 127.0.0.1 \
  --http-port 8444 \
  --http-cert /path/to/subscriber.crt \
  --http-key /path/to/subscriber.key
```

For a local plaintext Diameter-only check, Madis must explicitly opt in:

```text
SIP_DIAMETER_HOST=127.0.0.1
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

The opt-in TLS wire test generates its certificate in a temporary directory;
no certificate or private key is stored in the repository:

```sh
IMS_HSS_TEST_TLS=1 python3 -m unittest lab.test_ims_hss.HssDiameterTlsWireTests -v
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
