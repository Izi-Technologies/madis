"""Per-tenant authorization and token isolation tests for the MAF SDK."""

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

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


class TestDifferentTokensDifferentTenants(unittest.TestCase):
    """Different tokens must produce different Authorization headers."""

    @patch("madis_maf.urlopen")
    def test_tokens_isolated(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(200, {"events": []})

        client_a = MadisMaf("https://proxy.example.net", "tenant-a-token-1234")
        client_b = MadisMaf("https://proxy.example.net", "tenant-b-token-5678")

        client_a.events()
        req_a = mock_urlopen.call_args_list[0][0][0]

        client_b.events()
        req_b = mock_urlopen.call_args_list[1][0][0]

        self.assertEqual(req_a.get_header("Authorization"), "Bearer tenant-a-token-1234")
        self.assertEqual(req_b.get_header("Authorization"), "Bearer tenant-b-token-5678")
        self.assertNotEqual(
            req_a.get_header("Authorization"),
            req_b.get_header("Authorization"),
        )


class TestTokenLengthValidation(unittest.TestCase):
    """Token must be 16..512 characters."""

    def test_token_too_short(self):
        with self.assertRaises(ValueError) as ctx:
            MadisMaf("https://proxy.example.net", "short")
        self.assertIn("16..512", str(ctx.exception))

    def test_token_exactly_15_chars(self):
        with self.assertRaises(ValueError):
            MadisMaf("https://proxy.example.net", "a" * 15)

    def test_token_exactly_16_chars(self):
        # Should succeed
        client = MadisMaf("https://proxy.example.net", "a" * 16)
        self.assertIsNotNone(client)

    def test_token_exactly_512_chars(self):
        # Should succeed
        client = MadisMaf("https://proxy.example.net", "a" * 512)
        self.assertIsNotNone(client)

    def test_token_too_long(self):
        with self.assertRaises(ValueError) as ctx:
            MadisMaf("https://proxy.example.net", "a" * 513)
        self.assertIn("16..512", str(ctx.exception))

    def test_missing_token_empty_string(self):
        with self.assertRaises(ValueError):
            MadisMaf("https://proxy.example.net", "")


class TestHTTPErrorResponses(unittest.TestCase):
    """401 and 403 responses must raise MafError with correct status."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", "0123456789abcdef")

    @patch("madis_maf.urlopen")
    def test_401_raises_maf_error(self, mock_urlopen):
        body = json.dumps({"error": "unauthorized"}).encode()
        mock_urlopen.side_effect = HTTPError(
            "https://proxy.example.net/api/v1/maf/events",
            401, "Unauthorized", {}, BytesIO(body),
        )
        with self.assertRaises(MafError) as ctx:
            self.client.events()
        self.assertEqual(ctx.exception.status, 401)

    @patch("madis_maf.urlopen")
    def test_403_raises_maf_error(self, mock_urlopen):
        body = json.dumps({"error": "forbidden", "detail": "wrong tenant"}).encode()
        mock_urlopen.side_effect = HTTPError(
            "https://proxy.example.net/api/v1/maf/calls/x",
            403, "Forbidden", {}, BytesIO(body),
        )
        with self.assertRaises(MafError) as ctx:
            self.client.get_call("x")
        self.assertEqual(ctx.exception.status, 403)
        self.assertEqual(ctx.exception.payload["error"], "forbidden")


class TestTokenNeverInURL(unittest.TestCase):
    """Token must only appear in Authorization header, never in the URL."""

    def setUp(self):
        self.client = MadisMaf("https://proxy.example.net", "secret-token-value-1234")

    @patch("madis_maf.urlopen")
    def test_token_not_in_url(self, mock_urlopen):
        mock_urlopen.return_value = FakeResponse(200, {"events": []})

        self.client.events()
        self.client.get_call("call-1")

        for call_args in mock_urlopen.call_args_list:
            req = call_args[0][0]
            self.assertNotIn("secret-token-value-1234", req.full_url)
            self.assertIn("secret-token-value-1234", req.get_header("Authorization"))


class TestTokenNeverLeakedInErrors(unittest.TestCase):
    """Token must never appear in error messages or string representations."""

    def setUp(self):
        self.token = "super-secret-token-99"
        self.client = MadisMaf("https://proxy.example.net", self.token)

    @patch("madis_maf.urlopen")
    def test_token_not_in_maf_error_message(self, mock_urlopen):
        body = json.dumps({"error": "bad"}).encode()
        mock_urlopen.side_effect = HTTPError(
            "https://proxy.example.net/api/v1/maf/events",
            500, "Server Error", {}, BytesIO(body),
        )
        with self.assertRaises(MafError) as ctx:
            self.client.events()
        self.assertNotIn(self.token, str(ctx.exception))
        self.assertNotIn(self.token, repr(ctx.exception))

    def test_token_not_in_client_repr(self):
        # Client should not expose token in repr/str
        self.assertNotIn(self.token, str(self.client))


if __name__ == "__main__":
    unittest.main()
