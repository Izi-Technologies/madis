# Diameter support

Madis contains a bounded, client-side Diameter codec and peer path in [`../diameter.mko`](../diameter.mko). It is used for selected online charging and IMS integration contracts. It is not a general Diameter relay, a complete policy server, or an HSS/UDM.

## Implemented paths

- RFC 6733 message framing, header validation, AVP encoding/decoding, result handling, and bounded timeouts.
- CER/CEA peer negotiation and DWR/DWA watchdog messages.
- RFC 8506 credit-control CCR/CCA commands with initial, update, termination, and event request types, selected charging AVPs, session IDs, granted/used units, and result codes.
- Verified TLS/TCP peer operation, including optional serialized persistent peer reuse.
- SCTP transport selection where the Mako runtime and host provide SCTP support.
- Selected 3GPP Cx/Dx and Sh message builders in [`../ims_diameter.mko`](../ims_diameter.mko).

## Online charging

Enable preauthorization explicitly:

```sh
SIP_BILLING_MODE=preauth
SIP_CHARGING_PROTOCOL=diameter
SIP_DIAMETER_HOST=cc.example.net
# Or multi-peer failover (preferred host remembered after success):
# SIP_DIAMETER_HOSTS=hss1.example.com,hss2.example.com:3868
SIP_DIAMETER_PORT=5658
SIP_DIAMETER_TLS=1
SIP_DIAMETER_CA=/etc/ssl/certs/carrier-ca.pem
SIP_DIAMETER_PERSISTENT=1
SIP_DIAMETER_ORIGIN_HOST=proxy.example.net
SIP_DIAMETER_ORIGIN_REALM=example.net
SIP_DIAMETER_DEST_REALM=ocs.example.net
```

The worker sends the initial authorization before routing an INVITE and can send termination usage on BYE/CANCEL. Update encoding exists, but the worker does not implement autonomous quota timers or media-plane quota enforcement.

TLS is the normal transport. Configure `SIP_DIAMETER_CLIENT_CERT` and `SIP_DIAMETER_CLIENT_KEY` for mTLS. SCTP or plaintext TCP requires explicit platform and deployment protection; `SIP_DIAMETER_ALLOW_PLAINTEXT=1` is an override, not a secure default.

### Multi-peer client failover

Set `SIP_DIAMETER_HOSTS` to a comma-separated list of peers (`host` or `host:port`). On open or exchange failure the client advances the preferred index and retries the next peer once. `SIP_DIAMETER_HOST` remains the single-peer fallback when `HOSTS` is empty.

### Cx push server listen

With `SIP_IMS_CX=1`, `SIP_IMS_CX_PUSH=1`, and `SIP_IMS_CX_PUSH_LISTEN=1`, the worker also listens for HSS-initiated TLS mTLS connections on `SIP_IMS_CX_PUSH_PORT` (default 3868). Requires `SIP_DIAMETER_SERVER_CERT`/`SIP_DIAMETER_SERVER_KEY` (or SIP TLS certs) and `SIP_DIAMETER_SERVER_CLIENT_CA` (or `SIP_DIAMETER_CA`). The server answers CER with CEA advertising Cx, then handles RTR/PPR/DWR.

## Deliberate limitations

The current integration does not provide:

- Diameter redirect/relay agents or a full autonomous peer state machine;
- multi-connection client pools or weighted load balancing;
- autonomous reauthorization/quota timers or media-policy enforcement;
- RFC 4006 as a separate implementation target;
- carrier-specific 3GPP release profiles or vendor interoperability certification;
- other Diameter applications such as NASREQ, QoS, Rx, Gx, Ro, Rf, or Sy as complete services.

Use [`../tests/diameter_codec_test.mko`](../tests/diameter_codec_test.mko) for the repository’s framing, AVP, grouping, malformed-input, and correlation coverage. A carrier deployment still needs end-to-end tests against its selected OCS and 3GPP release/profile.
