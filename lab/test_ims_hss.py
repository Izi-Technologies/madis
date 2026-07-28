import base64
import json
import os
import pathlib
import shutil
import socket
import struct
import ssl
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request
import unittest

try:
    from .ims_hss import (
        CX_APPLICATION,
        HssApplication,
        HssStore,
        DiameterServer,
        SubscriberHTTPServer,
        RESULT_SUCCESS,
        RESULT_UNKNOWN_USER,
        _avp_text,
        _avp_u32,
        _vendor_grouped,
        _vendor_text,
        build_message,
        parse_message,
        authorization_document,
        _tls_context,
        parse_message,
    )
except ImportError:
    from ims_hss import (
        CX_APPLICATION,
        HssApplication,
        HssStore,
        DiameterServer,
        SubscriberHTTPServer,
    RESULT_SUCCESS,
    RESULT_UNKNOWN_USER,
    _avp_text,
    _avp_u32,
    _vendor_grouped,
    _vendor_text,
    build_message,
    parse_message,
        authorization_document,
        _tls_context,
        parse_message,
    )


class HssAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HssStore()
        self.store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
                "service_profile": {"associated_uris": ["sip:alice@example.com"]},
            }
        )
        self.app = HssApplication(self.store, origin_host="hss.lab.local", origin_realm="example.com")

    def request(self, command: int, body: bytes) -> bytes:
        return build_message(flags=0x80, command=command, application=CX_APPLICATION, hop_by_hop=11, end_to_end=22, body=body)

    def identity_body(self, command: int, include_server: bool = True) -> bytes:
        body = _avp_text(263, "session;alice") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com")
        if include_server:
            body += _vendor_text(602, "sip:scscf.example.com")
        if command == 303:
            item = _avp_u32(613, 0, vendor=10415) + _vendor_text(608, "Digest-AKAv1-MD5")
            body += _vendor_grouped(612, item)
        return body

    def test_uar_sar_and_lir_return_assigned_server(self) -> None:
        for command in (300, 301, 302):
            response = parse_message(self.app.handle(self.request(command, self.identity_body(command))))
            self.assertEqual(response.find(268), (RESULT_SUCCESS).to_bytes(4, "big"))
            self.assertEqual(response.find(602, 10415), b"sip:scscf.example.com")

    def test_mar_returns_opaque_vector(self) -> None:
        response = parse_message(self.app.handle(self.request(303, self.identity_body(303))))
        self.assertEqual(response.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        item = response.find(612, 10415)
        self.assertIsNotNone(item)
        self.assertIn(b"xres-alice", item)
        self.assertIn(b"Digest-AKAv1-MD5", item)

    def test_unknown_subscriber_and_server_mismatch_fail_closed(self) -> None:
        unknown = self.request(300, _avp_text(1, "missing@example.com") + _vendor_text(601, "sip:missing@example.com") + _vendor_text(602, "sip:scscf.example.com"))
        self.assertEqual(parse_message(self.app.handle(unknown)).find(268), RESULT_UNKNOWN_USER.to_bytes(4, "big"))
        mismatch = self.request(300, self.identity_body(300).replace(b"sip:scscf.example.com", b"sip:other.example.com"))
        self.assertEqual(parse_message(self.app.handle(mismatch)).find(268), RESULT_UNKNOWN_USER.to_bytes(4, "big"))

    def test_disabled_subscriber_fails_closed_without_private_identity(self) -> None:
        self.store.provision(
            {
                "public_identity": "sip:disabled@example.com",
                "private_identity": "disabled@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-disabled").decode("ascii"),
                "enabled": False,
            }
        )
        request = self.request(
            300,
            _avp_text(263, "disabled-session")
            + _vendor_text(601, "sip:disabled@example.com")
            + _vendor_text(602, "sip:scscf.example.com"),
        )
        result = parse_message(self.app.handle(request)).find(268)
        self.assertEqual(result, RESULT_UNKNOWN_USER.to_bytes(4, "big"))

    def test_authorization_contract_does_not_return_xres(self) -> None:
        status, response = authorization_document(
            self.store,
            {
                "schema": "madis.ims.subscriber.authorization.v1",
                "operation": "authorize-register",
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "visited_network": "example.com",
                "server_name": "sip:scscf.example.com",
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["decision"], "allow")
        self.assertNotIn("xres", response)
        self.assertNotIn("xres_base64", response)

    def test_profile_rejects_unbounded_or_secret_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.store.provision(
                {
                    "public_identity": "sip:bob@example.com",
                    "private_identity": "bob@example.com",
                    "assigned_server_name": "sip:scscf.example.com",
                    "xres_base64": base64.b64encode(b"xres-bob").decode("ascii"),
                    "service_profile": {"xres": "must-not-be-returned"},
                }
            )


def _read_exact(sock: socket.socket, length: int) -> bytes:
    data = bytearray()
    while len(data) < length:
        chunk = sock.recv(length - len(data))
        if not chunk:
            raise ConnectionError("peer closed")
        data.extend(chunk)
    return bytes(data)


def _read_diameter_frame(sock: socket.socket) -> bytes:
    header = _read_exact(sock, 20)
    length = int.from_bytes(header[1:4], "big")
    return header + _read_exact(sock, length - 20)


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_NETWORK") == "1", "set IMS_HSS_TEST_NETWORK=1 for listener tests")
class HssDiameterWireTests(unittest.TestCase):
    def setUp(self) -> None:
        store = HssStore()
        store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
            }
        )
        self.server = DiameterServer(HssApplication(store, origin_host="hss.lab.local", origin_realm="example.com"), "127.0.0.1", 0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        deadline = time.monotonic() + 2.0
        while self.server.bound_port == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        if self.server.bound_port == 0:
            self.server.close()
            self.thread.join(timeout=2.0)
            self.skipTest("TCP listener could not start")

    def tearDown(self) -> None:
        self.server.close()
        self.thread.join(timeout=2.0)

    def test_cer_then_cx_request_over_tcp(self) -> None:
        cer = build_message(flags=0x80, command=257, application=0, hop_by_hop=1, end_to_end=2, body=b"")
        uar = build_message(
            flags=0x80,
            command=300,
            application=CX_APPLICATION,
            hop_by_hop=3,
            end_to_end=4,
            body=_avp_text(263, "wire-session") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com") + _vendor_text(602, "sip:scscf.example.com"),
        )
        with socket.create_connection(("127.0.0.1", self.server.bound_port), timeout=2.0) as conn:
            conn.sendall(cer)
            cea = parse_message(_read_diameter_frame(conn))
            self.assertEqual(cea.command, 257)
            self.assertEqual(cea.find(268), (RESULT_SUCCESS).to_bytes(4, "big"))
            self.assertEqual(cea.find(258), (4).to_bytes(4, "big"))
            self.assertIsNotNone(cea.find(260))
            conn.sendall(uar)
            uaa = parse_message(_read_diameter_frame(conn))
            self.assertEqual(uaa.command, 300)
            self.assertEqual(uaa.find(268), (RESULT_SUCCESS).to_bytes(4, "big"))
            self.assertEqual(uaa.find(602, 10415), b"sip:scscf.example.com")


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_TLS") == "1", "set IMS_HSS_TEST_TLS=1 TLS listener tests")
class HssDiameterTlsWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        openssl = shutil.which("openssl")
        if openssl is None:
            raise unittest.SkipTest("openssl required for ephemeral TLS listener test")
        cls.tempdir = tempfile.TemporaryDirectory(prefix="ims-hss-tls-")
        directory = pathlib.Path(cls.tempdir.name)
        cls.cert = directory / "hss.crt"
        cls.key = directory / "hss.key"
        try:
            subprocess.run(
                [
                    openssl,
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    str(cls.key),
                    "-out",
                    str(cls.cert),
                    "-days",
                    "1",
                    "-subj",
                    "/CN=localhost",
                    "-addext",
                    "subjectAltName=IP:127.0.0.1,DNS:localhost",
                ],
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                text=True,
            )
        except (OSError, subprocess.CalledProcessError) as exc:
            cls.tempdir.cleanup()
            raise unittest.SkipTest(f"could not generate ephemeral TLS certificate: {exc}")

        store = HssStore()
        store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
            }
        )
        server_context = _tls_context(str(cls.cert), str(cls.key))
        assert server_context is not None
        cls.server = DiameterServer(
            HssApplication(store, origin_host="hss.lab.local", origin_realm="example.com"),
            "127.0.0.1",
            0,
            server_context,
        )
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        deadline = time.monotonic() + 2.0
        while cls.server.bound_port == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        if cls.server.bound_port == 0:
            cls.server.close()
            cls.thread.join(timeout=2.0)
            cls.tempdir.cleanup()
            raise unittest.SkipTest("TLS listener could not start")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.close()
        cls.thread.join(timeout=2.0)
        cls.tempdir.cleanup()

    def test_tls_cer_then_cx_request(self) -> None:
        client_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        client_context.check_hostname = False
        client_context.verify_mode = ssl.CERT_REQUIRED
        client_context.load_verify_locations(cafile=str(self.cert))
        cer = build_message(
            flags=0x80,
            command=257,
            application=0,
            hop_by_hop=31,
            end_to_end=32,
            body=b"",
        )
        uar = build_message(
            flags=0x80,
            command=300,
            application=CX_APPLICATION,
            hop_by_hop=33,
            end_to_end=34,
            body=(
                _avp_text(263, "tls-session")
                + _avp_text(1, "alice@example.com")
                + _vendor_text(601, "sip:alice@example.com")
                + _vendor_text(602, "sip:scscf.example.com")
            ),
        )
        with socket.create_connection(("127.0.0.1", self.server.bound_port), timeout=2.0) as raw:
            with client_context.wrap_socket(raw, server_hostname="localhost") as conn:
                conn.sendall(cer)
                cea = parse_message(_read_diameter_frame(conn))
                self.assertEqual(cea.command, 257)
                self.assertEqual(cea.find(268), (RESULT_SUCCESS).to_bytes(4, "big"))
                self.assertIsNotNone(cea.find(260))
                conn.sendall(uar)
                uaa = parse_message(_read_diameter_frame(conn))
                self.assertEqual(uaa.command, 300)
                self.assertEqual(uaa.find(268), (RESULT_SUCCESS).to_bytes(4, "big"))


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_NETWORK") == "1", "set IMS_HSS_TEST_NETWORK=1 for listener tests")
class HssHttpWireTests(unittest.TestCase):
    def setUp(self) -> None:
        self.store = HssStore()
        self.store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
            }
        )
        self.server = SubscriberHTTPServer(("127.0.0.1", 0), self.store, "http-test-token-1234", "provision-token-1234")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def post(self, path: str, document: dict[str, object], token: str | None) -> tuple[int, dict[str, object]]:
        body = json.dumps(document).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = "Bearer " + token
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.server.server_address[1]}{path}",
            data=body,
            headers=headers,
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read())

    def test_authorize_and_provision_are_separate_scopes(self) -> None:
        request = {
            "schema": "madis.ims.subscriber.authorization.v1",
            "operation": "authorize-register",
            "public_identity": "sip:alice@example.com",
            "private_identity": "alice@example.com",
            "visited_network": "example.com",
            "server_name": "sip:scscf.example.com",
        }
        with self.assertRaises(urllib.error.HTTPError) as unauthorized:
            self.post("/ims/authorize", request, None)
        self.assertEqual(unauthorized.exception.code, 401)
        unauthorized.exception.close()
        status, response = self.post("/ims/authorize", request, "http-test-token-1234")
        self.assertEqual(status, 200)
        self.assertEqual(response["decision"], "allow")
        self.assertNotIn("xres", response)

        provision = {
            "schema": "madis.ims.subscriber.provision.v1",
            "operation": "provision",
            "public_identity": "sip:bob@example.com",
            "private_identity": "bob@example.com",
            "assigned_server_name": "sip:scscf.example.com",
            "xres_base64": base64.b64encode(b"xres-bob").decode("ascii"),
        }
        with self.assertRaises(urllib.error.HTTPError) as wrong_scope:
            self.post("/ims/provision", provision, "http-test-token-1234")
        self.assertEqual(wrong_scope.exception.code, 401)
        wrong_scope.exception.close()
        status, response = self.post("/ims/provision", provision, "provision-token-1234")
        self.assertEqual(status, 201)
        self.assertTrue(response["provisioned"])


if __name__ == "__main__":
    unittest.main()
