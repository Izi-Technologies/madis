"""Standard-library client example for the Madis carrier API."""
import json
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class MadisCarrier:
    CONTROL_RESOURCES = {
        "gateways", "routes", "dispatch-sets", "dispatch-members", "dids",
        "header-rules", "access-control", "security-bans", "ani-groups",
        "ani-ranges", "registrations", "registration-bindings",
        "cluster-nodes", "security-events",
    }

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

    def cdr(self, limit=100, call_id=None):
        query = {"limit": min(max(limit, 1), 100)}
        if call_id:
            query["call_id"] = call_id
        return self._request("GET", "/api/v1/billing/cdr?" + urlencode(query))

    def control_status(self):
        return self._request("GET", "/api/v1/control/status")

    def routing_rules(self, limit=100):
        return self._request("GET", "/api/v1/control/routing-rules?" + urlencode({"limit": min(max(limit, 1), 100)}))

    def create_routing_rule(self, rule):
        return self._request("POST", "/api/v1/control/routing-rules", rule)

    def enable_routing_rule(self, rule_id):
        return self._request("POST", f"/api/v1/control/routing-rules/{int(rule_id)}/enable")

    def disable_routing_rule(self, rule_id):
        return self._request("POST", f"/api/v1/control/routing-rules/{int(rule_id)}/disable")

    def dialplans(self, limit=100):
        return self._request("GET", "/api/v1/control/dialplans?" + urlencode({"limit": min(max(limit, 1), 100)}))

    def create_dialplan(self, rule):
        return self._request("POST", "/api/v1/control/dialplans", rule)

    def set_dialplan_enabled(self, rule_id, enabled):
        state = "enable" if enabled else "disable"
        return self._request("POST", f"/api/v1/control/dialplans/{int(rule_id)}/{state}")

    def update_dialplan(self, rule_id, rule):
        return self._request("PUT", f"/api/v1/control/dialplans/{int(rule_id)}", rule)

    def delete_dialplan(self, rule_id):
        return self._request("DELETE", f"/api/v1/control/dialplans/{int(rule_id)}")

    def _resource_path(self, resource):
        if resource not in self.CONTROL_RESOURCES:
            raise ValueError("resource is not in the Madis control allowlist")
        return "/api/v1/control/resources/" + resource

    def control_resources(self, resource, limit=100):
        path = self._resource_path(resource)
        return self._request("GET", path + "?" + urlencode({"limit": min(max(limit, 1), 100)}))

    def create_control_resource(self, resource, document):
        return self._request("POST", self._resource_path(resource), document)

    def update_control_resource(self, resource, resource_id, document):
        return self._request("PUT", f"{self._resource_path(resource)}/{int(resource_id)}", document)

    def delete_control_resource(self, resource, resource_id, expected_revision=None):
        path = f"{self._resource_path(resource)}/{int(resource_id)}"
        if expected_revision:
            path += "?" + urlencode({"expected_revision": expected_revision})
        return self._request("DELETE", path)

    def set_control_resource_enabled(self, resource, resource_id, enabled):
        state = "enable" if enabled else "disable"
        return self._request("POST", f"{self._resource_path(resource)}/{int(resource_id)}/{state}")

    def validate_routing_rule(self, rule):
        return self._request("POST", "/api/v1/control/validate/routing-rule", rule)

    def validate_dialplan(self, rule):
        return self._request("POST", "/api/v1/control/validate/dialplan", rule)
