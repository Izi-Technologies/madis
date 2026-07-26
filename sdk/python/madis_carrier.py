"""Small standard-library client for the Madis carrier API."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MadisCarrier:
    def __init__(self, base_url, token, timeout=2.0):
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _request(self, method, path, body=None):
        data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
        if data is not None and len(data) > 65536:
            raise ValueError("event body exceeds Madis 64 KiB limit")
        headers = {"Authorization": f"Bearer {self.token}", "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        req = Request(self.base_url + path, data=data, headers=headers, method=method)
        with urlopen(req, timeout=self.timeout) as res:
            return json.loads(res.read())

    def capabilities(self):
        return self._request("GET", "/api/v1/capabilities")

    def pending_events(self, limit=100):
        return self._request("GET", "/api/v1/billing/events?" + urlencode({"limit": min(max(limit, 1), 100)}))

    def publish(self, event):
        return self._request("POST", "/api/v1/billing/events", event)

    def ack(self, event_id):
        return self._request("POST", "/api/v1/billing/events/ack?" + urlencode({"event_id": event_id}))
