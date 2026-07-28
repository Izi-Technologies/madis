# Docker IMS lab

This profile runs a reproducible local IMS smoke environment:

- `hss`: the bounded Cx/AKA HSS adapter with a TLS-only Diameter listener.
- `madis`: the Mako 0.4.18 SIP worker in standalone in-memory mode.
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
IMS Cx/AKA REGISTER, INVITE, SDP RTP, ACK, BYE
```

The worker SIP and admin ports are published only on loopback as `15060/udp` and `18080/tcp`. The HSS and media control ports stay on the private Docker network. Madis may send media control commands only from its fixed lab address (`172.30.0.4`); loopback is allowed only for the media container healthcheck.

Stop the containers and network with:

```sh
docker compose -f docker-compose.ims-lab.yml down
```

The named `ims-hss-certs` volume holds the short-lived self-signed HSS certificate. It contains generated runtime material and is not part of the repository. Remove that volume only when intentionally resetting the lab certificate:

```sh
docker volume rm sipproxy_ims-hss-certs
```

## What the test proves

The client checks TLS certificate validation from Madis to the HSS, Cx/AKA challenge and response handling for two subscribers, SIP INVITE forwarding, SDP offer/answer rewrite to the relay, RTP in both directions, ACK, and BYE. It does not test real UE behavior, full 3GPP IMS procedures, ICE/DTLS-SRTP, codecs, recording, external RTPEngine interoperability, or clustered state.

The Dockerfiles pin the Mako source to tag `v0.4.18` and build the worker inside the image with a matching runtime. The build requires Docker Desktop or a Linux Docker Engine with network access to the Mako repository and base-image registry.
