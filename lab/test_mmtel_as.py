"""Unit tests for the lab MMTel/TAS stub (no network)."""

import unittest

from lab import mmtel_as


class MmtelAsTests(unittest.TestCase):
    def test_barring_mo(self):
        rules = {"sip:alice@example.com": {"barring_mo": True}}
        invite = (
            "INVITE sip:bob@example.com SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK-x\r\n"
            "From: <sip:alice@example.com>;tag=a\r\n"
            "To: <sip:bob@example.com>\r\n"
            "Call-ID: c1\r\n"
            "CSeq: 1 INVITE\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        resp = mmtel_as.handle(invite, rules).decode()
        self.assertIn("603", resp)

    def test_cfu_redirect(self):
        rules = {"sip:alice@example.com": {"cfu": "sip:vm@example.com"}}
        invite = (
            "INVITE sip:bob@example.com SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5060;branch=z9hG4bK-y\r\n"
            "From: <sip:alice@example.com>;tag=a\r\n"
            "To: <sip:bob@example.com>\r\n"
            "Call-ID: c2\r\n"
            "CSeq: 1 INVITE\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        resp = mmtel_as.handle(invite, rules).decode()
        self.assertIn("302", resp)
        self.assertIn("sip:vm@example.com", resp)

    def test_third_party_register(self):
        rules = {}
        reg = (
            "REGISTER sip:tas.example.com SIP/2.0\r\n"
            "Via: SIP/2.0/UDP scscf;branch=z9hG4bK-r\r\n"
            "From: <sip:alice@example.com>;tag=t\r\n"
            "To: <sip:alice@example.com>\r\n"
            "Call-ID: r1\r\n"
            "CSeq: 1 REGISTER\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        resp = mmtel_as.handle(reg, rules).decode()
        self.assertIn("200", resp)


if __name__ == "__main__":
    unittest.main()
