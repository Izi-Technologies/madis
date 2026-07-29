import select
import socket
import threading
import time
import unittest

try:
    from .rtp_module import BencodeError, MediaRelay, bdecode_dict, bencode_dict, parse_sdp
except ImportError:
    from rtp_module import BencodeError, MediaRelay, bdecode_dict, bencode_dict, parse_sdp


SDP_A = (
    "v=0\r\n"
    "o=- 1 1 IN IP4 127.0.0.1\r\n"
    "s=-\r\n"
    "c=IN IP4 127.0.0.1\r\n"
    "t=0 0\r\n"
    "m=audio 49170 RTP/AVP 0\r\n"
)
SDP_B = SDP_A.replace("49170", "49172")


class MediaCodecTests(unittest.TestCase):
    def test_bencode_rejects_duplicate_and_oversized_values(self) -> None:
        with self.assertRaises(BencodeError):
            bdecode_dict(b"d3:foo3:bar3:foo3:baze")
        with self.assertRaises(BencodeError):
            bdecode_dict(b"d3:foo65536:" + b"x" * 65536 + b"e")

    def test_bencode_rejects_deep_nesting(self) -> None:
        nested = b"l" * 40 + b"e" * 40
        with self.assertRaises(BencodeError):
            bdecode_dict(nested)

    def test_sdp_requires_one_routable_audio_stream(self) -> None:
        for invalid in (
            SDP_A.replace("m=audio", "m=video"),
            SDP_A.replace("c=IN IP4 127.0.0.1", "c=IN IP4 0.0.0.0"),
            SDP_A + "m=audio 49171 RTP/AVP 0\r\n",
        ):
            with self.assertRaises(ValueError):
                parse_sdp(invalid)


class MediaModuleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.bind(("127.0.0.1", 0))
        except OSError as exc:
            raise unittest.SkipTest(f"localhost UDP unavailable: {exc}") from exc
        finally:
            probe.close()

    def setUp(self) -> None:
        self.relay = MediaRelay(media_min=0xC000, media_max=0xC010)

    def tearDown(self) -> None:
        self.relay.close()

    def command(self, **fields: str) -> dict[bytes, object]:
        return bdecode_dict(self.relay.handle_payload(bencode_dict(fields)))

    def test_offer_answer_delete_and_sdp_rewrite(self) -> None:
        offer = self.command(command="offer", **{"call-id": "call-1", "from-tag": "from-1", "sdp": SDP_A})
        self.assertEqual(offer[b"result"], b"ok")
        rewritten_offer = offer[b"sdp"].decode("ascii")
        self.assertIn("c=IN IP4 127.0.0.1", rewritten_offer)
        self.assertNotIn("m=audio 49170", rewritten_offer)
        self.assertEqual(len(self.relay.sessions), 1)

        answer = self.command(
            command="answer",
            **{"call-id": "call-1", "from-tag": "from-1", "to-tag": "to-1", "sdp": SDP_B},
        )
        self.assertEqual(answer[b"result"], b"ok")
        self.assertNotIn(b"49172", answer[b"sdp"])

        deleted = self.command(command="delete", **{"call-id": "call-1"})
        self.assertEqual(deleted[b"result"], b"ok")
        self.assertEqual(len(self.relay.sessions), 0)

    def test_rtp_packet_is_relayed_between_allocated_legs(self) -> None:
        endpoint_a = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        endpoint_b = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        endpoint_a.bind(("127.0.0.1", 0))
        endpoint_b.bind(("127.0.0.1", 0))
        endpoint_b.settimeout(2.0)
        try:
            sdp_a = SDP_A.replace("49170", str(endpoint_a.getsockname()[1]))
            sdp_b = SDP_B.replace("49172", str(endpoint_b.getsockname()[1]))
            self.command(command="offer", **{"call-id": "call-2", "from-tag": "from-2", "sdp": sdp_a})
            self.command(
                command="answer",
                **{"call-id": "call-2", "from-tag": "from-2", "to-tag": "to-2", "sdp": sdp_b},
            )
            session = self.relay.sessions["call-2"]
            packet = b"\x80\x00\x00\x01" + b"\x00" * 8 + b"lab-packet"
            endpoint_a.sendto(packet, session.offer.socket.getsockname())
            readable, _, _ = select.select([session.offer.socket], [], [], 2.0)
            self.assertEqual(readable, [session.offer.socket])
            self.relay._handle_media_socket(session.offer.socket)
            forwarded, _ = endpoint_b.recvfrom(64)
            self.assertEqual(forwarded, packet)
        finally:
            endpoint_a.close()
            endpoint_b.close()

    def test_malformed_and_unsafe_commands_fail_closed(self) -> None:
        malformed = bdecode_dict(self.relay.handle_payload(b"not-bencode"))
        self.assertEqual(malformed[b"result"], b"error")
        unsafe = self.command(
            command="offer",
            **{"call-id": "call\r\nX", "from-tag": "from-1", "sdp": SDP_A},
        )
        self.assertEqual(unsafe[b"result"], b"error")
        unsupported = self.command(command="record", **{"call-id": "call-3", "from-tag": "from-3", "sdp": SDP_A})
        self.assertEqual(unsupported[b"result"], b"error")

    def test_idle_sessions_are_reclaimed(self) -> None:
        self.command(command="offer", **{"call-id": "call-expire", "from-tag": "from-expire", "sdp": SDP_A})
        self.relay.sessions["call-expire"].last_activity = time.monotonic() - 3601
        self.relay._expire_sessions()
        self.assertNotIn("call-expire", self.relay.sessions)

    def test_session_capacity_fails_closed(self) -> None:
        relay = MediaRelay(media_min=0xC100, media_max=0xC110, max_sessions=1)
        try:
            first = bdecode_dict(
                relay.handle_payload(
                    bencode_dict(
                        {"command": "offer", "call-id": "capacity-1", "from-tag": "from-1", "sdp": SDP_A}
                    )
                )
            )
            second = bdecode_dict(
                relay.handle_payload(
                    bencode_dict(
                        {"command": "offer", "call-id": "capacity-2", "from-tag": "from-2", "sdp": SDP_A}
                    )
                )
            )
            self.assertEqual(first[b"result"], b"ok")
            self.assertEqual(second[b"result"], b"error")
            self.assertEqual(second[b"error-reason"], b"capacity-exhausted")
            self.assertEqual(len(relay.sessions), 1)
        finally:
            relay.close()

    def test_control_listener_restart_recovers(self) -> None:
        def ping(relay: MediaRelay) -> None:
            thread = threading.Thread(target=relay.serve, args=("127.0.0.1", 0), daemon=True)
            thread.start()
            deadline = time.monotonic() + 2.0
            while relay.control_address is None and time.monotonic() < deadline:
                time.sleep(0.001)
            self.assertIsNotNone(relay.control_address)
            client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                cookie = b"restart-cookie"
                client.sendto(cookie + b" " + bencode_dict({"command": "ping"}), relay.control_address)
                client.settimeout(2.0)
                response, _ = client.recvfrom(4096)
                self.assertEqual(response[: len(cookie)], cookie)
                self.assertEqual(bdecode_dict(response[len(cookie) + 1 :])[b"result"], b"ok")
            finally:
                client.close()
                relay.close()
                thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())

        ping(MediaRelay(media_min=0xC200, media_max=0xC210))
        ping(MediaRelay(media_min=0xC220, media_max=0xC230))

    def test_ng_udp_control_round_trip(self) -> None:
        thread = threading.Thread(target=self.relay.serve, args=("127.0.0.1", 0), daemon=True)
        thread.start()
        deadline = time.monotonic() + 2.0
        while self.relay.control_address is None and time.monotonic() < deadline:
            time.sleep(0.001)
        self.assertIsNotNone(self.relay.control_address)
        client = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client.settimeout(2.0)
        try:
            cookie = b"wire-cookie"
            command = bencode_dict({"command": "offer", "call-id": "wire-call", "from-tag": "wire-from", "sdp": SDP_A})
            client.sendto(cookie + b" " + command, self.relay.control_address)
            response, _ = client.recvfrom(65535)
            self.assertEqual(response[:len(cookie)], cookie)
            decoded = bdecode_dict(response[len(cookie) + 1:])
            self.assertEqual(decoded[b"result"], b"ok")

            client.sendto(cookie + b" " + bencode_dict({"command": "delete", "call-id": "wire-call"}), self.relay.control_address)
            response, _ = client.recvfrom(65535)
            self.assertEqual(bdecode_dict(response[len(cookie) + 1:])[b"result"], b"ok")
        finally:
            client.close()
            self.relay.close()
            thread.join(timeout=2.0)
            self.assertFalse(thread.is_alive())


if __name__ == "__main__":
    unittest.main()
