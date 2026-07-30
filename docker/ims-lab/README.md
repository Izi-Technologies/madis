# Docker IMS lab

This profile runs a reproducible local IMS smoke environment:

- `hss`: the bounded Cx/AKA HSS adapter with TLS-only Diameter and HTTPS subscriber-authorization listeners.
- `pcscf`, `icscf`, and `scscf`: separate Mako 0.5.0 SIP workers in standalone in-memory mode. P-CSCF forwards REGISTER and initial INVITE to I-CSCF; I-CSCF uses Cx LIR to select S-CSCF; S-CSCF owns AKA, registrations, dialogs, and media control.
- `media`: the bounded RTPEngine-ng-compatible RTP relay module.
- `client`: two deterministic SIP user agents that register, authenticate, place a call, exchange RTP, and tear down the dialog.

The subscribers and credentials are test fixtures only. This is an integration lab, not a production IMS deployment and not evidence of carrier interoperability or capacity.

## Run

From the repository root:

```sh
docker compose -f docker-compose.ims-lab.yml up \
  --abort-on-container-exit \
  --exit-code-from client
```

A successful run ends with:

```text
P-/I-/S-CSCF Cx/AKA REGISTER, authenticated INVITE, SDP relay, bidirectional RTP, ACK, BYE
```

The P-CSCF SIP and admin ports are published only on `localhost` as
`15060/udp` and `18080/tcp` (override with `IMS_LAB_SIP_PORT`/`IMS_LAB_ADMIN_PORT`
when they collide with a local process). The HSS and media control ports stay
on the private Docker network. Only the configured S-CSCF container may send
media control commands; local access is allowed only for the media container
healthcheck.

Stop the containers and network with:

```sh
docker compose -f docker-compose.ims-lab.yml down
```

The named `ims-hss-certs` volume holds the short-lived self-signed HSS certificate. It contains generated runtime material and is not part of the repository. Remove that volume only when intentionally resetting the lab certificate:

```sh
docker volume rm sipproxy_ims-hss-certs
```

## What the test proves

The client checks deterministic `503` rejection for an unknown and a disabled subscriber before successful registration, TLS certificate validation from S-CSCF/I-CSCF to the HSS, HTTPS subscriber authorization, Cx/AKA challenge and response handling for two subscribers, P-/I-/S-CSCF REGISTER and initial-INVITE forwarding, SDP offer/answer rewrite to the relay, RTP in both directions, ACK, and BYE. It does not test real UE behavior, full 3GPP IMS procedures, ICE/DTLS-SRTP, codecs, recording, external RTPEngine interoperability, or clustered state.

The Dockerfiles pin the Mako source to tag `v0.5.0` and build the worker inside the image with a matching runtime. The build requires Docker Desktop or a Linux Docker Engine with network access to the Mako repository and base-image registry.
