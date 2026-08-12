"""Integration tests for the Madis carrier SDK against a live proxy.

Run with:
    MADIS_URL=http://127.0.0.1:9090 \
    MADIS_TOKEN=<admin-token> \
    python3 -m pytest sdk/python/test_integration.py -v

Requires a running Madis proxy with SIP_ADMIN_PORT=9090 and SIP_ADMIN_TOKEN set.
Skips automatically if MADIS_URL is not set.
"""
import json
import os
import sys
import unittest
from urllib.error import HTTPError, URLError

sys.path.insert(0, os.path.dirname(__file__))
from madis_carrier import MadisCarrier


MADIS_URL = os.environ.get("MADIS_URL", "")
MADIS_TOKEN = os.environ.get("MADIS_TOKEN", "")


def skip_if_no_proxy():
    if not MADIS_URL or not MADIS_TOKEN:
        raise unittest.SkipTest("MADIS_URL and MADIS_TOKEN required")


class TestHealthEndpoints(unittest.TestCase):
    def setUp(self):
        skip_if_no_proxy()
        self.client = MadisCarrier(MADIS_URL, MADIS_TOKEN)

    def test_healthz(self):
        resp = self.client._request("GET", "/healthz")
        self.assertTrue(resp["ok"])
        self.assertIn("version", resp)
        self.assertIn("calls", resp)
        self.assertIsInstance(resp["calls"], int)

    def test_readyz(self):
        resp = self.client._request("GET", "/readyz")
        self.assertTrue(resp["ready"])

    def test_state(self):
        resp = self.client._request("GET", "/state")
        self.assertIn("registrations", resp)
        self.assertIn("calls", resp)
        self.assertIn("cache", resp)

    def test_metrics_returns_prometheus(self):
        from urllib.request import Request, urlopen
        req = Request(
            MADIS_URL.rstrip("/") + "/metrics",
            headers={"Authorization": f"Bearer {MADIS_TOKEN}"},
        )
        with urlopen(req, timeout=5) as res:
            body = res.read().decode()
            self.assertIn("sip_messages_total", body)

    def test_unauthorized_rejected(self):
        bad_client = MadisCarrier(MADIS_URL, "wrong-token-value-here1234567890")
        with self.assertRaises(HTTPError) as ctx:
            bad_client._request("GET", "/healthz")
        self.assertEqual(ctx.exception.code, 401)


class TestReloadEndpoint(unittest.TestCase):
    def setUp(self):
        skip_if_no_proxy()
        self.client = MadisCarrier(MADIS_URL, MADIS_TOKEN)

    def test_reload(self):
        resp = self.client._request("POST", "/reload")
        self.assertTrue(resp.get("reloaded"))
        self.assertIn("epoch", resp)
        self.assertIsInstance(resp["epoch"], int)

    def test_reload_get_rejected(self):
        with self.assertRaises(HTTPError) as ctx:
            self.client._request("GET", "/reload")
        self.assertEqual(ctx.exception.code, 405)


class TestCapabilities(unittest.TestCase):
    def setUp(self):
        skip_if_no_proxy()
        self.client = MadisCarrier(MADIS_URL, MADIS_TOKEN)

    def test_capabilities(self):
        try:
            resp = self.client.capabilities()
            self.assertIn("version", resp)
        except HTTPError as e:
            # 404 is acceptable if carrier API is on the admin process
            if e.code != 404:
                raise


class TestControlResources(unittest.TestCase):
    def setUp(self):
        skip_if_no_proxy()
        self.client = MadisCarrier(MADIS_URL, MADIS_TOKEN)

    def test_resource_allowlist(self):
        for resource in ["gateways", "routes", "dids", "access-control"]:
            try:
                resp = self.client.control_resources(resource, limit=1)
                self.assertIsInstance(resp, dict)
            except HTTPError as e:
                if e.code not in (404, 503):
                    raise

    def test_invalid_resource_rejected(self):
        with self.assertRaises(ValueError):
            self.client.control_resources("users")  # not in allowlist


class TestSDKBoundaryValidation(unittest.TestCase):
    """Verify the SDK enforces client-side limits."""

    def setUp(self):
        skip_if_no_proxy()
        self.client = MadisCarrier(MADIS_URL, MADIS_TOKEN)

    def test_body_size_limit(self):
        big_event = {"data": "x" * 70000}
        with self.assertRaises(ValueError) as ctx:
            self.client.publish(big_event)
        self.assertIn("64 KiB", str(ctx.exception))

    def test_resource_id_is_int(self):
        with self.assertRaises((ValueError, TypeError)):
            self.client.update_control_resource("gateways", "not-a-number", {})


if __name__ == "__main__":
    unittest.main()
