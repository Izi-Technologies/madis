# IMS lab media module

`rtp_module.py` is an external RTPEngine-ng compatible sidecar for the first
media interoperability slice. Madis keeps sending bounded `offer`, `answer`,
and `delete` control messages; this process allocates UDP ports, rewrites one
audio SDP stream, and forwards RTP/RTCP packets between the two legs.

Run it on a private media network:

```sh
python3 media/rtp_module.py \
 --control-host <control-host> \
  --control-port 2223 \
 --media-bind <media-bind-address> \
 --media-ip <media-address> \
  --media-min 30000 \
  --media-max 39999 \
  --session-timeout 3600
```

Point Madis at the sidecar with its existing RTPEngine configuration:

```text
rtpengine_enabled=true
rtpengine_host=<control-host>
rtpengine_port=2223
```

For a standalone Madis worker without a database, the same settings can be
provided through explicit environment overrides:

```text
SIP_RTPENGINE_ENABLED=1
SIP_RTPENGINE_HOST=<control-host>
SIP_RTPENGINE_PORT=2223
```

These environment values override database values for that worker. Set
`SIP_RTPENGINE_ENABLED=0` to disable the integration explicitly. Keep the
control address on a private network; the ng control protocol is not an
authentication boundary.

The control listener is loopback-only by default and accepts only the
configured source allow-list. Do not expose the ng control port publicly.
Configure `--media-ip` to an address reachable by both endpoints and ensure
the selected UDP range is allowed by the firewall.

This module is intentionally limited to a lab profile:

- one audio stream per call;
- RTP/RTCP version-2 packet forwarding without media inspection;
- no ICE/STUN, DTLS-SRTP termination, codec transcoding, recording, or media
  policy;
- no production-grade overload, persistence, or multi-site failover behavior.
- idle sessions are reclaimed after the bounded `--session-timeout`; signaling
  should still send `delete` on BYE/CANCEL.

The module is a separate process so media packet ownership and failure cannot
block the SIP worker. Phase 2 is complete only after testing this boundary
against real endpoints and a selected media/security profile.
