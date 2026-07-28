# Testing and release checks

Madis builds and tests with Mako **0.4.18** and a matching runtime directory. Do not mix a different compiler/runtime pair with generated C.

## Local CI

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

The CI script runs:

- Mako syntax checks and lint for `main.mko` and `admin/main.mko`.
- All repository Mako test files.
- Native SIP worker and WebUI links, including the `madis_memory.c` bridge.
- JSON-schema parsing, shell syntax validation, and Python SDK compilation.
- Default Python unit tests for the standalone `lab/` HSS adapter and `media/`
  RTPEngine-compatible sidecar.

The checks are deterministic contract and regression tests. They do not establish interoperability with every SIP, WebRTC, Diameter, IMS, or SS7 implementation.

## Focused tests

`tests/ims_lab_test.mko` is a deterministic two-subscriber HSS/Cx test double. It exercises real MAR/MAA message construction, Cx correlation, AKA response verification, replay rejection, registration bindings, and the S-CSCF session gate. It is not a substitute for interoperability testing against an external HSS/UDM, UE, or media system.

`tests/ims_aka_test.mko` explicitly covers missing vectors, malformed AKA
credentials, replay rejection, and an expired cached vector. The expiration
check validates the worker-side bounded XRES cache; vector generation and
lifetime policy remain HSS/UDM responsibilities.

`tests/rtpengine_test.mko` validates RTPEngine ng offer/answer/delete command shape, including Call-ID and dialog-tag correlation, plus control-character and length bounds on tags. With `SIP_RTPENGINE_TEST_NETWORK=1`, it also runs a local UDP ng-shaped responder and exercises the production client path end to end: offer/answer SDP replacement, delete acknowledgement, and no-responder timeout failure. It does not replace interoperability testing against a real RTPEngine, RTP, ICE, or DTLS-SRTP endpoint.

The same suite covers the RTPEngine SDP boundary: content-type checks, required `v=0` and `m=` lines, and body-size bounds. The production gate also scans every body byte for NULs before sending it to RTPEngine.

`tests/ims_session_timer_test.mko` covers the opt-in RFC 4028 request boundary: valid `Session-Expires` parameters, effective `Min-SE` handling, configured maximums, duplicate headers, malformed refresher values, quoted parameters, and control-character rejection. It does not prove endpoint refresh or external-stack interoperability.

`tests/ims_identity_test.mko` covers disabled compatibility behavior, untrusted asserted/preferred identity stripping, trusted single-identity validation, duplicate/list rejection, and `Privacy: id` outbound filtering. It does not prove full RFC 3325/RFC 8224 interoperability or identity assertion generation.

`tests/ims_path_test.mko` covers optional P-CSCF Path insertion, replacement of UE-supplied Path headers, `sip:`/`sips:` URI validation, and rejection of lists, control characters, and embedded name-addr values. It does not prove dynamic Path discovery, flow-token management, or multi-hop interoperability.

`tests/ims_registration_test.mko` covers the optional local-S-CSCF Service-Route and P-Associated-URI response values, `sip:`/`sips:` URI validation, and rejection of lists, control characters, embedded name-addr values, and unsupported schemes.

`tests/ims_subscriber_test.mko` covers the versioned authorization envelope, fail-closed identity/assignment checks, and bounded `service_profile.associated_uris` extraction. It does not prove external HSS/UDM interoperability or iFC/TAS execution.

`tests/ims_ifc_test.mko` covers target-only `service_profile.initial_filter_criteria` extraction, four-target and uniqueness limits, SIP/SIPS target validation, unsafe delimiter rejection, malformed array elements, originating/terminating live-registration guards, final-binding expiry reconciliation, outbound `Privacy: id` filtering for AS forks, and clearing of stored triggers. It does not prove standard iFC condition evaluation or TAS behavior.

| Test | Coverage |
| --- | --- |
| `tests/admin_http_test.mko` | HTTP framing, cookie boundaries, form decoding, and Origin checks. |
| `tests/adversarial_test.mko` | Malformed headers, framing, injection, limits, status handling, and SIP URI validation. |
| `tests/app_gateway_test.mko` | Signed application/module commands, header boundaries, SQL-shaped data, and module allowlists. |
| `tests/auth_test.mko` | Digest parameters, qop, MD5/SHA-256, `-sess`, and bounded attacker caches. |
| `tests/b2bua_test.mko` | Independent B2BUA legs, dialog translation, cleanup, and header safety. |
| `tests/carrier_contract_test.mko` | Billing identity/escaping, control API routes, validation, and resource allowlists. |
| `tests/diameter_codec_test.mko` | Diameter headers, AVPs, grouping, malformed input, Cx/Sh correlation, and credit-control fields. |
| `tests/proxy_state_test.mko` | Registration, transaction replay, INVITE/CANCEL isolation, dialog phase classification/teardown, forks, ACK/CANCEL/BYE, routes, and state limits. |
| `tests/ims_roles_test.mko` | IMS role boundaries, initial versus in-dialog classification, To-tag-specific PRACK/UPDATE target selection, and bounded RSeq/RAck validation. |
| `tests/ims_session_timer_test.mko` | Opt-in `Session-Expires`/`Min-SE` validation, bounds, duplicate-header rejection, and parser hardening. |
| `tests/ims_identity_test.mko` | Trusted-network P-Asserted/P-Preferred identity validation, untrusted stripping, and Privacy filtering. |
| `tests/ims_path_test.mko` | Optional P-CSCF Path insertion, UE-supplied Path replacement, and route safety. |
| `tests/ims_registration_test.mko` | Optional Service-Route/P-Associated-URI configuration and REGISTER response header safety. |
| `tests/ims_subscriber_test.mko` | Subscriber authorization envelope and bounded profile-associated identity extraction. |
| `tests/ims_ifc_test.mko` | Target-only profile iFC target validation, bounded state, duplicate rejection, call-direction guards, and clearing. |
| `tests/rfc3261_abnf_test.mko` | Compact headers, quoted values, continuation, Via grammar, and Proxy-Require. |
| `tests/rfc3263_test.mko` | NAPTR/SRV ordering, transport selection, IPv6 targets, and port validation. |

## Protocol and load gates

The optional gates exercise deployment-dependent behavior beyond the unit/contract tests:

```sh
MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/rfc_gate.sh

MAKO=/path/to/mako \
MAKO_RUNTIME_PATH=/path/to/mako/runtime \
  ./bench/sanitizer.sh
```

The RFC gate covers selected UDP/TCP/TLS/WSS, IPv6, loss/delay/duplicate/reorder, ABNF, and transport behavior. The sanitizer gate builds AddressSanitizer/UndefinedBehaviorSanitizer variants and runs transport, WSS, TLS/IPv6, fault, and fuzz matrices where the host supports them.

For CPS measurements:

```sh
RATE=100 CALLS=1000 CONCURRENCY=200 WORKERS=1 \
  ./bench/benchmark.sh
```

Record host CPU, memory, file descriptors, database capacity, network conditions, and exact configuration with every benchmark result. A benchmark result is not a production capacity guarantee.

For the opt-in local RTPEngine control-path check:

```sh
SIP_RTPENGINE_TEST_NETWORK=1 \
  /path/to/mako test tests/rtpengine_test.mko --native-source madis_memory.c
```

This verifies the Madis UDP client against a test responder in the same process boundary; it is not evidence of RTP, ICE, DTLS-SRTP, endpoint, or production RTPEngine interoperability.

## Docker IMS integration lab

The repository includes a containerized six-service smoke environment for the
implemented IMS boundary. It builds separate Mako `v0.4.18` P-/I-/S-CSCF
workers, starts TLS Cx/AKA and HTTPS subscriber-authority endpoints in the HSS
adapter plus an RTPEngine-ng-compatible media relay, rejects unknown and
disabled subscribers, then runs two test subscribers through role-chain
REGISTER and initial-INVITE forwarding, SDP offer/answer, bidirectional RTP,
ACK, and BYE:

```sh
docker compose -f docker-compose.ims-lab.yml up \
  --abort-on-container-exit \
  --exit-code-from client
docker compose -f docker-compose.ims-lab.yml down
```

The lab uses fake subscriber data and short-lived runtime certificates. The
HSS private key is generated inside a named Docker volume and is never copied
into the repository. SIP/admin ports are loopback-published; HSS and media
control remain on the private Compose network. A passing run is an integration
smoke result, not proof of complete 3GPP IMS interoperability, ICE/DTLS-SRTP,
real UE compatibility, clustered state, or production capacity.

## Release checklist

- [ ] `scripts/ci.sh` passes with Mako 0.4.18.
- [ ] API schemas and documentation match the deployed configuration and token scopes.
- [ ] TLS certificates, CA bundles, bearer-token rotation, database permissions, firewall rules, and backups are reviewed.
- [ ] A real OPTIONS/REGISTER and representative INVITE path work in staging.
- [ ] Billing event deduplication and acknowledgement recovery have been exercised.
- [ ] Control API read/write separation and revision-conflict handling have been exercised.
- [ ] Application/module timeout, signature, allowlist, and failure-mode behavior has been tested if enabled.
- [ ] External SIP, Diameter/IMS, media, and SS7 interoperability checks are recorded separately.
- [ ] Upgrade and database restore procedures have been rehearsed.
## HEP and cluster validation

The HEP wire-format, queue clamp, and full-queue drop regressions are in
`tests/hep_test.mko`. The native test bridge
is linked explicitly with Mako 0.4.18:

```sh
MAKO_RUNTIME=/path/to/mako/runtime \
  mako test tests --native-source madis_memory.c
```

`tests/capacity_test.mko` covers the configurable call/dialog state budget and
its lower/upper clamps. Load tests must also verify that the configured state
budget is above the expected live-dialog record count; reaching the budget
must produce bounded admission failure rather than state eviction.

Run load tests with HEP both disabled and enabled, then repeat with an
unreachable collector. SIP success/error rates and transaction timing must be
unchanged by collector failure. Cluster test runs must preserve UDP
transaction affinity and TCP/TLS/WebSocket connection affinity; see
[`clustering.md`](clustering.md).

## External IMS lab adapters

The repository also checks the standalone lab components without requiring
external services. The default commands run offline unit/contract coverage;
listener and worker-backed checks are opt-in because they need local sockets or
an executable worker:

```sh
python3 -m unittest discover -s lab -p 'test_*.py'
python3 -m unittest discover -s media -p 'test_*.py'

# Listener tests: Diameter TCP and HTTP authorization/provisioning
IMS_HSS_TEST_NETWORK=1 python3 -m unittest discover -s lab -p 'test_*.py'

# Diameter and HTTPS TLS listeners with ephemeral certificates
IMS_HSS_TEST_TLS=1 python3 -m unittest \
  lab.test_ims_hss.HssDiameterTlsWireTests \
  lab.test_ims_hss.HssHttpsWireTests -v

# Full worker-backed two-subscriber IMS smoke with a local S-CSCF and external RTP sidecar
IMS_END_TO_END=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end -v

# The same call with Diameter TLS and an ephemeral HSS certificate
IMS_END_TO_END=1 IMS_END_TO_END_TLS=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end -v
```

The HSS tests cover Cx answer construction, unknown-subscriber and serving-
server rejection, opaque vector handling, malformed Diameter requests being
dropped without an answer, and the rule that HTTP subscriber authorization
never returns XRES. The media tests cover bounded ng control,
SDP rewriting, offer/answer/delete lifecycle, malformed input rejection, and
localhost RTP forwarding. The worker-backed test additionally verifies that
standalone `SIP_RTPENGINE_*` configuration reaches the call path, that both
SDP legs are rewritten, and that RTP crosses the sidecar in both directions.
It also has an opt-in HSS-unavailable case that requires the worker to fail
closed with SIP `503`; it is skipped unless a built worker is supplied. The
Docker profile extends that same contract across separate P-/I-/S-CSCF
workers and uses Cx LIR to select the S-CSCF. These tests are lab-contract
evidence; they do not replace tests against real UEs, HSS/UDM systems,
RTPEngine deployments, or media/security profiles.
