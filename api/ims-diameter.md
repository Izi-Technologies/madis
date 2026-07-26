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

When `SIP_IMS_CX=1`, REGISTER authorization performs the configured Cx UAR/SAR sequence and fails closed when the HSS response does not authorize the registration. Configure `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and `SIP_IMS_DEST_HOST`, plus the Diameter TLS/identity settings.

## Sh

The Sh path uses selected TS 29.329 command pairs:

- UDR/UDA (`306`)
- PUR/PUA (`307`)
- SNR/SNA (`308`)
- PNR/PNA (`309`)

Request builders cover UDR, PUR, and SNR with bounded user identity, data-reference, service-indication, and opaque Sh-data fields. Shared answer parsing and result helpers are available to the integration layer.

## What remains external

Madis does not provide HSS/UDM storage, P-/I-/S-CSCF service logic, TAS/MMTel, PCRF/PCF, complete Diameter peer routing/failover, push-request handling for every command, or a complete IMS release profile. Carrier-specific AVP requirements and interoperability must be tested against the selected 3GPP release and vendor.

See [`diameter.md`](diameter.md) for transport, TLS, charging, and peer limitations.
