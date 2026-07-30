# Testing and release checks

The opt-in session-timer worker regression additionally verifies a `422 Min-SE` response for an undersized `Session-Expires` interval and forwarding of a valid interval. It does not prove endpoint refresh or external-stack interoperability.

The opt-in worker-backed two-subscriber IMS smoke runs the worker against the lab HSS with TLS Cx/AKA **and** the fail-closed HTTPS subscriber-authorization boundary (ephemeral certificates, bearer token), then exercises authenticated REGISTER retransmission replay, initial-INVITE forwarding, in-dialog `UPDATE` and re-INVITE offer/answer exchanges through the RTP sidecar, and authenticated INVITE cancellation with downstream `487 Request Terminated` handling. Separate opt-in cases provision two target-only iFC application branches and verify a reliable `183 Session Progress`/PRACK exchange with To-tag routing, downstream `200 OK` acknowledgement, CANCEL cleanup after one branch answers, and a correlated `408 Request Timeout` when an INVITE receives no final response.

Madis builds and tests with Mako **0.5.0** and a matching runtime directory. Mako 0.5.0 is native-first, so the contract suite selects its C backend explicitly while production C emission remains exercised. MADIS supplies an explicit `SO_REUSEPORT` bridge for multi-worker UDP. Do not mix a different compiler/runtime pair with generated C.

## Local CI

```sh
MAKO_BIN=/path/to/mako \
MAKO_RUNTIME=/path/to/mako/runtime \
  ./scripts/ci.sh
```

## Contract tests (with native bridge)

`tests/proxy_state_test.mko` and any suite pulling `rfc.mko` transaction ticks
need `madis_memory.c` linked. Prefer:

```sh
./scripts/test.sh tests
# or one file:
./scripts/test.sh tests/proxy_state_test.mko
```

Plain `mako test tests` without `MAKO_LDFLAGS` will fail to link `madis_cmap_*`.

The CI script runs:

- Mako syntax checks and lint for `main.mko` and `admin/main.mko`.
- All repository Mako test files.
- Native SIP worker and WebUI links, including the `madis_memory.c` bridge.
- JSON-schema parsing, shell syntax validation, and Python SDK compilation.
- Default Python unit tests for the standalone `lab/` HSS adapter and `media/`
  RTPEngine-compatible sidecar.

The checks are deterministic contract and regression tests. They do not establish interoperability with every SIP, WebRTC, Diameter, IMS, or SS7 implementation.

## Focused tests

Run the worker session-timer regression with:

```sh
IMS_END_TO_END=1 IMS_END_TO_END_SESSION_TIMERS=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_session_timer_min_se_and_forwarding -v
```

`tests/ims_lab_test.mko` is a deterministic two-subscriber HSS/Cx test double. It exercises real MAR/MAA message construction, Cx correlation, AKA response verification, replay rejection, registration bindings, and the S-CSCF session gate. It is not a substitute for interoperability testing against an external HSS/UDM, UE, or media system.

`tests/ims_aka_test.mko` explicitly covers missing vectors, malformed AKA
credentials, replay rejection, an expired cached vector, and the cluster
contract that a sibling node holding no local vector re-challenges instead of
accepting or hard-failing (vectors remain node-local secrets). The expiration
check validates the worker-side bounded XRES cache; vector generation and
lifetime policy remain HSS/UDM responsibilities.

`tests/rtpengine_test.mko` validates RTPEngine ng offer/answer/delete command shape, including Call-ID and dialog-tag correlation, plus control-character and length bounds on tags. With `SIP_RTPENGINE_TEST_NETWORK=1`, it also runs a local UDP ng-shaped responder and exercises the production client path end to end: offer/answer SDP replacement, delete acknowledgement, malformed-response rejection, and no-responder timeout failure. It does not replace interoperability testing against a real RTPEngine, RTP, ICE, or DTLS-SRTP endpoint.

The same suite covers the RTPEngine SDP boundary: content-type checks, required `v=0` and `m=` lines, and body-size bounds. The production gate also scans every body byte for NULs before sending it to RTPEngine.

`tests/ims_session_timer_test.mko` covers the opt-in RFC 4028 request boundary: valid `Session-Expires` parameters, effective `Min-SE` handling, configured maximums, duplicate headers, malformed refresher values, quoted parameters, and control-character rejection. It does not prove endpoint refresh or external-stack interoperability.

`tests/ims_identity_test.mko` covers disabled compatibility behavior, untrusted asserted/preferred identity stripping, trusted single-identity validation, duplicate/list rejection, and `Privacy: id` outbound filtering. It does not prove full RFC 3325/RFC 8224 interoperability or identity assertion generation.

`tests/ims_path_test.mko` covers optional P-CSCF Path insertion, replacement of UE-supplied Path headers, `sip:`/`sips:` URI validation, and rejection of lists, control characters, and embedded name-addr values. It does not prove dynamic Path discovery, flow-token management, or multi-hop interoperability.

`tests/ims_registration_test.mko` covers the optional local-S-CSCF Service-Route and P-Associated-URI response values, `sip:`/`sips:` URI validation, and rejection of lists, control characters, embedded name-addr values, and unsupported schemes.

`tests/ims_subscriber_test.mko` covers the versioned authorization envelope, fail-closed identity/assignment checks, and bounded `service_profile.associated_uris` extraction. It does not prove external HSS/UDM interoperability or iFC/TAS execution.

`tests/ims_ifc_test.mko` covers target-only `service_profile.initial_filter_criteria` extraction, four-target and uniqueness limits, SIP/SIPS target validation, unsafe delimiter rejection, malformed array elements, structured criteria (priority, method, session_case, default_handling), originating/terminating live-registration guards, final-binding expiry reconciliation, outbound `Privacy: id` filtering for AS forks, clearing of stored triggers, third-party REGISTER builder identity derivation (`SIP_IMS_SERVER_NAME`/`SIP_REALM`, never hardcoded), and the Via-branch guard that keeps worker-originated 3pREG responses local. It does not prove standard iFC condition evaluation or TAS behavior. Worker-originated 3pREG delivery to AS targets, local response consumption, and the authenticated-fork session are covered by the opt-in worker smoke (`IMS_END_TO_END_FORK=1`).

`tests/bind_config_test.mko` covers `SIP_BIND_IP` parsing: wildcard default, configured IPv4 literals, trimming, and fail-back-to-wildcard on invalid values. It does not prove interface binding on a multi-homed host.

`tests/https_client_test.mko` covers the Mako HTTPS client (`madis_https.mko`, built on the runtime TLS pool) envelope ("status|body") parsing and, with `MADIS_HTTPS_TEST_URL`/`MADIS_HTTPS_TEST_CA`/`MADIS_HTTPS_TEST_TOKEN` set, a live authenticated HTTPS POST including bearer delivery, DNS resolution, hostname verification, and fail-closed behavior with a wrong CA. TLS endpoints must use DNS names. It does not replace interoperability testing against the production subscriber/charging/application endpoints.

| Test | Coverage |
| --- | --- |
| `tests/admin_http_test.mko` | HTTP framing, cookie boundaries, form decoding, and Origin checks. |
| `tests/adversarial_test.mko` | Malformed headers, framing, injection, limits, status handling, and SIP URI validation. |
| `tests/app_gateway_test.mko` | Signed application/module commands, header boundaries, SQL-shaped data, and module allowlists. |
| `tests/auth_test.mko` | Digest parameters, qop, MD5/SHA-256, `-sess`, and bounded attacker caches. |
| `tests/b2bua_test.mko` | Independent B2BUA legs, dialog translation, cleanup, and header safety. |
| `tests/carrier_contract_test.mko` | Billing identity/escaping, control API routes, validation, and resource allowlists. |
| `tests/diameter_codec_test.mko` | Diameter headers, AVPs, grouping, malformed input, Cx/Sh correlation, and credit-control fields. |
| `tests/diameter_failover_test.mko` | Multi-peer list parsing, failover rotation, backoff/inflight bounds, and realm-pinned peer selection (`realm@host:port`) with Destination-Realm extraction from the request. |
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
implemented IMS boundary. It builds separate Mako `v0.5.0` P-/I-/S-CSCF
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

- [ ] `scripts/ci.sh` passes with Mako 0.5.0.
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
is linked explicitly with Mako 0.5.0:

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
# Cx MAR multi-vector + AUTS lab evidence (included in discover above):
# python3 -m unittest lab.test_ims_hss.HssAdapterTests.test_mar_multi_vector_count \
#   lab.test_ims_hss.HssAdapterTests.test_mar_auts_resync_requires_issued_rand -v

# Listener tests: Diameter TCP and HTTP authorization/provisioning
IMS_HSS_TEST_NETWORK=1 python3 -m unittest discover -s lab -p 'test_*.py'

# Diameter and HTTPS TLS listeners with ephemeral certificates
IMS_HSS_TEST_TLS=1 python3 -m unittest \
  lab.test_ims_hss.HssDiameterTlsWireTests \
  lab.test_ims_hss.HssHttpsWireTests -v

# Full worker-backed two-subscriber IMS smoke with a local S-CSCF and external RTP sidecar
IMS_END_TO_END=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end -v

# Target-only iFC fork selection and losing-branch CANCEL cleanup
IMS_END_TO_END=1 IMS_END_TO_END_FORK=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_ifc_fork_selects_branch_and_cancels_loser -v

# Client INVITE Timer C / 408 timeout
IMS_END_TO_END=1 IMS_END_TO_END_TIMEOUT=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end.TwoSubscriberImsSmokeTests.test_unanswered_invite_times_out -v

# The same call with Diameter TLS and an ephemeral HSS certificate
IMS_END_TO_END=1 IMS_END_TO_END_TLS=1 MADIS_BIN=/path/to/madis \
  python3 -m unittest lab.test_ims_end_to_end -v
```

The HSS tests cover Cx answer construction, unknown-subscriber and serving-
server rejection, opaque vector handling, malformed Diameter requests being
dropped without an answer, and the rule that HTTP subscriber authorization
never returns XRES. The media tests cover bounded ng control,
SDP rewriting, offer/answer/delete lifecycle, malformed input rejection,
capacity-exhaustion rejection, and control-listener restart recovery.
localhost RTP forwarding. The worker-backed test additionally verifies that
standalone `SIP_RTPENGINE_*` configuration reaches the call path, that both
SDP legs are rewritten, and that RTP crosses the sidecar in both directions.
It also has an opt-in HSS-unavailable case that requires the worker to fail
closed with SIP `503`; it is skipped unless a built worker is supplied. The
Docker profile extends that same contract across separate P-/I-/S-CSCF
workers and uses Cx LIR to select the S-CSCF. These tests are lab-contract
evidence; they do not replace tests against real UEs, HSS/UDM systems,
RTPEngine deployments, or media/security profiles.
