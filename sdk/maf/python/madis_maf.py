"""Small standard-library client for the MADIS Application Fabric (MAF)."""

from __future__ import annotations

import json
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


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

    def events(self, cursor: int = 0, event_type: str | None = None,
               limit: int = 100) -> object:
        query: dict[str, object] = {"cursor": max(cursor, 0),
                                    "limit": min(max(limit, 1), 100)}
        if event_type is not None:
            query["event_type"] = event_type
        return self._request("GET", "/api/v1/maf/events", query=query)
