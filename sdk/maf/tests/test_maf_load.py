"""Load, backpressure, and boundary tests for the MAF SDK."""

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MafError  # noqa: E402


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


TOKEN = "0123456789abcdef"


class TestRapidCommandSubmission(unittest.TestCase):
    """1000 commands with unique idempotency keys must yield unique command_ids."""

    def setUp(self):
        self.seen_keys = []
        self.client = MadisMaf("https://proxy.example.net", TOKEN)

    def _fake_urlopen(self, request, timeout):
        body = json.loads(request.data)
        self.seen_keys.append(body["command_id"])
        return FakeResponse(202, {"status": "accepted", "command_id": body["command_id"]})

    @patch("madis_maf.urlopen")
    def test_1000_unique_commands(self, mock_urlopen):
        mock_urlopen.side_effect = self._fake_urlopen
        keys = [f"key-{i:04d}" for i in range(1000)]
        for k in keys:
            self.client.create_call("sip:a@x", "sip:b@x", idempotency_key=k)
        self.assertEqual(len(set(self.seen_keys)), 1000)
        self.assertEqual(self.seen_keys, keys)


class TestBodySizeBoundary(unittest.TestCase):
    """Body at exactly 64 KiB must succeed; 64 KiB + 1 must fail."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", TOKEN)

    @patch("madis_maf.urlopen")
    def test_exactly_64k_succeeds(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(202, {"ok": True})
        # Build a body whose JSON encoding is exactly 65536 bytes.
        # json.dumps({"d":"x..."}, separators=(",",":")) → {"d":"..."}
        # overhead: {"d":""} = 8 bytes, so pad = 65536 - 8 = 65528
        pad = "x" * 65528
        body = {"d": pad}
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(encoded), 65536)
        # Should not raise
        self.client._request("POST", "/api/v1/maf/calls", body)

    def test_64k_plus_one_fails(self):
        pad = "x" * 65529  # 8 + 65529 = 65537
        body = {"d": pad}
        encoded = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        self.assertEqual(len(encoded), 65537)
        with self.assertRaises(ValueError) as ctx:
            self.client._request("POST", "/api/v1/maf/calls", body)
        self.assertIn("64 KiB", str(ctx.exception))


class TestLargeEventPage(unittest.TestCase):
    """A page with 100 events should parse correctly."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", TOKEN)

    @patch("madis_maf.urlopen")
    def test_100_events_parsed(self, mock_urlopen):
        events = [{"id": i, "type": "call.created", "ts": 1000 + i} for i in range(100)]
        payload = {"events": events, "next_cursor": 100}
        mock_urlopen.return_value = FakeResponse(200, payload)
        result = self.client.events(cursor=0)
        self.assertEqual(len(result["events"]), 100)
        self.assertEqual(result["next_cursor"], 100)
        self.assertEqual(result["events"][99]["id"], 99)


class TestConcurrentIdempotency(unittest.TestCase):
    """Same key submitted twice should return the same receipt."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", TOKEN)
        self.call_count = 0

    def _fake_urlopen(self, request, timeout):
        self.call_count += 1
        return FakeResponse(202, {"command_id": "fixed-id", "status": "accepted"})

    @patch("madis_maf.urlopen")
    def test_same_key_same_receipt(self, mock_urlopen):
        mock_urlopen.side_effect = self._fake_urlopen
        r1 = self.client.create_call("sip:a@x", "sip:b@x", idempotency_key="dup-key")
        r2 = self.client.create_call("sip:a@x", "sip:b@x", idempotency_key="dup-key")
        self.assertEqual(r1["command_id"], r2["command_id"])
        # Both calls sent the same idempotency key in body
        self.assertEqual(self.call_count, 2)


class TestEventCursorWraparound(unittest.TestCase):
    """Cursor values near max int should work without overflow."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", TOKEN)

    @patch("madis_maf.urlopen")
    def test_large_cursor(self, mock_urlopen):
        big = 2**63 - 1
        mock_urlopen.return_value = FakeResponse(200, {"events": [], "next_cursor": big + 1})
        result = self.client.events(cursor=big)
        # Verify the cursor was passed through
        req = mock_urlopen.call_args[0][0]
        self.assertIn(f"cursor={big}", req.full_url)
        self.assertEqual(result["next_cursor"], big + 1)

    @patch("madis_maf.urlopen")
    def test_negative_cursor_clamped_to_zero(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(200, {"events": [], "next_cursor": 0})
        self.client.events(cursor=-5)
        req = mock_urlopen.call_args[0][0]
        self.assertIn("cursor=0", req.full_url)


class TestEmptyStringFieldsRejected(unittest.TestCase):
    """Empty string fields should be rejected where minLength > 0."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", TOKEN)

    def test_empty_from_uri(self):
        # create_call passes through to server; SDK doesn't validate URIs,
        # but base_url and token DO have minLength constraints.
        with self.assertRaises(ValueError):
            MadisMaf("", TOKEN)

    def test_empty_token(self):
        with self.assertRaises(ValueError):
            MadisMaf("https://proxy.example.net", "")

    def test_empty_base_url_no_scheme(self):
        with self.assertRaises(ValueError):
            MadisMaf("not-a-url", TOKEN)


if __name__ == "__main__":
    unittest.main()
