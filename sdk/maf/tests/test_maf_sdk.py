import json
import sys
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MAF_VERSION  # noqa: E402


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
        return FakeResponse(status, {
            "status": "accepted",
            "resource_id": "call-12345678",
            "events": [{"event_type": "call.dtmf", "payload": {"digit": "9"}}],
            "next_cursor": "5",
        })

    def test_maf_version(self):
        self.assertEqual(MAF_VERSION, "0.7.0")

    def test_all_routes_and_security_headers(self):
        # 1. Call operations
        self.client.create_call("sip:a@example.net", "sip:b@example.net", {"app": "crm"}, "create-123456", caller_id="+15550001")
        self.client.get_call("call-12345678")
        self.client.answer_call("call-12345678", "v=0\r\nm=audio 4000 RTP/AVP 0\r\n", "answer-123456")
        self.client.reject_call("call-12345678", 486, "busy", "reject-123456")
        self.client.hangup_call("call-12345678", "done", "hangup-123456")
        self.client.bridge_call("call-12345678", ["chan-a", "chan-b"], "bridge-123456")
        self.client.media("call-12345678", "play", "tone", "media-123456")
        self.client.set_headers("call-12345678", [{"action": "add", "name": "X-Client", "value": "test"}], "hdr-123456")
        self.client.transfer_call("call-12345678", "sip:carol@example.net", "blind", idempotency_key="xfer-123456")
        self.client.hold_call("call-12345678", "hold-123456")
        self.client.unhold_call("call-12345678", "unhold-123456")
        self.client.send_dtmf("call-12345678", "5", 250, "dtmf-123456")
        self.client.rtp_control("call-12345678", "offer", sdp="v=0\r\n", idempotency_key="rtp-123456")
        self.client.route_call("call-12345678", "sip:agent@10.0.0.1:5060", transport="udp", mode="proxy", caller_id="+15559999", idempotency_key="route-123456")
        self.client.identity("call-12345678", "sign", attest="A", idempotency_key="id-123456")

        # 2. Advanced MAF services
        self.client.scheduled_calls()
        self.client.schedule_call("sip:a@example.net", "sip:b@example.net", "2026-09-05T12:00:00Z")
        self.client.cancel_scheduled_call(1)
        self.client.queues()
        self.client.create_queue("support", "round-robin", 180)
        self.client.add_queue_member(1, "sip:agent@example.net", 1)
        self.client.remove_queue_member(1, 10)
        self.client.conferences()
        self.client.create_conference("room-1", "1234", 10, True)
        self.client.webhooks()
        self.client.create_webhook("https://app.example.net/webhook", ["call.answered", "call.dtmf"])
        self.client.delete_webhook(1)
        self.client.tag_call("call-12345678", {"dept": "sales"})
        self.client.number_lookup("+15551234")
        self.client.upsert_number("+15551234", "Verizon", "mobile", "US", 0)
        self.client.routing_intelligence()
        self.client.record_routing_outcome("gw-1", "+1", True, 60, 450)

        # 3. Events
        self.client.events(cursor=4, event_type="call.created", limit=200)

        self.assertEqual(len(self.records), 33)
        for _, _, headers, _, _ in self.records:
            self.assertEqual(headers["Authorization"], "Bearer 0123456789abcdef")
            self.assertEqual(headers["X-maf-version"], "0.7.0")
        self.assertEqual(urlparse(self.records[0][1]).path, "/admin/api/v1/maf/calls")
        self.assertEqual(self.records[0][3]["caller_id"], "+15550001")
        self.assertEqual(urlparse(self.records[13][1]).path, "/admin/api/v1/maf/calls/call-12345678/route")
        self.assertEqual(self.records[13][3]["target"], "sip:agent@10.0.0.1:5060")
        self.assertEqual(self.records[13][3]["mode"], "proxy")
        events_url = urlparse(self.records[-1][1])
        self.assertEqual(events_url.path, "/admin/api/v1/maf/events")
        self.assertEqual(parse_qs(events_url.query), {"cursor": ["4"], "event_type": ["call.created"], "limit": ["100"]})

    def test_ws_url_generation(self):
        url = self.client.ws_url(cursor=2, event_type="call.dtmf", call_id="call-999")
        self.assertEqual(url, "wss://proxy.example.net/admin/api/v1/maf/events/ws?cursor=2&event_type=call.dtmf&call_id=call-999")


if __name__ == "__main__":
    unittest.main()
