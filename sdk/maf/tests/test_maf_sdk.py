import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self._payload


class MafSdkTests(unittest.TestCase):
    def setUp(self):
        self.records = []
        self.client = MadisMaf("https://proxy.example.net/admin", "0123456789abcdef")
        self.urlopen = patch("madis_maf.urlopen", side_effect=self.fake_urlopen)
        self.urlopen.start()

    def tearDown(self):
        self.urlopen.stop()

    def fake_urlopen(self, request, timeout):
        body = None if request.data is None else json.loads(request.data)
        self.records.append((request.method, request.full_url, dict(request.headers), body, timeout))
        status = 202 if request.method == "POST" else 200
        return FakeResponse(status, {"status": "accepted", "resource_id": "call-12345678"})

    def test_all_routes_and_security_headers(self):
        self.client.create_call("sip:a@example.net", "sip:b@example.net", idempotency_key="create-123456")
        self.client.get_call("call-12345678")
        self.client.answer_call("call-12345678", "v=0\r\nm=audio 4000 RTP/AVP 0\r\n", "answer-123456")
        self.client.reject_call("call-12345678", 486, "busy", "reject-123456")
        self.client.hangup_call("call-12345678", "done", "hangup-123456")
        self.client.bridge_call("call-12345678", ["chan-a", "chan-b"], "bridge-123456")
        self.client.media("call-12345678", "play", "tone", "media-123456")
        self.client.events(cursor=4, event_type="call.created", limit=200)
        self.assertEqual(len(self.records), 8)
        for _, _, headers, _, _ in self.records:
            self.assertEqual(headers["Authorization"], "Bearer 0123456789abcdef")
        self.assertEqual(urlparse(self.records[0][1]).path, "/admin/api/v1/maf/calls")
        events_url = urlparse(self.records[-1][1])
        self.assertEqual(events_url.path, "/admin/api/v1/maf/events")
        self.assertEqual(parse_qs(events_url.query), {"cursor": ["4"], "event_type": ["call.created"], "limit": ["100"]})


if __name__ == "__main__":
    unittest.main()
