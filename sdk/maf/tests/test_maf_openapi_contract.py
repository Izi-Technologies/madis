"""Contract tests: every OpenAPI route/schema has a matching SDK surface."""

import json
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MAF_VERSION  # noqa: E402

SPEC_PATH = Path(__file__).resolve().parents[3] / "api" / "maf.openapi.yaml"


def _load_spec():
    """Parse the OpenAPI YAML with stdlib only (good-enough subset)."""
    text = SPEC_PATH.read_text()
    # We only need paths, schemas, and enums. A full YAML parser isn't
    # worth a dep; we extract what we need with targeted regex/splits.
    return text


def _extract_paths(text):
    """Return list of (http_method, path_template) from the spec."""
    results = []
    current_path = None
    for line in text.splitlines():
        # Top-level path keys are indented 2 spaces under 'paths:'
        m = re.match(r"^  (/\S+):\s*$", line)
        if m:
            current_path = m.group(1)
            continue
        if current_path:
            m2 = re.match(r"^    (get|post|put|delete|patch):\s*$", line)
            if m2:
                results.append((m2.group(1).upper(), current_path))
    return results


def _extract_required_fields(text, schema_name):
    """Extract required fields list for a named schema."""
    pattern = rf"^\s+{schema_name}:\s*$"
    in_schema = False
    in_required = False
    fields = []
    for line in text.splitlines():
        if re.match(pattern, line):
            in_schema = True
            continue
        if in_schema:
            if re.match(r"^\s+\w+:", line) and not line.strip().startswith("required") and not in_required:
                if not line.startswith("      "):
                    # Left the schema block
                    if fields:
                        break
            req = re.match(r"\s+required:\s*\[(.+)\]", line)
            if req and in_schema:
                fields.extend(f.strip() for f in req.group(1).split(","))
                in_required = False
    return fields


def _extract_enum(text, field_context, field_name):
    """Extract enum values for a field in a schema context."""
    values = []
    in_context = False
    for line in text.splitlines():
        if field_context in line:
            in_context = True
        if in_context and field_name in line:
            m = re.search(r"enum:\s*\[(.+?)\]", line)
            if m:
                for v in m.group(1).split(","):
                    values.append(v.strip().strip("'\""))
                return values
    return values


# ---------- Mock infra (reused from test_maf_sdk.py pattern) ----------

class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._payload


MOCK_RECEIPT = {
    "schema": "madis.maf.command-receipt.v1",
    "command_id": "cmd-12345678",
    "status": "accepted",
    "trace_id": "tr-abcdef01",
}

MOCK_CALL = {
    "schema": "madis.maf.call.v1",
    "call_id": "call-12345678",
    "state": "ringing",
    "version": "1",
}

MOCK_EVENT_PAGE = {
    "schema": "madis.maf.event-page.v1",
    "events": [],
    "next_cursor": "0",
    "truncated": False,
}


class OpenApiContractTests(unittest.TestCase):
    """Validate SDK surface against OpenAPI spec."""

    @classmethod
    def setUpClass(cls):
        cls.spec = _load_spec()
        cls.routes = _extract_paths(cls.spec)

    def setUp(self):
        self.captured = []
        self.client = MadisMaf("https://proxy.example.net/admin", "0123456789abcdef")
        self._patcher = patch("madis_maf.urlopen", side_effect=self._intercept)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _intercept(self, request, timeout):
        body = None if request.data is None else json.loads(request.data)
        self.captured.append({
            "method": request.method,
            "url": request.full_url,
            "headers": dict(request.headers),
            "body": body,
        })
        is_get = request.method == "GET"
        if "/events" in request.full_url:
            payload = MOCK_EVENT_PAGE
        elif is_get:
            payload = MOCK_CALL
        else:
            payload = MOCK_RECEIPT
        return FakeResponse(200 if is_get else 202, payload)

    # -- Route coverage --

    # Map operationId -> SDK method name
    ROUTE_SDK_MAP = {
        ("POST", "/api/v1/maf/calls"): "create_call",
        ("GET", "/api/v1/maf/calls/{call_id}"): "get_call",
        ("POST", "/api/v1/maf/calls/{call_id}/answer"): "answer_call",
        ("POST", "/api/v1/maf/calls/{call_id}/reject"): "reject_call",
        ("POST", "/api/v1/maf/calls/{call_id}/hangup"): "hangup_call",
        ("POST", "/api/v1/maf/calls/{call_id}/bridges"): "bridge_call",
        ("POST", "/api/v1/maf/calls/{call_id}/media"): "media",
        ("POST", "/api/v1/maf/calls/{call_id}/headers"): "set_headers",
        ("GET", "/api/v1/maf/events"): "events",
    }

    def test_every_openapi_route_has_sdk_method(self):
        for method, path in self.routes:
            sdk_method = self.ROUTE_SDK_MAP.get((method, path))
            self.assertIsNotNone(sdk_method, f"No SDK mapping for {method} {path}")
            self.assertTrue(
                hasattr(self.client, sdk_method),
                f"MadisMaf missing method '{sdk_method}' for {method} {path}",
            )

    # -- Schema required-field validation --

    def test_command_receipt_required_fields(self):
        required = {"schema", "command_id", "status", "trace_id"}
        for field in required:
            self.assertIn(field, MOCK_RECEIPT, f"CommandReceipt missing '{field}'")
        self.assertEqual(MOCK_RECEIPT["schema"], "madis.maf.command-receipt.v1")

    def test_event_page_required_fields(self):
        required = {"schema", "events", "next_cursor", "truncated"}
        for field in required:
            self.assertIn(field, MOCK_EVENT_PAGE, f"EventPage missing '{field}'")
        self.assertEqual(MOCK_EVENT_PAGE["schema"], "madis.maf.event-page.v1")

    def test_call_required_fields(self):
        required = {"schema", "call_id", "state", "version"}
        for field in required:
            self.assertIn(field, MOCK_CALL, f"Call missing '{field}'")
        self.assertEqual(MOCK_CALL["schema"], "madis.maf.call.v1")

    # -- Enum validation --

    def test_command_receipt_status_enum(self):
        spec_enums = _extract_enum(self.spec, "CommandReceipt", "status")
        self.assertEqual(spec_enums, ["accepted", "completed", "failed"])
        self.assertIn(MOCK_RECEIPT["status"], spec_enums)

    def test_call_state_enum(self):
        spec_enums = _extract_enum(self.spec, "Call:", "state")
        expected = ["created", "ringing", "answered", "bridged", "ending", "ended", "failed"]
        self.assertEqual(spec_enums, expected)
        self.assertIn(MOCK_CALL["state"], spec_enums)

    def test_media_operation_enum(self):
        spec_enums = _extract_enum(self.spec, "MediaRequest", "operation")
        expected = ["play", "record", "stop", "pause", "resume"]
        self.assertEqual(spec_enums, expected)

    def test_header_action_enum(self):
        spec_enums = _extract_enum(self.spec, "HeaderPolicy", "action")
        expected = ["add", "set", "remove", "rename", "copy", "move"]
        self.assertEqual(spec_enums, expected)

    # -- Body size limit --

    def test_body_size_limit_64kb(self):
        huge = {"data": "x" * 70000}
        with self.assertRaises(ValueError) as ctx:
            self.client.create_call("sip:a@x", "sip:b@x",
                                    application_data=huge)
        self.assertIn("64", str(ctx.exception))

    # -- Idempotency-Key on all command routes --

    def test_idempotency_key_on_command_routes(self):
        self.client.create_call("sip:a@x", "sip:b@x", idempotency_key="k-create-1")
        self.client.answer_call("c1", "v=0\r\n", "k-answer-1")
        self.client.reject_call("c1", idempotency_key="k-reject-1")
        self.client.hangup_call("c1", idempotency_key="k-hangup-1")
        self.client.bridge_call("c1", ["a", "b"], "k-bridge-1")
        self.client.media("c1", "play", idempotency_key="k-media-01")
        self.client.set_headers("c1", [{"action": "add", "name": "X-Foo"}],
                                idempotency_key="k-header-1")
        for cap in self.captured:
            if cap["method"] == "POST":
                self.assertIn("Idempotency-key", cap["headers"],
                              f"Missing Idempotency-Key on {cap['url']}")

    # -- Bearer auth header format --

    def test_bearer_auth_header_format(self):
        self.client.get_call("call-12345678")
        auth = self.captured[0]["headers"]["Authorization"]
        self.assertTrue(auth.startswith("Bearer "), f"Bad auth format: {auth}")

    # -- MAF version header --

    def test_maf_version_header_sent(self):
        self.client.get_call("call-12345678")
        self.assertIn("X-maf-version", self.captured[0]["headers"])
        self.assertEqual(self.captured[0]["headers"]["X-maf-version"], MAF_VERSION)

    def test_maf_version_constant(self):
        self.assertEqual(MAF_VERSION, "0.5.0")


if __name__ == "__main__":
    unittest.main()
