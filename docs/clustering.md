# Active-active SIP clustering

Madis clustering is an active-active edge pattern. Each SIP worker owns its
listeners, transaction/dialog maps, and local `CMap` state. PostgreSQL is the
shared authority for registrations, routing policy, cluster membership, CDRs,
and durable outbox records; it is not a replica of in-flight SIP state.

## Recommended topology

```text
UEs / trunks
     |
SIP-aware L4 load balancer
  Call-ID/branch affinity for UDP
  connection affinity for TCP/TLS/WS/WSS
     |
  +--+------------------+
  |  active SIP workers |
  |  node-a ... node-n  |
  +--+------------------+
     |             |
 PostgreSQL     HEP collector
 shared state   UDP 9060 (optional)
```

Use an L4 device that preserves transaction affinity. Round-robin per UDP
datagram is unsafe: retransmissions, CANCEL, ACK, and responses can land on
different workers that do not share transaction state. TCP/TLS/WebSocket
connections must remain pinned to one worker for their lifetime.

Within a host, `SIP_UDP_WORKERS` enables bounded `SO_REUSEPORT` workers and
`SIP_TCP_WORKERS` controls stream workers. Across hosts, use distinct
`SIP_NODE_ID` values and unique `SIP_NODE_ADDR` values. The existing INVITE
fallback consults live `registration_bindings` plus a fresh `cluster_nodes`
heartbeat and fails closed when the owner is unavailable.

## AKA vectors across nodes

AKA authentication vectors (XRES, and CK/IK when `SIP_IMS_AKA_STORE_KEYS=1`)
are deliberately **node-local secrets**: they live only in the issuing worker's
bounded in-memory cache with `SIP_IMS_AKA_VECTOR_TTL_MS` lifetime and are never
written to PostgreSQL or shared between nodes. A UE whose authenticated
REGISTER lands on a node that did not issue the nonce receives a fresh
challenge (`401`, stale) from that node's own Cx MAR instead of a hard
rejection; registration completes one round trip later. Replay safety holds
per node and across nodes: a consumed vector cannot be replayed to the issuer,
and a sibling node has no XRES to validate against, so cross-node replay
cannot succeed either. Contract: `TestIMS_AKAClusterNodeRechallenge` in
`tests/ims_aka_test.mko`. Deployments that cannot tolerate the extra
round trip should pin REGISTER flows by source or Call-ID at the edge rather
than replicate secrets.

## Capacity rules

The requested scale point is an acceptance-test input, not a performance claim.
Validate it
with the real codec/media topology, database size, message mix, retransmission
rate, HEP collector, and TLS costs. Start with these guardrails:

- keep SIP workers close to stateless at the edge; do not add unbounded call
  state to `CMap`;
- size PostgreSQL connection pools, WAL, indexes, and `registration_bindings`
  separately from SIP packet workers;
- reserve file descriptors for persistent TCP/TLS/WSS associations and
  outbound transaction tables before increasing worker counts;
- benchmark normal calls, retransmissions, CANCEL storms, REGISTER refreshes,
  HEP enabled/disabled, and a failed HEP collector;
- scale HEP collectors independently and monitor capture loss; HEP is
  best-effort and must never become a SIP availability dependency;
- use rate limits and admission control before overload reaches the database.

The project must not be declared production-capable at a target CPS until a
repeatable benchmark records CPU, RSS, file descriptors, PostgreSQL latency,
SIP response/error rates, retransmission behavior, and HEP loss at that load.

## Failure boundaries

The current design intentionally fails closed for stale remote registration
ownership rather than routing a call to an expired contact. A worker restart
loses its local transaction/dialog state; the external load balancer and
database cannot reconstruct an in-flight SIP transaction. Planned HA work must
therefore include graceful drain, affinity-aware failover, and explicit
re-registration/recovery behavior rather than assuming PostgreSQL is a full
transaction-state replica.

## Compose cluster harness

[`docker-compose.cluster.yml`](../docker-compose.cluster.yml) starts two
Madis nodes on the private `madis-net` network and gives them unique node IDs
and addresses. It does not publish SIP ports: place a SIP-aware L4 load
balancer in front of `madis-node1` and `madis-node2`.

```sh
MADIS_DB_PASS=... \
MADIS_ADMIN_TOKEN=... \
MADIS_CARRIER_API_TOKEN=... \
MADIS_CONTROL_API_TOKEN=... \
MADIS_CONTROL_API_READ_TOKEN=... \
docker compose -f docker-compose.cluster.yml up --build
```

Set `MADIS_HEP_ENABLE=1` and `MADIS_HEP_HOST` when the nodes should export
HEPv3 to a collector. The harness is for topology and failover validation;
it is not a capacity certification or a substitute for a production SIP
load balancer.

## Graceful drain and rolling upgrade

1. Set `SIP_DRAIN=1` on the node leaving service (env or process restart with the flag).
2. New `REGISTER` and initial `INVITE` receive `503` with reason tag `drain`.
3. In-dialog requests (re-INVITE, BYE, ACK, PRACK, UPDATE) continue until natural teardown.
4. Wait for active dialogs to end (or operator max wait); monitor admin metrics / logs.
5. Stop the worker. Peer nodes serve new sessions; durable IMS lifecycle rows remain in Postgres.
6. Start the replacement binary/config with `SIP_DRAIN=0`. On boot, `ims_lifecycle_load_db` hydrates Path/Service-Route state for MT routing.
7. Optional: `SIP_IMS_LIFECYCLE_HSS_RECONCILE=1` re-SARs hydrated bindings and drops HSS denials.

Never force-push mid-dialog affinity: keep Call-ID affinity on the L4 balancer until drain completes.

## Multi-site disaster recovery (operator-owned)

Madis does not ship multi-region active-active product logic. Operators own:

| Concern | Owner |
| --- | --- |
| Postgres primary / replica / failover | DBA / cloud HA |
| DNS / anycast for SIP edge | Network ops |
| Diameter multi-peer HSS lists | `SIP_DIAMETER_HOSTS` per site |
| Secrets and TLS material | HSM / secret manager |
| Cross-site registration ownership | Shared DB + short registration TTL |

### Site-failure checklist

1. Fail over Postgres (promote replica). Point remaining Madis nodes at the new primary via `SIP_DB_URL`.
2. Ensure `cluster_nodes` heartbeats from surviving site; mark dead site nodes stale.
3. Re-point SIP load balancer / DNS to surviving edge.
4. Madis workers hydrate `ims_registrations` + `registration_bindings` from DB; UEs re-REGISTER if contacts expired.
5. Verify Cx to HSS (`SIP_DIAMETER_HOSTS` still reachable or use site-local HSS peers).
6. Record RTO/RPO measured against your Postgres and DNS design — not Madis alone.

### What Madis will not claim

- Automatic multi-region transaction recovery
- Shared in-memory dialog state across sites
- Zero call drop on hard site loss without UE re-REGISTER
