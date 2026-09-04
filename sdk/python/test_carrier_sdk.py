import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
from madis_carrier import MadisCarrier  # noqa: E402


class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status = status
        self._payload = json.dumps(payload or {"ok": True}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class CarrierSdkUnitTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.client = MadisCarrier("https://proxy.example.net/admin", "carrier-token-1234567890")
        self.urlopen = patch("madis_carrier.urlopen", side_effect=self.fake_urlopen)
        self.urlopen.start()

    def tearDown(self):
        self.urlopen.stop()

    def fake_urlopen(self, request, timeout):
        body = None if request.data is None else json.loads(request.data)
        self.records.append((request.method, request.full_url, dict(request.headers), body, timeout))
        return FakeResponse(200, {"ok": True, "count": 1})

    def test_all_carrier_operations(self):
        # 1. Basic capabilities & billing
        self.client.capabilities()
        self.client.pending_events(limit=50)
        self.client.publish({"event_type": "cdr.lifecycle"})
        self.client.ack("evt-1234")
        self.client.cdr(limit=25, call_id="call-1")

        # 2. Control status & routing rules
        self.client.control_status()
        self.client.routing_rules(limit=100)
        self.client.create_routing_rule({"action": "gateway", "prefix": "1"})
        self.client.enable_routing_rule(1)
        self.client.disable_routing_rule(1)

        # 3. Dialplans
        self.client.dialplans(limit=10)
        self.client.create_dialplan({"match": "^9", "strip": 1})
        self.client.set_dialplan_enabled(2, True)
        self.client.set_dialplan_enabled(2, False)
        self.client.update_dialplan(2, {"strip": 2})
        self.client.delete_dialplan(2)

        # 4. Generic control resources
        self.client.control_resources("gateways", limit=50)
        self.client.create_control_resource("gateways", {"name": "gw-1"})
        self.client.update_control_resource("gateways", 5, {"port": 5080})
        self.client.delete_control_resource("gateways", 5, expected_revision="rev-1")
        self.client.set_control_resource_enabled("gateways", 5, True)

        # 5. Validations
        self.client.validate_routing_rule({"prefix": "44"})
        self.client.validate_dialplan({"match": "^0"})

        self.assertEqual(len(self.records), 23)
        for _, _, headers, _, _ in self.records:
            self.assertEqual(headers["Authorization"], "Bearer carrier-token-1234567890")

    def test_invalid_resource_rejected(self):
        with self.assertRaises(ValueError):
            self.client.control_resources("unknown_resource")


if __name__ == "__main__":
    unittest.main()
