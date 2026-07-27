# IMS Diameter contracts

Madis includes selected client-side IMS Diameter builders and answer parsers in [`../ims_diameter.mko`](../ims_diameter.mko). These are integration contracts, not a complete IMS core.

## Cx

The Cx path uses the 3GPP vendor/application identifiers and selected command pairs from TS 29.229:

- UAR/UAA (`300`)
- SAR/SAA (`301`)
- LIR/LIA (`302`)
- MAR/MAA (`303`)
- RTR/RTA (`304`)
- PPR/PPA (`305`)

When `SIP_IMS_CX=1`, REGISTER authorization performs the configured Cx UAR/SAR sequence and fails closed when the HSS response does not authorize the registration. A successful UAA must include `Server-Name` matching `SIP_IMS_SERVER_NAME`; missing or mismatched assignment fails before SAR and no local registration is written. SAR uses `REGISTRATION` (1), `RE_REGISTRATION` (2), or `USER_DEREGISTRATION` (5) according to the SIP Contact/Expires lifecycle. Configure `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and `SIP_IMS_DEST_HOST`, plus the Diameter TLS/identity settings.

## CSCF REGISTER roles

Set `SIP_IMS_ROLE` to `pcscf`, `icscf`, or `scscf`; the default is `scscf` for compatibility. The P-CSCF role forwards REGISTER to the SIP target in `SIP_IMS_PCSCF_NEXT_HOP`. The I-CSCF role uses Cx LIR/LIA to obtain the S-CSCF server name when `SIP_IMS_CX=1`; otherwise it forwards to `SIP_IMS_ICSCF_NEXT_HOP`. The S-CSCF role keeps the local authentication, subscriber authorization, Cx UAR/SAR, AKA, and registrar path.

P-CSCF and I-CSCF targets must be operator-configured `sip:` or `sips:` targets. Missing, malformed, unavailable, or failed Cx role routing returns a deterministic 503 and never falls back to local registration. This is a bounded REGISTER role boundary, not a complete carrier-grade P-/I-/S-CSCF implementation.

For initial INVITE sessions, P-CSCF and I-CSCF use the same role targets and Cx LIR selection before dialplan, application, charging, or local-contact lookup. In-dialog requests are not re-selected; existing SIP Route and dialog state remains authoritative. The session path includes the worker’s existing transaction, NAT/SDP, media-control, CDR, and response-relay behavior.

Set `SIP_IMS_SESSION=1` on the S-CSCF to require both the originating private identity and the terminating public identity to have active local REGISTER bindings for an initial local session. A missing or expired caller binding returns 403; a missing or expired destination binding returns 404, before charging, application routing, or contact lookup. The default is `0` for compatibility with non-IMS SIP deployments.

## Sh

The Sh path uses selected TS 29.329 command pairs:

- UDR/UDA (`306`)
- PUR/PUA (`307`)
- SNR/SNA (`308`)
- PNR/PNA (`309`)

Request builders cover UDR, PUR, and SNR with bounded user identity, data-reference, service-indication, and opaque Sh-data fields. Shared answer parsing and result helpers are available to the integration layer.

## Subscriber authorization

Madis also exposes an optional fail-closed HTTPS subscriber authorization adapter for REGISTER. It is documented in [`ims-subscriber.md`](ims-subscriber.md) and uses [`ims-subscriber.schema.json`](ims-subscriber.schema.json). This adapter is an explicit authorization boundary; it does not implement HSS/UDM storage or AKA vector generation.

## Cx authentication vectors

`ims_cx_mar_vector_from_answer` validates a correlated Cx MAR/MAA response and extracts one `SIP-Auth-Data-Item` as the opaque [`ims-aka-vector.schema.json`](ims-aka-vector.schema.json) envelope. `ims_cx_mar_vector` performs the bounded MAR exchange used by the optional SIP AKA REGISTER gate.

Set `SIP_IMS_AKA=1` together with `SIP_IMS_CX=1` to enable that gate. The current profile accepts only `SIP_IMS_AKA_SCHEME=Digest-AKAv1-MD5`; the HSS remains responsible for Milenage/TUAK generation and key custody. Madis caches only XRES briefly in worker memory, derives the [RFC 3310](https://www.rfc-editor.org/rfc/rfc3310) Digest response from it, rejects stale/replayed responses, and does not persist AKA secrets or use the confidentiality/integrity keys for media security.

## What remains external

Madis does not provide HSS/UDM storage, P-/I-/S-CSCF service logic, TAS/MMTel, PCRF/PCF, complete Diameter peer routing/failover, push-request handling for every command, or a complete IMS release profile. Carrier-specific AVP requirements and interoperability must be tested against the selected 3GPP release and vendor.

See [`diameter.md`](diameter.md) for transport, TLS, charging, and peer limitations.
