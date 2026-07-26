# Diameter support

Madis has a bounded Diameter codec and a client-side peer layer in
[`diameter.mko`](../diameter.mko). It uses the Mako 0.4.16 socket, TLS, and
SCTP APIs.
The application-specific IMS contracts are in
[`ims_diameter.mko`](../ims_diameter.mko).

## Supported path

- RFC 6733 Diameter framing, standard and vendor AVP validation, CER/CEA
  negotiation, TCP timeout bounds, serialized persistent TLS peers, DWR/DWA
  handling, and strict hop-by-hop/end-to-end correlation.
- RFC 8506 application ID 4, CCR/CCA command code 272, mandatory request and
  answer AVPs, `INITIAL_REQUEST`, `UPDATE_REQUEST`, `TERMINATION_REQUEST`, and
  `EVENT_REQUEST` encoding.
- SIP subscription identity, service context, destination rating input,
  requested/used/granted time units, result-code validation, and session/request
  correlation.
- Verified TLS/TCP by default. Set `SIP_DIAMETER_CLIENT_CERT` and
  `SIP_DIAMETER_CLIENT_KEY` for pooled mutual TLS with the persistent peer.
- SCTP is available with `SIP_DIAMETER_TRANSPORT=sctp` on platforms where
  Mako reports SCTP support. Set `SIP_DIAMETER_ALLOW_PLAINTEXT=1` only when
  the deployment supplies protection outside SCTP, such as NDS/IPsec.

Configuration for online preauthorization:

```sh
SIP_BILLING_MODE=preauth
SIP_CHARGING_PROTOCOL=diameter
SIP_DIAMETER_HOST=cc.example.net
SIP_DIAMETER_PORT=5658
SIP_DIAMETER_TLS=1
SIP_DIAMETER_CA=/etc/ssl/certs/carrier-ca.pem
SIP_DIAMETER_PERSISTENT=1
SIP_DIAMETER_ORIGIN_HOST=proxy.example.net
SIP_DIAMETER_ORIGIN_REALM=example.net
SIP_DIAMETER_DEST_REALM=ocs.example.net
```

The SIP worker sends the initial request before routing an INVITE and sends a
termination request on BYE/CANCEL. An update encoder is available, but this
worker does not enforce media quota expiry or run autonomous reauthorization
timers.

## Current limitations

The current path does not implement redirect/relay routing, peer failover, or
automatic media-plane quota enforcement. SCTP uses one request per association;
the Mako Diameter manager is not yet the Madis peer scheduler. Plain TCP and
SCTP are disabled unless `SIP_DIAMETER_ALLOW_PLAINTEXT=1` is set.

RFC 4006 is not the implementation target because RFC 8506 obsoletes it. RFC
4740 is the Diameter SIP authentication/authorization application and is not
implicitly required for credit control. RFC 7155 (NASREQ) and RFC 5777 (QoS
attributes) become required only when those separate applications are enabled.
3GPP IMS deployments additionally require the applicable 3GPP TS 29-series
interfaces and a carrier-specific interoperability profile.

Wire-format and malformed-input tests are in
[`tests/diameter_codec_test.mko`](../tests/diameter_codec_test.mko). They run
without a network peer.
