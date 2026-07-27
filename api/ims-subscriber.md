# IMS subscriber authorization contract

Madis can optionally ask an external subscriber service to authorize an IMS REGISTER. The service owns subscriber identities, IMS AKA material, profiles, and assignment state. Madis does not store or return AKA secrets.

The adapter is disabled unless `SIP_IMS_SUBSCRIBER_URL` is configured. When configured, it requires an HTTPS URL and a bearer token of at least 16 characters. Any URL, TLS, HTTP, timeout, malformed-response, identity-mismatch, or non-`allow` result denies the REGISTER.

The repository now includes a database-backed provider in the standalone admin process. Point the client URL at `/admin/api/v1/ims/subscriber/authorize` when using that provider. It currently owns identity authorization, assigned S-CSCF, and service-profile data; AKA vector generation remains the responsibility of the HSS/UDM. SIP AKA REGISTER, when enabled, uses the separate Cx MAR/MAA boundary documented in [`ims-diameter.md`](ims-diameter.md).

The JSON schema is [`ims-subscriber.schema.json`](ims-subscriber.schema.json). The request and response use the same schema identifier:

```text
madis.ims.subscriber.authorization.v1
```

## Request

```json
{
  "schema": "madis.ims.subscriber.authorization.v1",
  "operation": "authorize-register",
  "request_id": "stable-32-character-hash",
  "public_identity": "sip:alice@example.com",
  "private_identity": "alice@example.com",
  "visited_network": "example.com",
  "server_name": "sip:scscf.example.com"
}
```

`request_id` is deterministic for the identity and registration context, so retries of the same authorization request can be deduplicated by the subscriber service.

## Response

```json
{
  "schema": "madis.ims.subscriber.authorization.v1",
  "operation": "authorize-register",
  "request_id": "stable-32-character-hash",
  "public_identity": "sip:alice@example.com",
  "private_identity": "alice@example.com",
  "decision": "allow",
  "assigned_server_name": "sip:scscf.example.com",
  "service_profile": {}
}
```

Madis requires the schema, operation, request ID, public identity, private identity, and `decision` to match the request. `decision` must be `allow`; all other responses fail closed. An allow response must include `assigned_server_name`, and it must exactly match the S-CSCF requested by the worker. Dynamic S-CSCF selection is not implemented yet; the assignment is currently an integrity binding for the configured role.

## Configuration

```text
SIP_IMS_SUBSCRIBER_URL=https://subscriber.example.net/ims/authorize
SIP_IMS_SUBSCRIBER_TOKEN=<server-side bearer token>
SIP_IMS_SUBSCRIBER_CA=<optional CA bundle or deployment trust path>
SIP_IMS_SUBSCRIBER_TIMEOUT_MS=250
```

The service should be private-network reachable, use operator-managed TLS, and never log the private identity or bearer token. This adapter complements the existing optional Cx UAR/SAR gate; if both are enabled, both authorization gates must succeed.

## Provisioning

Provision or update a subscriber through the control token. This endpoint does not accept AKA secrets:

```http
POST /admin/api/v1/control/ims/subscribers
Authorization: Bearer <SIP_CONTROL_API_TOKEN>
Content-Type: application/json
```

```json
{
  "schema": "madis.ims.subscriber.provision.v1",
  "operation": "provision",
  "public_identity": "sip:alice@example.com",
  "private_identity": "alice@example.com",
  "realm": "example.com",
  "assigned_server_name": "sip:scscf.example.com",
  "service_profile": {
    "initial_filter_criteria": []
  }
}
```

Provisioning is an upsert keyed by the public/private identity pair. It is intended for the lab profile; production deployments still need protected AKA storage, vector lifecycle, auditing, and subscriber-provisioning workflows.
