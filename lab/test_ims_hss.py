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
        SH_APPLICATION,
        HssApplication,
        HssStore,
        DiameterServer,
        SubscriberHTTPServer,
        RESULT_SUCCESS,
        RESULT_UNKNOWN_USER,
        THREEGPP_VENDOR,
        RTR_PERMANENT_TERMINATION,
        RTR_REASON_NAMES,
        _avp,
        _avp_text,
        _avp_u32,
        _parse_avps,
        _subscriber_json,
        _subscriber_profile_xml,
        _vendor_bytes,
        _vendor_grouped,
        _vendor_text,
        authorization_document,
        build_message,
        parse_message,
        _tls_context,
    )
except ImportError:
    from ims_hss import (
        CX_APPLICATION,
        SH_APPLICATION,
        HssApplication,
        HssStore,
        DiameterServer,
        SubscriberHTTPServer,
        RESULT_SUCCESS,
        RESULT_UNKNOWN_USER,
        THREEGPP_VENDOR,
        RTR_PERMANENT_TERMINATION,
        RTR_REASON_NAMES,
        _avp,
        _avp_text,
        _avp_u32,
        _parse_avps,
        _subscriber_json,
        _subscriber_profile_xml,
        _vendor_bytes,
        _vendor_grouped,
        _vendor_text,
        authorization_document,
        build_message,
        parse_message,
        _tls_context,
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
        self.assertEqual(len([a for a in response.avps if a.code == 612]), 1)
        nested = _parse_avps(item)
        auth = next(a.value for a in nested if a.code == 609 and a.vendor == THREEGPP_VENDOR)
        self.assertEqual(len(auth), 32)  # RAND(16) || AUTN-like(16)

    def test_mar_multi_vector_count(self) -> None:
        body = self.identity_body(303) + _avp_u32(607, 3, vendor=THREEGPP_VENDOR)
        response = parse_message(self.app.handle(self.request(303, body)))
        self.assertEqual(response.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        items = [a for a in response.avps if a.code == 612 and a.vendor == THREEGPP_VENDOR]
        self.assertEqual(len(items), 3)

    def test_mar_auts_resync_requires_issued_rand(self) -> None:
        # First MAR issues RAND.
        first = parse_message(self.app.handle(self.request(303, self.identity_body(303))))
        self.assertEqual(first.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        item_raw = first.find(612, THREEGPP_VENDOR)
        self.assertIsNotNone(item_raw)
        nested = _parse_avps(item_raw)
        authenticate = None
        for avp in nested:
            if avp.code == 609 and avp.vendor == THREEGPP_VENDOR:
                authenticate = avp.value
        self.assertIsNotNone(authenticate)
        assert authenticate is not None
        rand = authenticate[:16]
        auts = b"0123456789abcd"  # 14-byte lab AUTS

        # AUTS with unknown RAND fails closed.
        bad_item = (
            _avp_u32(613, 0, vendor=THREEGPP_VENDOR)
            + _vendor_text(608, "Digest-AKAv1-MD5")
            + _vendor_bytes(609, b"x" * 16)
            + _vendor_bytes(610, auts)
        )
        bad_body = (
            _avp_text(263, "session;alice")
            + _avp_text(1, "alice@example.com")
            + _vendor_text(601, "sip:alice@example.com")
            + _vendor_text(602, "sip:scscf.example.com")
            + _avp_u32(607, 1, vendor=THREEGPP_VENDOR)
            + _vendor_grouped(612, bad_item)
        )
        bad = parse_message(self.app.handle(self.request(303, bad_body)))
        self.assertEqual(bad.find(268), RESULT_UNKNOWN_USER.to_bytes(4, "big"))

        # AUTS with issued RAND succeeds and returns a new vector.
        good_item = (
            _avp_u32(613, 0, vendor=THREEGPP_VENDOR)
            + _vendor_text(608, "Digest-AKAv1-MD5")
            + _vendor_bytes(609, rand)
            + _vendor_bytes(610, auts)
        )
        good_body = (
            _avp_text(263, "session;alice-resync")
            + _avp_text(1, "alice@example.com")
            + _vendor_text(601, "sip:alice@example.com")
            + _vendor_text(602, "sip:scscf.example.com")
            + _avp_u32(607, 2, vendor=THREEGPP_VENDOR)
            + _vendor_grouped(612, good_item)
        )
        good = parse_message(self.app.handle(self.request(303, good_body)))
        self.assertEqual(good.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        good_items = [a for a in good.avps if a.code == 612 and a.vendor == THREEGPP_VENDOR]
        self.assertEqual(len(good_items), 2)
        new_auth = None
        for avp in _parse_avps(good_items[0].value):
            if avp.code == 609 and avp.vendor == THREEGPP_VENDOR:
                new_auth = avp.value
        self.assertIsNotNone(new_auth)
        self.assertNotEqual(new_auth, authenticate)

    def test_unknown_subscriber_and_server_mismatch_fail_closed(self) -> None:
        unknown = self.request(300, _avp_text(1, "missing@example.com") + _vendor_text(601, "sip:missing@example.com") + _vendor_text(602, "sip:scscf.example.com"))
        self.assertEqual(parse_message(self.app.handle(unknown)).find(268), RESULT_UNKNOWN_USER.to_bytes(4, "big"))
        mismatch = self.request(300, self.identity_body(300).replace(b"sip:scscf.example.com", b"sip:other.example.com"))
        self.assertEqual(parse_message(self.app.handle(mismatch)).find(268), RESULT_UNKNOWN_USER.to_bytes(4, "big"))

    def test_malformed_diameter_request_returns_no_answer(self) -> None:
        self.assertEqual(self.app.handle(b"not-a-diameter-message"), b"")
        self.assertEqual(self.app.handle(b"\x01\x00\x00\x14\x80\x00\x01\x2c"), b"")

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


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_TLS") == "1", "set IMS_HSS_TEST_TLS=1 HTTPS listener tests")
class HssHttpsWireTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        openssl = shutil.which("openssl")
        if openssl is None:
            raise unittest.SkipTest("openssl required for HTTPS listener tests")
        cls.tempdir = tempfile.TemporaryDirectory(prefix="ims-hss-http-tls-")
        cls.cert = pathlib.Path(cls.tempdir.name) / "hss.crt"
        cls.key = pathlib.Path(cls.tempdir.name) / "hss.key"
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
            raise unittest.SkipTest(f"could not generate HTTPS certificate: {exc}")

        store = HssStore()
        store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
            }
        )
        cls.server = SubscriberHTTPServer(
            ("127.0.0.1", 0),
            store,
            "https-test-token-1234",
            "provision-token-1234",
        )
        context = _tls_context(str(cls.cert), str(cls.key))
        assert context is not None
        cls.server.socket = context.wrap_socket(cls.server.socket, server_side=True)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=2.0)
        cls.tempdir.cleanup()

    def test_authorize_over_https(self) -> None:
        request = {
            "schema": "madis.ims.subscriber.authorization.v1",
            "operation": "authorize-register",
            "public_identity": "sip:alice@example.com",
            "private_identity": "alice@example.com",
            "visited_network": "example.com",
            "server_name": "sip:scscf.example.com",
        }
        body = json.dumps(request).encode("utf-8")
        http_request = urllib.request.Request(
            f"https://127.0.0.1:{self.server.server_address[1]}/ims/authorize",
            data=body,
            headers={
                "Authorization": "Bearer https-test-token-1234",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = True
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(cafile=str(self.cert))
        with urllib.request.urlopen(http_request, context=context, timeout=2.0) as response:
            document = json.loads(response.read())
        self.assertEqual(response.status, 200)
        self.assertEqual(document["decision"], "allow")
        self.assertNotIn("xres", document)


class HssRtrPprTests(unittest.TestCase):
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

    def test_rtr_sent_to_connected_peer(self) -> None:
        server_sock, client_sock = socket.socketpair()
        try:
            self.app.send_rtr("sip:alice@example.com", "alice@example.com", RTR_PERMANENT_TERMINATION, server_sock)
            client_sock.settimeout(2.0)
            header = b""
            while len(header) < 20:
                header += client_sock.recv(20 - len(header))
            length = int.from_bytes(header[1:4], "big")
            rest = b""
            while len(rest) < length - 20:
                rest += client_sock.recv(length - 20 - len(rest))
            msg = parse_message(header + rest)
            self.assertEqual(msg.command, 304)
            self.assertTrue(msg.flags & 0x80)  # Request bit set
            self.assertEqual(msg.application, CX_APPLICATION)
            self.assertEqual(msg.find(1), b"alice@example.com")  # User-Name
            self.assertEqual(msg.find(601, THREEGPP_VENDOR), b"sip:alice@example.com")
            # Deregistration-Reason grouped AVP present
            dereg = msg.find(615, THREEGPP_VENDOR)
            self.assertIsNotNone(dereg)
            nested = _parse_avps(dereg)
            reason_code = next(a for a in nested if a.code == 616 and a.vendor == THREEGPP_VENDOR)
            self.assertEqual(struct.unpack("!I", reason_code.value)[0], RTR_PERMANENT_TERMINATION)
        finally:
            server_sock.close()
            client_sock.close()

    def test_ppr_sent_to_connected_peer(self) -> None:
        server_sock, client_sock = socket.socketpair()
        try:
            profile = {"associated_uris": ["sip:alice@example.com"]}
            self.app.send_ppr("sip:alice@example.com", "alice@example.com", profile, server_sock)
            client_sock.settimeout(2.0)
            header = b""
            while len(header) < 20:
                header += client_sock.recv(20 - len(header))
            length = int.from_bytes(header[1:4], "big")
            rest = b""
            while len(rest) < length - 20:
                rest += client_sock.recv(length - 20 - len(rest))
            msg = parse_message(header + rest)
            self.assertEqual(msg.command, 305)
            self.assertTrue(msg.flags & 0x80)  # Request bit set
            self.assertEqual(msg.find(1), b"alice@example.com")
            user_data = msg.find(606, THREEGPP_VENDOR)
            self.assertIsNotNone(user_data)
            self.assertIn(b"Sh-Data", user_data)
        finally:
            server_sock.close()
            client_sock.close()


class HssShInterfaceTests(unittest.TestCase):
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

    def sh_request(self, command: int, body: bytes) -> bytes:
        return build_message(flags=0x80, command=command, application=SH_APPLICATION, hop_by_hop=11, end_to_end=22, body=body)

    def test_sh_udr_returns_profile(self) -> None:
        body = _avp_text(263, "sh-session-udr") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com")
        response = parse_message(self.app.handle(self.sh_request(306, body)))
        self.assertEqual(response.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        user_data = response.find(606, THREEGPP_VENDOR)
        self.assertIsNotNone(user_data)
        self.assertIn(b"Sh-Data", user_data)
        self.assertIn(b"sip:alice@example.com", user_data)

    def test_sh_pur_updates_profile(self) -> None:
        new_profile = json.dumps({"associated_uris": ["sip:alice@example.com", "sip:alice2@example.com"]}).encode("utf-8")
        body = _avp_text(263, "sh-session-pur") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com") + _vendor_bytes(606, new_profile)
        response = parse_message(self.app.handle(self.sh_request(307, body)))
        self.assertEqual(response.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        # Verify the profile was updated via a subsequent UDR.
        udr_body = _avp_text(263, "sh-session-udr2") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com")
        udr_response = parse_message(self.app.handle(self.sh_request(306, udr_body)))
        user_data = udr_response.find(606, THREEGPP_VENDOR)
        self.assertIsNotNone(user_data)
        self.assertIn(b"sip:alice2@example.com", user_data)


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_NETWORK") == "1", "set IMS_HSS_TEST_NETWORK=1 for listener tests")
class HssAdminEndpointTests(unittest.TestCase):
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
        app = HssApplication(self.store, origin_host="hss.lab.local", origin_realm="example.com")
        self.diameter = DiameterServer(app, "127.0.0.1", 0)
        self.diameter_thread = threading.Thread(target=self.diameter.serve_forever, daemon=True)
        self.diameter_thread.start()
        deadline = time.monotonic() + 2.0
        while self.diameter.bound_port == 0 and time.monotonic() < deadline:
            time.sleep(0.001)
        self.http_server = SubscriberHTTPServer(("127.0.0.1", 0), self.store, "", "provision-token-1234", self.diameter)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()

    def tearDown(self) -> None:
        self.http_server.shutdown()
        self.http_server.server_close()
        self.http_thread.join(timeout=2.0)
        self.diameter.close()
        self.diameter_thread.join(timeout=2.0)

    def admin_post(self, path: str, document: dict[str, object]) -> tuple[int, dict[str, object]]:
        body = json.dumps(document).encode("utf-8")
        request = urllib.request.Request(
            f"http://127.0.0.1:{self.http_server.server_address[1]}{path}",
            data=body,
            headers={"Content-Type": "application/json", "Authorization": "Bearer provision-token-1234"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=2.0) as response:
            return response.status, json.loads(response.read())

    def test_rtr_http_endpoint(self) -> None:
        status, response = self.admin_post("/admin/rtr", {
            "public_identity": "sip:alice@example.com",
            "private_identity": "alice@example.com",
            "reason": "PERMANENT_TERMINATION",
        })
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertIn("peers_notified", response)

    def test_ppr_http_endpoint(self) -> None:
        status, response = self.admin_post("/admin/ppr", {
            "public_identity": "sip:alice@example.com",
            "private_identity": "alice@example.com",
            "profile": {"associated_uris": ["sip:alice@example.com"]},
        })
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertIn("peers_notified", response)


class HssSubscriberCrudTests(unittest.TestCase):
    """Unit tests for subscriber CRUD on HssStore and JSON helper."""

    def setUp(self) -> None:
        self.store = HssStore()
        self.alice = self.store.provision(
            {
                "public_identity": "sip:alice@example.com",
                "private_identity": "alice@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
                "service_profile": {"associated_uris": ["sip:alice@example.com"]},
            }
        )

    def test_subscriber_crud_lifecycle(self) -> None:
        # Create
        sub = self.store.provision(
            {
                "public_identity": "sip:bob@example.com",
                "private_identity": "bob@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-bob").decode("ascii"),
            }
        )
        self.assertEqual(sub.public_identity, "sip:bob@example.com")
        # Read
        found = self.store.find("sip:bob@example.com")
        self.assertIsNotNone(found)
        self.assertEqual(found.public_identity, "sip:bob@example.com")
        # Update
        updated = self.store.update("sip:bob@example.com", {"assigned_server_name": "sip:scscf2.example.com"})
        self.assertIsNotNone(updated)
        self.assertEqual(updated.assigned_server_name, "sip:scscf2.example.com")
        # Delete
        self.assertTrue(self.store.remove("sip:bob@example.com"))
        self.assertIsNone(self.store.find("sip:bob@example.com"))

    def test_subscriber_list(self) -> None:
        self.store.provision(
            {
                "public_identity": "sip:bob@example.com",
                "private_identity": "bob@example.com",
                "assigned_server_name": "sip:scscf.example.com",
                "xres_base64": base64.b64encode(b"xres-bob").decode("ascii"),
            }
        )
        all_subs = self.store.list_all()
        self.assertEqual(len(all_subs), 2)
        identities = {s.public_identity for s in all_subs}
        self.assertIn("sip:alice@example.com", identities)
        self.assertIn("sip:bob@example.com", identities)

    def test_subscriber_enable_disable(self) -> None:
        sub = self.store.set_enabled("sip:alice@example.com", False)
        self.assertIsNotNone(sub)
        self.assertFalse(sub.enabled)
        # Disabled subscriber is not authorized
        self.assertIsNone(self.store.authorize("sip:alice@example.com", "alice@example.com"))
        # Re-enable
        sub = self.store.set_enabled("sip:alice@example.com", True)
        self.assertTrue(sub.enabled)
        self.assertIsNotNone(self.store.authorize("sip:alice@example.com", "alice@example.com"))

    def test_crud_never_returns_xres(self) -> None:
        doc = _subscriber_json(self.alice)
        self.assertNotIn("xres", doc)
        self.assertNotIn("xres_base64", doc)
        serialized = json.dumps(doc)
        self.assertNotIn("xres-alice", serialized)

    def test_sar_returns_user_data_profile(self) -> None:
        app = HssApplication(self.store, origin_host="hss.lab.local", origin_realm="example.com")
        body = _avp_text(263, "session;alice") + _avp_text(1, "alice@example.com") + _vendor_text(601, "sip:alice@example.com") + _vendor_text(602, "sip:scscf.example.com")
        raw = build_message(flags=0x80, command=301, application=CX_APPLICATION, hop_by_hop=11, end_to_end=22, body=body)
        response = parse_message(app.handle(raw))
        self.assertEqual(response.find(268), RESULT_SUCCESS.to_bytes(4, "big"))
        # Server-Name present
        self.assertEqual(response.find(602, THREEGPP_VENDOR), b"sip:scscf.example.com")
        # User-Data AVP (code 606, vendor 10415) present with XML profile
        user_data = response.find(606, THREEGPP_VENDOR)
        self.assertIsNotNone(user_data)
        xml = user_data.decode("utf-8")
        self.assertIn("<IMSSubscription>", xml)
        self.assertIn("<ServiceProfile>", xml)
        self.assertIn("sip:alice@example.com", xml)
        # Must not contain XRES
        self.assertNotIn("xres", xml.lower())


@unittest.skipUnless(os.environ.get("IMS_HSS_TEST_NETWORK") == "1", "set IMS_HSS_TEST_NETWORK=1 for listener tests")
class HssAdminCrudHttpTests(unittest.TestCase):
    """HTTP-level tests for the /admin/subscribers CRUD API."""

    def setUp(self) -> None:
        self.store = HssStore()
        self.token = "admin-test-token-1234"
        self.server = SubscriberHTTPServer(("127.0.0.1", 0), self.store, self.token, "provision-token-1234")
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2.0)

    def _request(self, method: str, path: str, body: dict | None = None, token: str | None = None):
        data = json.dumps(body).encode("utf-8") if body is not None else None
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(self.base + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                return resp.status, json.loads(resp.read())
        except urllib.error.HTTPError as exc:
            result = json.loads(exc.read()) if exc.readable() else {}
            exc.close()
            return exc.code, result

    def _provision_alice(self) -> None:
        self._request("POST", "/admin/subscribers", {
            "public_identity": "sip:alice@example.com",
            "private_identity": "alice@example.com",
            "assigned_server_name": "sip:scscf.example.com",
            "xres_base64": base64.b64encode(b"xres-alice").decode("ascii"),
            "service_profile": {"associated_uris": ["sip:alice@example.com"]},
        }, self.token)

    def test_subscriber_crud_lifecycle(self) -> None:
        # Create
        status, doc = self._request("POST", "/admin/subscribers", {
            "public_identity": "sip:bob@example.com",
            "private_identity": "bob@example.com",
            "assigned_server_name": "sip:scscf.example.com",
            "xres_base64": base64.b64encode(b"xres-bob").decode("ascii"),
        }, self.token)
        self.assertEqual(status, 201)
        self.assertEqual(doc["public_identity"], "sip:bob@example.com")
        # Read
        status, doc = self._request("GET", "/admin/subscribers/sip:bob@example.com", token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(doc["public_identity"], "sip:bob@example.com")
        # Update
        status, doc = self._request("PUT", "/admin/subscribers/sip:bob@example.com", {
            "assigned_server_name": "sip:scscf2.example.com",
        }, self.token)
        self.assertEqual(status, 200)
        self.assertEqual(doc["assigned_server_name"], "sip:scscf2.example.com")
        # Delete
        status, doc = self._request("DELETE", "/admin/subscribers/sip:bob@example.com", token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(doc["ok"])
        # Confirm gone
        status, _ = self._request("GET", "/admin/subscribers/sip:bob@example.com", token=self.token)
        self.assertEqual(status, 404)

    def test_subscriber_list(self) -> None:
        self._provision_alice()
        status, doc = self._request("GET", "/admin/subscribers", token=self.token)
        self.assertEqual(status, 200)
        self.assertIsInstance(doc, list)
        self.assertEqual(len(doc), 1)
        self.assertEqual(doc[0]["public_identity"], "sip:alice@example.com")

    def test_subscriber_enable_disable(self) -> None:
        self._provision_alice()
        # Disable
        status, doc = self._request("POST", "/admin/subscribers/sip:alice@example.com/disable", token=self.token)
        self.assertEqual(status, 200)
        self.assertFalse(doc["enabled"])
        # Enable
        status, doc = self._request("POST", "/admin/subscribers/sip:alice@example.com/enable", token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(doc["enabled"])

    def test_crud_requires_auth_token(self) -> None:
        self._provision_alice()
        # No token -> 401 for each verb
        for method, path in [
            ("GET", "/admin/subscribers"),
            ("GET", "/admin/subscribers/sip:alice@example.com"),
            ("POST", "/admin/subscribers"),
            ("PUT", "/admin/subscribers/sip:alice@example.com"),
            ("DELETE", "/admin/subscribers/sip:alice@example.com"),
            ("POST", "/admin/subscribers/sip:alice@example.com/enable"),
        ]:
            body = {"public_identity": "sip:x@example.com", "private_identity": "x@example.com", "assigned_server_name": "sip:s.example.com", "xres_base64": base64.b64encode(b"x").decode()} if method in ("POST", "PUT") else None
            status, _ = self._request(method, path, body=body)
            self.assertEqual(status, 401, f"{method} {path} should require auth")

    def test_crud_never_returns_xres(self) -> None:
        self._provision_alice()
        for method, path in [
            ("GET", "/admin/subscribers"),
            ("GET", "/admin/subscribers/sip:alice@example.com"),
        ]:
            status, doc = self._request(method, path, token=self.token)
            self.assertEqual(status, 200)
            serialized = json.dumps(doc)
            self.assertNotIn("xres", serialized)


if __name__ == "__main__":
    unittest.main()
