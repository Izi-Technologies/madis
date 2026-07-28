"""Opt-in two-subscriber IMS smoke test against a built Madis worker.

Run with:

    IMS_END_TO_END=1 MADIS_BIN=./main \
      python3 -m unittest lab.test_ims_end_to_end -v

The test starts the lab HSS adapter as a real TCP peer, starts Madis on
loopback-only high ports, registers two users through Cx/AKA, and drives an
originating INVITE through provisional response, answer, ACK, and BYE.  When
the media sidecar is enabled for the test, it also checks SDP rewriting and
bidirectional RTP forwarding.  It is not part of the default CI job because
no worker binary or privileged SIP ports are assumed there.
"""

from __future__ import annotations

import base64
import hashlib
import http.client
import os
import re
import socket
import shutil
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
import uuid
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HSS_SCRIPT = ROOT / "lab" / "ims_hss.py"
MADIS_BIN = Path(os.environ.get("MADIS_BIN", str(ROOT / "main"))).expanduser().resolve()
RUN_E2E = os.environ.get("IMS_END_TO_END") == "1" and MADIS_BIN.is_file() and os.access(MADIS_BIN, os.X_OK)
RUN_E2E_TLS = RUN_E2E and os.environ.get("IMS_END_TO_END_TLS") == "1"


def _free_port(kind: int) -> int:
    sock = socket.socket(socket.AF_INET, kind)
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _wait_tcp(host: str, port: int, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25):
                return
        except OSError as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"TCP port {host}:{port} did not become ready: {last_error}")


def _wait_media(host: str, port: int, timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    cookie = b"ims-e2e-media"
    packet = cookie + b" d7:command4:pinge"
    last_error: Exception | None = None
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        while time.monotonic() < deadline:
            try:
                sock.settimeout(min(0.25, max(0.05, deadline - time.monotonic())))
                sock.sendto(packet, (host, port))
                response, _ = sock.recvfrom(4096)
                if response.startswith(cookie + b" ") and b"6:result2:ok" in response:
                    return
            except OSError as exc:
                last_error = exc
            time.sleep(0.05)
    finally:
        sock.close()
    raise AssertionError(f"RTP sidecar port {host}:{port} did not become ready: {last_error}")


def _wait_diameter_tls(host: str, port: int, ca_file: Path, timeout: float = 8.0) -> None:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = True
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_verify_locations(cafile=str(ca_file))
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.25) as raw:
                with context.wrap_socket(raw, server_hostname="localhost"):
                    return
        except (OSError, ssl.SSLError) as exc:
            last_error = exc
        time.sleep(0.05)
    raise AssertionError(f"TLS Diameter port {host}:{port} did not become ready: {last_error}")


def _wait_http(host: str, port: int, token: str = "", timeout: float = 8.0) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(f"http://{host}:{port}/healthz")
            if token:
                request.add_header("Authorization", f"Bearer {token}")
            with urllib.request.urlopen(request, timeout=0.25) as response:
                if response.status == 200:
                    return
        except urllib.error.HTTPError as exc:
            last_error = exc
            exc.close()
            time.sleep(0.05)
        except (OSError, urllib.error.URLError) as exc:
            last_error = exc
            time.sleep(0.05)
    raise AssertionError(f"HTTP port {host}:{port} did not become ready: {last_error}")


def _headers(message: str) -> dict[str, str]:
    head = message.split("\r\n\r\n", 1)[0]
    values: dict[str, str] = {}
    for line in head.split("\r\n")[1:]:
        if ":" not in line:
            continue
        name, value = line.split(":", 1)
        values[name.lower()] = value.strip()
    return values


def _status(message: str) -> int:
    fields = message.split("\r\n", 1)[0].split()
    return int(fields[1])


def _sdp_media_port(message: str) -> int:
    body = message.split("\r\n\r\n", 1)[1]
    for line in body.split("\r\n"):
        if line.startswith("m=audio "):
            fields = line.split()
            if len(fields) >= 2:
                return int(fields[1])
    raise AssertionError("SIP message did not contain an audio SDP media line")


def _digest_params(value: str) -> dict[str, str]:
    params: dict[str, str] = {}
    for match in re.finditer(r"([A-Za-z][A-Za-z0-9_-]*)\s*=\s*(?:\"([^\"]*)\"|([^,\s]+))", value):
        params[match.group(1).lower()] = match.group(2) if match.group(2) is not None else match.group(3)
    return params


def _header_line(headers: dict[str, str], name: str) -> str:
    return f"{name}: {headers[name.lower()]}\r\n"


def _header_lines(message: str, name: str) -> str:
    values = []
    for line in message.split("\r\n")[1:]:
        if ":" not in line:
            continue
        header_name, value = line.split(":", 1)
        if header_name.lower() == name.lower():
            values.append(value.strip())
    return "".join(f"{name}: {value}\r\n" for value in values)


class SipClient:
    def __init__(self) -> None:
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", 0))
        self.socket.settimeout(2.0)
        self.address = self.socket.getsockname()

    def send(self, message: str, port: int) -> None:
        self.socket.sendto(message.encode("ascii"), ("127.0.0.1", port))

    def receive(self, predicate, timeout: float = 5.0) -> str:
        deadline = time.monotonic() + timeout
        seen: list[str] = []
        while time.monotonic() < deadline:
            self.socket.settimeout(max(0.1, deadline - time.monotonic()))
            try:
                raw, _ = self.socket.recvfrom(65535)
            except socket.timeout:
                break
            message = raw.decode("ascii", "replace")
            seen.append(" | ".join(message.split("\r\n")[:7]))
            if predicate(message):
                return message
        raise AssertionError(f"SIP message did not arrive; saw {seen}")

    def close(self) -> None:
        self.socket.close()


@unittest.skipUnless(RUN_E2E, "set IMS_END_TO_END=1 and provide an executable MADIS_BIN")
class TwoSubscriberImsSmokeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.hss_diameter_port = _free_port(socket.SOCK_STREAM)
        self.hss_http_port = _free_port(socket.SOCK_STREAM)
        self.sip_port = _free_port(socket.SOCK_DGRAM)
        self.admin_port = _free_port(socket.SOCK_STREAM)
        self.tls_port = _free_port(socket.SOCK_STREAM)
        self.wss_port = _free_port(socket.SOCK_STREAM)
        self.media_control_port = _free_port(socket.SOCK_DGRAM)
        self.media_min = 41000
        self.media_max = 41127
        self.alice = SipClient()
        self.bob = SipClient()
        self.alice_media = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.alice_media.bind(("127.0.0.1", 0))
        self.alice_media.settimeout(2.0)
        self.bob_media = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.bob_media.bind(("127.0.0.1", 0))
        self.bob_media.settimeout(2.0)
        self.processes: list[subprocess.Popen] = []
        self.tempdir = tempfile.TemporaryDirectory(prefix="madis-ims-e2e-")
        self.use_diameter_tls = RUN_E2E_TLS
        self.diameter_cert: Path | None = None
        self.diameter_key: Path | None = None
        self.seed = Path(self.tempdir.name) / "subscribers.json"
        self.seed.write_text(
            "{\"subscribers\":["
            "{\"public_identity\":\"sip:alice@example.com\",\"private_identity\":\"alice@example.com\",\"assigned_server_name\":\"sip:scscf.example.com\",\"xres_base64\":\"" + base64.b64encode(b"xres-alice").decode("ascii") + "\"},"
            "{\"public_identity\":\"sip:bob@example.com\",\"private_identity\":\"bob@example.com\",\"assigned_server_name\":\"sip:scscf.example.com\",\"xres_base64\":\"" + base64.b64encode(b"xres-bob").decode("ascii") + "\"}"
            "]}",
        )
        if self.use_diameter_tls:
            self._generate_diameter_tls_material()
        try:
            self._start_hss()
            self._start_media()
            self._start_madis()
        except Exception:
            self.tearDown()
            raise

    def tearDown(self) -> None:
        self.alice.close()
        self.bob.close()
        for media_socket in (
            getattr(self, "alice_media", None),
            getattr(self, "bob_media", None),
        ):
            if media_socket is not None:
                media_socket.close()
        for process in reversed(getattr(self, "processes", [])):
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)
            if process.stdout is not None:
                output = process.stdout.read()
                if output:
                    bounded = output[-8192:]
                    sys.stderr.write("\n--- IMS smoke child log ---\n" + bounded)
                    debug_path = os.environ.get("IMS_E2E_DEBUG_LOG")
                    if debug_path:
                        with open(debug_path, "a", encoding="utf-8") as debug:
                            debug.write("\n--- IMS smoke child log ---\n" + bounded)
        if hasattr(self, "tempdir"):
            self.tempdir.cleanup()

    def _generate_diameter_tls_material(self) -> None:
        openssl = shutil.which("openssl")
        if openssl is None:
            self.fail("openssl is required for IMS_END_TO_END_TLS=1")
        self.diameter_cert = Path(self.tempdir.name) / "hss.crt"
        self.diameter_key = Path(self.tempdir.name) / "hss.key"
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
                    str(self.diameter_key),
                    "-out",
                    str(self.diameter_cert),
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
            self.fail(f"could not generate ephemeral Diameter TLS certificate: {exc}")

    def _start_hss(self) -> None:
        command = [
            sys.executable,
            str(HSS_SCRIPT),
            "--seed-json",
            str(self.seed),
            "--diameter-host",
            "127.0.0.1",
            "--diameter-port",
            str(self.hss_diameter_port),
            "--http-host",
            "127.0.0.1",
            "--http-port",
            str(self.hss_http_port),
        ]
        if self.use_diameter_tls:
            assert self.diameter_cert is not None
            assert self.diameter_key is not None
            command.extend(
                [
                    "--diameter-cert",
                    str(self.diameter_cert),
                    "--diameter-key",
                    str(self.diameter_key),
                ]
            )
        hss_env = os.environ.copy()
        process = subprocess.Popen(command, env=hss_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.processes.append(process)
        if self.use_diameter_tls:
            assert self.diameter_cert is not None
            _wait_diameter_tls("127.0.0.1", self.hss_diameter_port, self.diameter_cert)
        else:
            _wait_tcp("127.0.0.1", self.hss_diameter_port)

    def _start_media(self) -> None:
        command = [
            sys.executable,
            str(ROOT / "media" / "rtp_module.py"),
            "--control-host",
            "127.0.0.1",
            "--control-port",
            str(self.media_control_port),
            "--media-bind",
            "127.0.0.1",
            "--media-ip",
            "127.0.0.1",
            "--media-min",
            str(self.media_min),
            "--media-max",
            str(self.media_max),
            "--max-sessions",
            "8",
            "--session-timeout",
            "30",
        ]
        process = subprocess.Popen(
            command,
            env=os.environ.copy(),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        self.processes.append(process)
        _wait_media("127.0.0.1", self.media_control_port)

    def _start_madis(self) -> None:
        env = os.environ.copy()
        for key in (
            "SIP_DB_URL",
            "SIP_IMS_SUBSCRIBER_URL",
            "SIP_IMS_SUBSCRIBER_TOKEN",
            "SIP_DIAMETER_CA",
            "SIP_DIAMETER_CLIENT_CERT",
            "SIP_DIAMETER_CLIENT_KEY",
        ):
            env.pop(key, None)
        diameter_tls = "1" if self.use_diameter_tls else "0"
        diameter_allow_plaintext = "0" if self.use_diameter_tls else "1"
        diameter_ca = str(self.diameter_cert) if self.diameter_cert is not None else ""
        diameter_host = "localhost" if self.use_diameter_tls else "127.0.0.1"
        env.update(
            {
                "SIP_BIND_IP": "127.0.0.1",
                "SIP_IPV6": "0",
                "SIP_UDP_PORT": str(self.sip_port),
                "SIP_ADMIN_PORT": str(self.admin_port),
                "SIP_TLS_PORT": str(self.tls_port),
                "SIP_WSS_PORT": str(self.wss_port),
                "SIP_ADMIN_TOKEN": "ims-e2e-admin-token-1234",
                "SIP_REALM": "example.com",
                "SIP_NODE_ID": "ims-e2e-node",
                "SIP_NODE_ADDR": "127.0.0.1",
            "SIP_DIAMETER_HOST": diameter_host,
                "SIP_DIAMETER_PORT": str(self.hss_diameter_port),
            "SIP_DIAMETER_TLS": diameter_tls,
            "SIP_DIAMETER_ALLOW_PLAINTEXT": diameter_allow_plaintext,
            "SIP_DIAMETER_CA": diameter_ca,
                "SIP_DIAMETER_ORIGIN_HOST": "scscf.lab.local",
                "SIP_DIAMETER_ORIGIN_REALM": "example.com",
                "SIP_DIAMETER_DEST_REALM": "example.com",
                "SIP_RTPENGINE_ENABLED": "1",
                "SIP_RTPENGINE_HOST": "127.0.0.1",
                "SIP_RTPENGINE_PORT": str(self.media_control_port),
                "SIP_IMS_CX": "1",
                "SIP_IMS_AKA": "1",
                "SIP_IMS_AKA_SCHEME": "Digest-AKAv1-MD5",
                "SIP_IMS_ROLE": "scscf",
                "SIP_IMS_VISITED_NETWORK": "example.com",
                "SIP_IMS_SERVER_NAME": "sip:scscf.example.com",
                "SIP_IMS_DEST_HOST": "hss.lab.local",
                "SIP_IMS_SESSION": "1",
            }
        )
        process = subprocess.Popen([str(MADIS_BIN)], env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.processes.append(process)
        _wait_http("127.0.0.1", self.admin_port, "ims-e2e-admin-token-1234")

    def _register(self, client: SipClient, user: str, xres: bytes) -> None:
        call_id = f"register-{user}-{uuid.uuid4().hex[:12]}"
        from_header = f"<sip:{user}@example.com>;tag={user}-register"
        contact = f"<sip:{user}@127.0.0.1:{client.address[1]}>"

        def make_register(cseq: int, branch: str, authorization: str = "") -> str:
            extra = f"Authorization: {authorization}\r\n" if authorization else ""
            return (
                "REGISTER sip:example.com SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP 127.0.0.1:{client.address[1]};branch={branch}\r\n"
                "Max-Forwards: 70\r\n"
                f"From: {from_header}\r\n"
                f"To: <sip:{user}@example.com>\r\n"
                f"Call-ID: {call_id}\r\n"
                f"CSeq: {cseq} REGISTER\r\n"
                f"Contact: {contact}\r\n"
                "Expires: 300\r\n"
                f"{extra}Content-Length: 0\r\n\r\n"
            )

        client.send(make_register(1, "z9hG4bK-" + uuid.uuid4().hex), self.sip_port)
        challenge = client.receive(lambda message: _status(message) in (401, 407))
        self.assertEqual(_status(challenge), 401)
        auth_header = _headers(challenge).get("www-authenticate", "")
        params = _digest_params(auth_header)
        self.assertEqual(params.get("algorithm", "").lower(), "akav1-md5")
        self.assertEqual(params.get("qop"), "auth")
        uri = "sip:example.com"
        cnonce = "ims-e2e-cnonce"
        nc = "00000001"
        ha1 = hashlib.md5(f"{user}@example.com:example.com:{xres.decode('ascii')}".encode("ascii")).hexdigest()
        ha2 = hashlib.md5(f"REGISTER:{uri}".encode("ascii")).hexdigest()
        response = hashlib.md5(f"{ha1}:{params['nonce']}:{nc}:{cnonce}:auth:{ha2}".encode("ascii")).hexdigest()
        authorization = (
            f'Digest username="{user}@example.com", realm="example.com", nonce="{params["nonce"]}", '
            f'uri="{uri}", response="{response}", algorithm=AKAv1-MD5, qop=auth, nc={nc}, cnonce="{cnonce}"'
        )
        client.send(make_register(2, "z9hG4bK-" + uuid.uuid4().hex, authorization), self.sip_port)
        accepted = client.receive(lambda message: _status(message) == 200)
        self.assertEqual(_status(accepted), 200)

    def _invite(self) -> tuple[str, str, str, str]:
        call_id = "call-" + uuid.uuid4().hex[:12]
        alice_tag = "alice-call"
        branch = "z9hG4bK-" + uuid.uuid4().hex
        sdp = (
            "v=0\r\n"
            "o=- 1 1 IN IP4 127.0.0.1\r\n"
            "s=-\r\n"
            "c=IN IP4 127.0.0.1\r\n"
            "t=0 0\r\n"
            f"m=audio {self.alice_media.getsockname()[1]} RTP/AVP 0\r\n"
        )
        message = (
            "INVITE sip:bob@example.com SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{self.alice.address[1]};branch={branch}\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
            "To: <sip:bob@example.com>\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 INVITE\r\n"
            f"Contact: <sip:alice@127.0.0.1:{self.alice.address[1]}>\r\n"
            "Content-Type: application/sdp\r\n"
            f"Content-Length: {len(sdp)}\r\n\r\n{sdp}"
    )
        self.alice.send(message, self.sip_port)
        challenge = self.alice.receive(lambda item: _status(item) == 401)
        challenge_params = _digest_params(_headers(challenge).get("www-authenticate", ""))
        self.assertEqual(challenge_params.get("qop"), "auth")
        cnonce = "ims-e2e-invite-cnonce"
        nc = "00000001"
        ha1 = hashlib.md5(
            f"alice@example.com:example.com:xres-alice".encode("ascii")
        ).hexdigest()
        ha2 = hashlib.md5(
            b"INVITE:sip:bob@example.com"
        ).hexdigest()
        response = hashlib.md5(
            f"{ha1}:{challenge_params['nonce']}:{nc}:{cnonce}:auth:{ha2}".encode("ascii")
        ).hexdigest()
        authorization = (
            'Digest username="alice@example.com", realm="example.com", '
            f'nonce="{challenge_params["nonce"]}", uri="sip:bob@example.com", '
            f'response="{response}", algorithm=AKAv1-MD5, qop=auth, nc={nc}, '
            f'cnonce="{cnonce}"'
        )
        auth_message = message.replace(
            f"branch={branch}", f"branch={branch}-authenticated"
        ).replace(
            "CSeq: 1 INVITE\r\n",
            "CSeq: 2 INVITE\r\n"
        ).replace(
            "Content-Type: application/sdp\r\n",
            f"Authorization: {authorization}\r\nContent-Type: application/sdp\r\n"
        )
        self.alice.send(auth_message, self.sip_port)
        return call_id, alice_tag, branch, sdp

    def test_two_subscribers_register_call_and_clear(self) -> None:
        self._register(self.alice, "alice", b"xres-alice")
        self._register(self.bob, "bob", b"xres-bob")
        call_id, alice_tag, _, _ = self._invite()
        invite = self.bob.receive(lambda message: message.startswith("INVITE "))
        invite_headers = _headers(invite)
        offer_media_port = _sdp_media_port(invite)
        self.assertNotEqual(offer_media_port, self.alice_media.getsockname()[1])
        bob_tag = "bob-call"
        ringing = (
        "SIP/2.0 180 Ringing\r\n"
        + _header_lines(invite, "Via")
        + f"{_header_line(invite_headers, 'from')}"
        + f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        + f"{_header_line(invite_headers, 'call-id')}"
        + f"{_header_line(invite_headers, 'cseq')}"
        + "Content-Length: 0\r\n\r\n"
        )
        self.bob.send(ringing, self.sip_port)
        self.alice.receive(lambda message: _status(message) == 180)
        answer_sdp = (
            "v=0\r\n"
            "o=- 2 2 IN IP4 127.0.0.1\r\n"
            "s=-\r\n"
            "c=IN IP4 127.0.0.1\r\n"
            "t=0 0\r\n"
            f"m=audio {self.bob_media.getsockname()[1]} RTP/AVP 0\r\n"
        )
        ok = (
        "SIP/2.0 200 OK\r\n"
        + _header_lines(invite, "Via")
        + f"{_header_line(invite_headers, 'from')}"
        + f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
        + f"{_header_line(invite_headers, 'call-id')}"
        + f"{_header_line(invite_headers, 'cseq')}"
        + f"Contact: <sip:bob@127.0.0.1:{self.bob.address[1]}>\r\n"
        + "Content-Type: application/sdp\r\n"
        + f"Content-Length: {len(answer_sdp)}\r\n\r\n{answer_sdp}"
        )
        self.bob.send(ok, self.sip_port)
        accepted = self.alice.receive(lambda message: _status(message) == 200)
        answer_media_port = _sdp_media_port(accepted)
        self.assertNotEqual(answer_media_port, self.bob_media.getsockname()[1])
        alice_packet = b"\x80\x00\x00\x01\x00\x00\x00\x01\x12\x34\x56\x78alice-media"
        self.alice_media.sendto(alice_packet, ("127.0.0.1", offer_media_port))
        forwarded_to_bob, _ = self.bob_media.recvfrom(4096)
        self.assertEqual(forwarded_to_bob, alice_packet)
        bob_packet = b"\x80\x00\x00\x02\x00\x00\x00\x02\x87\x65\x43\x21bob-media"
        self.bob_media.sendto(bob_packet, ("127.0.0.1", answer_media_port))
        forwarded_to_alice, _ = self.alice_media.recvfrom(4096)
        self.assertEqual(forwarded_to_alice, bob_packet)
        accepted_headers = _headers(accepted)
        ack = (
            "ACK sip:bob@example.com SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{self.alice.address[1]};branch=z9hG4bK-{uuid.uuid4().hex}\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
            f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 1 ACK\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        self.alice.send(ack, self.sip_port)
        self.bob.receive(lambda message: message.startswith("ACK "))
        bye = (
            "BYE sip:bob@example.com SIP/2.0\r\n"
            f"Via: SIP/2.0/UDP 127.0.0.1:{self.alice.address[1]};branch=z9hG4bK-{uuid.uuid4().hex}\r\n"
            "Max-Forwards: 70\r\n"
            f"From: <sip:alice@example.com>;tag={alice_tag}\r\n"
            f"To: <sip:bob@example.com>;tag={bob_tag}\r\n"
            f"Call-ID: {call_id}\r\n"
            "CSeq: 2 BYE\r\n"
            "Content-Length: 0\r\n\r\n"
        )
        self.alice.send(bye, self.sip_port)
        bye_request = self.bob.receive(lambda message: message.startswith("BYE "))
        bye_headers = _headers(bye_request)
        bye_ok = (
            "SIP/2.0 200 OK\r\n"
            + _header_lines(bye_request, "Via")
            + f"{_header_line(bye_headers, 'from')}"
            + f"{_header_line(bye_headers, 'to')}"
            + f"{_header_line(bye_headers, 'call-id')}"
            + f"{_header_line(bye_headers, 'cseq')}"
            + "Content-Length: 0\r\n\r\n"
        )
        self.bob.send(bye_ok, self.sip_port)
        self.alice.receive(lambda message: _status(message) == 200 and _headers(message).get("cseq", "").startswith("2 BYE"))


if __name__ == "__main__":
    unittest.main()
