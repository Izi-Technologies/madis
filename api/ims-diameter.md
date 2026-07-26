# IMS Diameter interfaces

The native IMS layer is in [`ims_diameter.mko`](../ims_diameter.mko). It is a
client-side contract for a SIP proxy talking to an HSS or another Diameter
server; it is not an HSS implementation.

## Cx/Dx

The codec uses 3GPP vendor `10415`, application `16777216`, and the command
pairs defined by TS 29.229:

- UAR/UAA `300`
- SAR/SAA `301`
- LIR/LIA `302`
- MAR/MAA `303`
- RTR/RTA `304`
- PPR/PPA `305`

The request builders cover UAR, SAR, LIR, MAR, and RTR. The shared answer
validator checks the Diameter header, application, transaction identifiers,
session ID, vendor-specific application ID, auth-session state, origin, and
either a standard or 3GPP experimental result code.

Set `SIP_IMS_CX=1` to run UAR followed by SAR during REGISTER. This mode is
fail-closed. `SIP_IMS_VISITED_NETWORK`, `SIP_IMS_SERVER_NAME`, and
`SIP_IMS_DEST_HOST` select the identities used in the request. The peer must
be reachable over verified TLS. With `SIP_DIAMETER_PERSISTENT=1`, Mako
0.4.16's pooled mTLS API is used when both client certificate variables are
configured.

## Sh

The codec uses 3GPP vendor `10415`, application `16777217`, and the command
pairs defined by TS 29.329:

- UDR/UDA `306`
- PUR/PUA `307`
- SNR/SNA `308`
- PNR/PNA `309`

The request builders cover UDR, PUR, and SNR. User-Identity is encoded as a
3GPP grouped AVP, Data-Reference and Service-Indication are vendor AVPs, and
Sh-Data is treated as bounded opaque data. The module also exposes the shared
answer parser and accepted-result helpers.

## What this does not provide

The following still need separate carrier components or implementation work:

- HSS/UDM data storage and all S-CSCF/I-CSCF service logic
- Rx, Gx, Ro, Rf, Sy, and other policy/charging applications
- Diameter relay/redirect routing, peer failover, and autonomous peer scheduling
- autonomous quota timers, media policy enforcement, and push-request handlers
  for inbound RTR/PPR/PNR traffic
- release-specific 3GPP conformance and interoperability testing against the
  selected vendor profile

The command and AVP values in this module are based on the cited 3GPP
application specifications. A carrier deployment still needs to select a
3GPP release and test the complete message-content rules for that release.
