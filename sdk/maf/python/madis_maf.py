"""Small standard-library client for the MADIS Application Fabric (MAF)."""

from __future__ import annotations

import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


MAF_VERSION = "0.7.0"
"""Protocol version sent as X-MAF-Version on every request.

The server may reject requests with an unsupported version.  Bump this
constant only when the contract (schemas, routes, required fields) changes
in a way that requires coordinated SDK and server updates."""


class MafError(RuntimeError):
    """HTTP or contract failure returned by the MAF endpoint."""

    def __init__(self, status: int, payload: object):
        super().__init__(f"MAF request failed with HTTP {status}: {payload}")
        self.status = status
        self.payload = payload


class MadisMaf:
    """Bearer-authenticated MAF HTTP client.

    Put the admin listener behind the deployment's HTTPS/mTLS edge. The
    client deliberately sends only the MAF bearer credential to the MAF route;
    it never places that credential in URLs or SIP messages.
    """

    def __init__(self, base_url: str, token: str, timeout: float = 5.0):
        if not base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must use HTTP or HTTPS")
        if len(token) < 16 or len(token) > 512:
            raise ValueError("MAF token must be 16..512 characters")
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: object | None = None,
                 query: dict[str, object] | None = None,
                 idempotency_key: str | None = None) -> object:
        if query:
            path += "?" + urlencode(query)
        payload = None if body is None else json.dumps(
            body, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
        if payload is not None and len(payload) > 65536:
            raise ValueError("MAF request body exceeds 64 KiB")
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "X-MAF-Version": MAF_VERSION,
        }
        if payload is not None:
            headers["Content-Type"] = "application/json"
        if idempotency_key is not None:
            headers["Idempotency-Key"] = idempotency_key
        request = Request(self.base_url + path, data=payload,
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                status = response.status
                raw = response.read()
        except HTTPError as error:
            raw = error.read()
            raise MafError(error.code, self._decode(raw)) from error
        except URLError as error:
            raise MafError(0, str(error.reason)) from error
        decoded = self._decode(raw)
        if status < 200 or status >= 300:
            raise MafError(status, decoded)
        return decoded

    @staticmethod
    def _decode(raw: bytes) -> object:
        if not raw:
            return None
        text = raw.decode("utf-8", errors="replace")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    @staticmethod
    def _key(value: str | None) -> str:
        return value or uuid.uuid4().hex

    def _command(self, method: str, path: str, body: dict[str, object],
                 idempotency_key: str | None) -> object:
        key = self._key(idempotency_key)
        body = dict(body)
        body.setdefault("command_id", key)
        return self._request(method, path, body, idempotency_key=key)

    def create_call(self, from_uri: str, to_uri: str,
                    application_data: dict[str, object] | None = None,
                    idempotency_key: str | None = None) -> object:
        body: dict[str, object] = {"from": from_uri, "to": to_uri}
        if application_data is not None:
            body["application_data"] = application_data
        return self._command("POST", "/api/v1/maf/calls", body, idempotency_key)

    def get_call(self, call_id: str) -> object:
        return self._request("GET", f"/api/v1/maf/calls/{quote(call_id, safe='')}")

    def answer_call(self, call_id: str, answer_sdp: str,
                    idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/answer",
                             {"answer_sdp": answer_sdp}, idempotency_key)

    def reject_call(self, call_id: str, sip_code: int | None = None,
                    reason: str | None = None,
                    idempotency_key: str | None = None) -> object:
        body: dict[str, object] = {}
        if sip_code is not None:
            body["sip_code"] = sip_code
        if reason is not None:
            body["reason"] = reason
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/reject",
                             body, idempotency_key)

    def hangup_call(self, call_id: str, reason: str | None = None,
                    idempotency_key: str | None = None) -> object:
        body = {} if reason is None else {"reason": reason}
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/hangup",
                             body, idempotency_key)

    def bridge_call(self, call_id: str, channel_ids: list[str],
                    idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/bridges",
                             {"channel_ids": channel_ids}, idempotency_key)

    def media(self, call_id: str, operation: str, resource: str | None = None,
              idempotency_key: str | None = None) -> object:
        body: dict[str, object] = {"operation": operation}
        if resource is not None:
            body["resource"] = resource
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/media",
                             body, idempotency_key)

    def set_headers(self, call_id: str, headers: list[dict[str, object]],
                    idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/headers",
                             {"headers": headers}, idempotency_key)

    def transfer_call(self, call_id: str, target: str,
                      transfer_type: str = "blind",
                      other_call_id: str | None = None,
                      idempotency_key: str | None = None) -> object:
        body: dict[str, object] = {"target": target, "type": transfer_type}
        if other_call_id is not None:
            body["other_call_id"] = other_call_id
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/transfer",
                             body, idempotency_key)

    def hold_call(self, call_id: str,
                  idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/hold",
                             {}, idempotency_key)

    def unhold_call(self, call_id: str,
                    idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/unhold",
                             {}, idempotency_key)

    def send_dtmf(self, call_id: str, digit: str, duration: int = 250,
                  idempotency_key: str | None = None) -> object:
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/dtmf",
                             {"digit": digit, "duration": duration}, idempotency_key)

    def identity(self, call_id: str, action: str,
                 identity: str | None = None,
                 attest: str | None = None,
                 idempotency_key: str | None = None) -> object:
        """STIR/SHAKEN identity control for external signing services.

        Actions:
          sign   — attach a pre-signed Identity header from an external STI service
          verify — get the verification result for an inbound call
          attest — set attestation level (A/B/C)
          clear  — remove Identity headers
        """
        body: dict[str, object] = {"action": action}
        if identity is not None:
            body["identity"] = identity
        if attest is not None:
            body["attest"] = attest
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/identity",
                             body, idempotency_key)

    def rtp_control(self, call_id: str, action: str,
                    sdp: str | None = None,
                    from_tag: str | None = None,
                    to_tag: str | None = None,
                    flags: str | None = None,
                    idempotency_key: str | None = None) -> object:
        body: dict[str, object] = {"action": action}
        if sdp is not None:
            body["sdp"] = sdp
        if from_tag is not None:
            body["from_tag"] = from_tag
        if to_tag is not None:
            body["to_tag"] = to_tag
        if flags is not None:
            body["flags"] = flags
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/rtp",
                             body, idempotency_key)

    def route_call(self, call_id: str, target: str,
                   transport: str | None = None,
                   idempotency_key: str | None = None) -> object:
        body = {"target": target}
        if transport is not None:
            body["transport"] = transport
        return self._command("POST", f"/api/v1/maf/calls/{quote(call_id, safe='')}/route",
                             body, idempotency_key)

    def publish_event(self, event_type: str, call_id: str = "",
                      payload: object = None) -> object:
        body: dict[str, object] = {"event_type": event_type}
        if call_id:
            body["call_id"] = call_id
        if payload is not None:
            body["payload"] = json.dumps(payload) if not isinstance(payload, str) else payload
        return self._request("POST", "/api/v1/maf/events", body=body)

    def registrations(self, aor: str | None = None, limit: int = 100) -> object:
        query: dict[str, object] = {"limit": min(max(limit, 1), 100)}
        if aor is not None:
            query["aor"] = aor
        return self._request("GET", "/api/v1/maf/registrations", query=query)

    def cdr(self, call_id: str | None = None, limit: int = 50) -> object:
        query: dict[str, object] = {"limit": min(max(limit, 1), 100)}
        if call_id is not None:
            query["call_id"] = call_id
        return self._request("GET", "/api/v1/maf/cdr", query=query)

    def bans(self) -> object:
        return self._request("GET", "/api/v1/maf/security/bans")

    def ban_ip(self, source_ip: str, reason: str = "",
               permanent: bool = False, duration_min: int = 60) -> object:
        body: dict[str, object] = {"source_ip": source_ip, "reason": reason,
                                    "permanent": "true" if permanent else "false",
                                    "duration_min": duration_min}
        return self._request("POST", "/api/v1/maf/security/bans", body=body)

    def unban_ip(self, source_ip: str) -> object:
        return self._request("DELETE", f"/api/v1/maf/security/bans/{quote(source_ip, safe='')}")

    def sip_inspect(self, call_id: str) -> object:
        return self._request("GET", f"/api/v1/maf/calls/{quote(call_id, safe='')}/sip")

    def presence(self, aor: str | None = None, limit: int = 100) -> object:
        query: dict[str, object] = {"limit": min(max(limit, 1), 500)}
        if aor is not None:
            query["aor"] = aor
        return self._request("GET", "/api/v1/maf/presence", query=query)

    def presence_user(self, aor: str) -> object:
        return self._request("GET", f"/api/v1/maf/presence/{quote(aor, safe='')}")

    def routing_rules(self) -> object:
        return self._request("GET", "/api/v1/maf/routing/rules")

    def create_routing_rule(self, action: str, match_prefix: str = "",
                            priority: int = 10, **kwargs) -> object:
        body = {"action": action, "match_prefix": match_prefix,
                "priority": priority, **kwargs}
        return self._request("POST", "/api/v1/maf/routing/rules", body=body)

    def delete_routing_rule(self, rule_id: int) -> object:
        return self._request("DELETE", f"/api/v1/maf/routing/rules/{rule_id}")

    def gateways(self) -> object:
        return self._request("GET", "/api/v1/maf/gateways")

    def create_gateway(self, name: str, address: str, port: int = 5060,
                       transport: str = "UDP") -> object:
        return self._request("POST", "/api/v1/maf/gateways",
                             body={"name": name, "address": address,
                                   "port": port, "transport": transport})

    def dids(self) -> object:
        return self._request("GET", "/api/v1/maf/dids")

    def create_did(self, number: str, destination_user: str,
                   description: str = "") -> object:
        return self._request("POST", "/api/v1/maf/dids",
                             body={"number": number,
                                   "destination_user": destination_user,
                                   "description": description})

    def dispatch_sets(self) -> object:
        return self._request("GET", "/api/v1/maf/dispatch-sets")

    def create_dispatch_set(self, name: str,
                            algorithm: str = "round-robin") -> object:
        return self._request("POST", "/api/v1/maf/dispatch-sets",
                             body={"name": name, "algorithm": algorithm})

    def cluster(self) -> object:
        return self._request("GET", "/api/v1/maf/cluster")

    def config(self) -> object:
        return self._request("GET", "/api/v1/maf/config")

    def set_config(self, key: str, value: str,
                   description: str = "") -> object:
        return self._request("POST", "/api/v1/maf/config",
                             body={"key": key, "value": value,
                                   "description": description})

    def charge_authorize(self, call_id: str) -> object:
        return self._request("POST",
                             f"/api/v1/maf/calls/{quote(call_id, safe='')}/charge")

    def charge_deny(self, call_id: str) -> object:
        return self._request("POST",
                             f"/api/v1/maf/calls/{quote(call_id, safe='')}/charge-deny")

    def delete_did(self, did_id: int) -> object:
        return self._request("DELETE", f"/api/v1/maf/dids/{did_id}")

    def delete_gateway(self, gateway_id: int) -> object:
        return self._request("DELETE", f"/api/v1/maf/gateways/{gateway_id}")

    def dialplans(self) -> object:
        return self._request("GET", "/api/v1/maf/dialplans")

    def create_dialplan(self, **kwargs) -> object:
        return self._request("POST", "/api/v1/maf/dialplans", body=kwargs)

    def delete_dialplan(self, dialplan_id: int) -> object:
        return self._request("DELETE", f"/api/v1/maf/dialplans/{dialplan_id}")

    def ip_auth(self) -> object:
        return self._request("GET", "/api/v1/maf/ip-auth")

    def create_ip_auth(self, ip: str, description: str = "") -> object:
        return self._request("POST", "/api/v1/maf/ip-auth",
                             body={"ip": ip, "description": description})

    def delete_ip_auth(self, ip_auth_id: int) -> object:
        return self._request("DELETE", f"/api/v1/maf/ip-auth/{ip_auth_id}")

    def access_control(self) -> object:
        return self._request("GET", "/api/v1/maf/access-control")

    def create_access_control(self, rule: str, source: str,
                              description: str = "") -> object:
        return self._request("POST", "/api/v1/maf/access-control",
                             body={"rule": rule, "source": source,
                                   "description": description})

    def header_rules(self) -> object:
        return self._request("GET", "/api/v1/maf/header-rules")

    def create_header_rule(self, action: str, name: str, **kwargs) -> object:
        return self._request("POST", "/api/v1/maf/header-rules",
                             body={"action": action, "name": name, **kwargs})

    def billing_events(self) -> object:
        return self._request("GET", "/api/v1/maf/billing/events")

    def billing_ack(self, event_ids: list[str]) -> object:
        return self._request("POST", "/api/v1/maf/billing/events/ack",
                             body={"event_ids": event_ids})

    def security_events(self) -> object:
        return self._request("GET", "/api/v1/maf/security/events")

    def ani_groups(self) -> object:
        return self._request("GET", "/api/v1/maf/ani-groups")

    def create_ani_group(self, name: str, numbers: list[str]) -> object:
        return self._request("POST", "/api/v1/maf/ani-groups",
                             body={"name": name, "numbers": numbers})

    def active_calls(self) -> object:
        return self._request("GET", "/api/v1/maf/calls/active")

    def create_dispatch_member(self, dispatch_set_id: int, gateway_id: int,
                               weight: int = 100, priority: int = 1) -> object:
        return self._request("POST", "/api/v1/maf/dispatch-members",
                             body={"dispatch_set_id": dispatch_set_id,
                                   "gateway_id": gateway_id,
                                   "weight": weight, "priority": priority})

    def events(self, cursor: int = 0, event_type: str | None = None,
               limit: int = 100) -> object:
        query: dict[str, object] = {"cursor": max(cursor, 0),
                                    "limit": min(max(limit, 1), 100)}
        if event_type is not None:
            query["event_type"] = event_type
        return self._request("GET", "/api/v1/maf/events", query=query)

    def subscribe(self, cursor: int = 0, event_type: str | None = None,
                  call_id: str | None = None, poll_ms: float = 0.2,
                  max_poll_ms: float = 2.0):
        """Yield events as they arrive using HTTP long-poll with adaptive backoff.

        This is a blocking generator that polls the /events endpoint.
        For true WebSocket streaming, connect directly to
        /admin/api/v1/maf/events/ws with a WebSocket library.

        Usage:
            for event in client.subscribe(event_type="call.answered"):
                print(event["event_type"], event["call_id"])
        """
        import time
        cur = max(cursor, 0)
        interval = poll_ms
        while True:
            try:
                query: dict[str, object] = {"cursor": cur, "limit": 100}
                if event_type is not None:
                    query["event_type"] = event_type
                if call_id is not None:
                    query["call_id"] = call_id
                page = self._request("GET", "/api/v1/maf/events", query=query)
                events = page.get("events", []) if isinstance(page, dict) else []
                if events:
                    interval = poll_ms
                    for evt in events:
                        yield evt
                    next_cur = page.get("next_cursor", cur)
                    if isinstance(next_cur, str):
                        next_cur = int(next_cur)
                    if next_cur > cur:
                        cur = next_cur
                else:
                    interval = min(interval * 2, max_poll_ms)
            except MafError:
                interval = max_poll_ms
            time.sleep(interval)

    def ws_url(self, cursor: int = 0, event_type: str | None = None,
               call_id: str | None = None) -> str:
        """Build the WebSocket URL for direct connection with a WS library.

        Usage with websockets (pip install websockets):
            import websockets, asyncio, json
            async def stream():
                url = client.ws_url(event_type="call.answered")
                async with websockets.connect(url,
                    extra_headers={"Authorization": f"Bearer {client.token}"}
                ) as ws:
                    async for msg in ws:
                        print(json.loads(msg))
        """
        base = self.base_url.replace("http://", "ws://").replace("https://", "wss://")
        params: dict[str, object] = {"cursor": max(cursor, 0)}
        if event_type is not None:
            params["event_type"] = event_type
        if call_id is not None:
            params["call_id"] = call_id
        return base + "/api/v1/maf/events/ws?" + urlencode(params)
