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
