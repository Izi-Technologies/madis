#!/usr/bin/env python3
"""Verify CA-validated SIP-over-WSS outbound delivery.

The fixture acts as a minimal RFC 6455 WebSocket server behind TLS.  A SIP
REGISTER advertises a ``transport=wss`` contact, then an INVITE is routed to
that contact.  This deliberately tests the proxy's outbound WebRTC signaling
path rather than only its inbound WSS listener.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path


WS_MAGIC = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_certificates(openssl: str, directory: Path) -> tuple[Path, Path, Path]:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.crt"
    server_key = directory / "server.key"
    server_csr = directory / "server.csr"
    server_cert = directory / "server.crt"
    extensions = directory / "server.ext"
    run(
        [
            openssl,
            "req",
            "-x509",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(ca_key),
            "-out",
            str(ca_cert),
            "-days",
            "2",
            "-subj",
            "/CN=mako WSS test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:1",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )
    extensions.write_text(
        "basicConstraints=critical,CA:FALSE\n"
        "keyUsage=critical,digitalSignature,keyEncipherment\n"
        "extendedKeyUsage=serverAuth\n"
        "subjectAltName=DNS:localhost\n",
        encoding="ascii",
    )
    run(
        [
            openssl,
            "req",
            "-new",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(server_key),
            "-out",
            str(server_csr),
            "-subj",
            "/CN=localhost",
        ]
    )
    run(
        [
            openssl,
            "x509",
            "-req",
            "-in",
            str(server_csr),
            "-CA",
            str(ca_cert),
            "-CAkey",
            str(ca_key),
            "-CAcreateserial",
            "-out",
            str(server_cert),
            "-days",
            "2",
            "-sha256",
            "-extfile",
            str(extensions),
        ]
    )
    return ca_cert, server_cert, server_key


def read_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            raise RuntimeError("WSS peer closed before the complete frame arrived")
        data.extend(chunk)
    return bytes(data)


def read_headers(sock: socket.socket) -> bytes:
    data = bytearray()
    while b"\r\n\r\n" not in data:
        data.extend(sock.recv(4096))
        require(len(data) <= 16384, "WSS handshake headers exceeded the limit")
    return bytes(data)


def read_text_frame(sock: socket.socket) -> bytes:
    first, second = read_exact(sock, 2)
    require(first & 0x0F == 0x1, "outbound WSS payload was not a text frame")
    require(second & 0x80 != 0, "client WebSocket frame was not masked")
    length = second & 0x7F
    if length == 126:
        length = int.from_bytes(read_exact(sock, 2), "big")
    elif length == 127:
        length = int.from_bytes(read_exact(sock, 8), "big")
    require(length <= 1_048_576, "outbound WSS frame exceeded the test limit")
    mask = read_exact(sock, 4)
    payload = bytearray(read_exact(sock, length))
    for index in range(length):
        payload[index] ^= mask[index % 4]
    return bytes(payload)


def send_text_frame(sock: socket.socket, payload: bytes) -> None:
    length = len(payload)
    if length < 126:
        header = bytes((0x81, length))
    elif length < 65536:
        header = bytes((0x81, 126)) + length.to_bytes(2, "big")
    else:
        header = bytes((0x81, 127)) + length.to_bytes(8, "big")
    sock.sendall(header + payload)


def header_lines(message: bytes, name: bytes) -> list[bytes]:
    prefix = name.lower() + b":"
    return [
        line.split(b":", 1)[1].strip()
        for line in message.split(b"\r\n")
        if line.lower().startswith(prefix)
    ]


def one_header(message: bytes, name: bytes) -> bytes:
    values = header_lines(message, name)
    require(values, f"WSS INVITE missing {name.decode('ascii')} header")
    return values[0]


def sip_response(request: bytes, status: int, reason: bytes) -> bytes:
    vias = header_lines(request, b"Via")
    require(vias, "WSS INVITE missing Via header")
    to = one_header(request, b"To")
    if b";tag=" not in to.lower():
        to += b";tag=wss-peer"
    return (
        b"SIP/2.0 "
        + str(status).encode("ascii")
        + b" "
        + reason
        + b"\r\n"
        + b"\r\n".join(b"Via: " + via for via in vias)
        + b"\r\nFrom: "
        + one_header(request, b"From")
        + b"\r\nTo: "
        + to
        + b"\r\nCall-ID: "
        + one_header(request, b"Call-ID")
        + b"\r\nCSeq: "
        + one_header(request, b"CSeq")
        + b"\r\nContact: <sips:uas@localhost;transport=wss>\r\n"
        + b"Content-Length: 0\r\n\r\n"
    )


class WssFixture:
    def __init__(self, certificate: Path, key: Path, port: int) -> None:
        self.certificate = certificate
        self.key = key
        self.port = port
        self.ready = threading.Event()
        self.received = threading.Event()
        self.ack_received = threading.Event()
        self.bye_received = threading.Event()
        self.payload = b""
        self.error: Exception | None = None
        self.listener: socket.socket | None = None
        self.thread = threading.Thread(target=self._serve, daemon=True)

    def start(self) -> None:
        self.listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", self.port))
        self.listener.listen(4)
        self.listener.settimeout(10.0)
        self.thread.start()
        require(self.ready.wait(2.0), "WSS fixture did not start")

    def stop(self) -> None:
        if self.listener is not None:
            self.listener.close()
        self.thread.join(timeout=3.0)

    def _serve(self) -> None:
        require_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        require_context.load_cert_chain(str(self.certificate), str(self.key))
        try:
            self.ready.set()
            assert self.listener is not None
            raw, _ = self.listener.accept()
            with require_context.wrap_socket(raw, server_side=True) as tls:
                tls.settimeout(5.0)
                handshake = read_headers(tls)
                lines = handshake.split(b"\r\n")
                headers = {}
                for line in lines[1:]:
                    if b":" in line:
                        name, value = line.split(b":", 1)
                        headers[name.decode("ascii").lower()] = value.strip()
                require(lines[0].startswith(b"GET / HTTP/1.1"), "WSS default path was not /")
                require(headers.get("upgrade", b"").lower() == b"websocket", "missing WebSocket upgrade")
                require(headers.get("connection", b"").lower() == b"upgrade", "missing upgrade connection")
                key = headers.get("sec-websocket-key", b"")
                require(len(key) > 0, "missing Sec-WebSocket-Key")
                accept = base64.b64encode(hashlib.sha1(key + WS_MAGIC).digest())
                tls.sendall(
                    b"HTTP/1.1 101 Switching Protocols\r\n"
                    b"Upgrade: websocket\r\n"
                    b"Connection: Upgrade\r\n"
                    b"Sec-WebSocket-Accept: "
                    + accept
                    + b"\r\n\r\n"
                )
                self.payload = read_text_frame(tls)
                require(self.payload.startswith(b"INVITE "), "WSS peer did not receive INVITE")
                require(b"Content-Length:" in self.payload, "forwarded INVITE lost Content-Length")
                self.received.set()
                send_text_frame(tls, sip_response(self.payload, 180, b"Ringing"))
                send_text_frame(tls, sip_response(self.payload, 200, b"OK"))
                while True:
                    next_message = read_text_frame(tls)
                    if next_message.startswith(b"ACK "):
                        self.ack_received.set()
                        continue
                    if next_message.startswith(b"BYE "):
                        self.bye_received.set()
                        send_text_frame(tls, sip_response(next_message, 200, b"OK"))
                        return
        except socket.timeout as exc:  # surfaced by main after the process exits
            self.error = RuntimeError("WSS fixture timed out waiting for ACK")
            self.error.__cause__ = exc
            self.received.set()
        except Exception as exc:  # surfaced by main after the process exits
            self.error = exc
            self.received.set()


def wait_ready(admin_port: int) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{admin_port}/readyz", timeout=0.5) as response:
                if response.status == 200 and json.loads(response.read()).get("ready"):
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def response_status(response: bytes) -> int:
    try:
        return int(response.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return 0


def recv_response(udp: socket.socket, label: str) -> bytes:
    try:
        response, _ = udp.recvfrom(8192)
        return response
    except socket.timeout as exc:
        raise RuntimeError(f"timed out waiting for {label} from proxy") from exc


def exercise_proxy(udp_port: int, upstream_port: int, fixture: WssFixture) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        udp.bind(("127.0.0.1", 5090))
        udp.settimeout(5.0)
        register = (
            "REGISTER sip:example.test SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5090;branch=z9hG4bK-wss-register\r\n"
            "From: <sip:uas@example.test>;tag=wss-register\r\n"
            "To: <sip:uas@example.test>\r\n"
            "Call-ID: wss-register@example.test\r\n"
            "CSeq: 1 REGISTER\r\n"
            "Contact: <sips:uas@localhost:"
            f"{upstream_port};transport=wss>\r\n"
            "Expires: 300\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()
        udp.sendto(register, ("127.0.0.1", udp_port))
        registration_response, _ = udp.recvfrom(8192)
        require(response_status(registration_response) == 200, "WSS contact registration failed")

        invite = (
            "INVITE sip:uas@example.test SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5090;branch=z9hG4bK-wss-invite\r\n"
            "From: <sip:caller@example.test>;tag=wss-caller\r\n"
            "To: <sip:uas@example.test>\r\n"
            "Call-ID: wss-invite@example.test\r\n"
            "CSeq: 1 INVITE\r\n"
            "Contact: <sip:caller@127.0.0.1:5090>\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()
        udp.sendto(invite, ("127.0.0.1", udp_port))
        trying = recv_response(udp, "100 Trying")
        require(response_status(trying) == 100, "proxy did not return 100 Trying for WSS route")

        require(fixture.received.wait(5.0), "WSS upstream did not receive the INVITE")
        if fixture.error is not None:
            raise fixture.error
        ringing = recv_response(udp, "180 Ringing")
        require(response_status(ringing) == 180, "proxy did not forward WSS 180 Ringing")
        ok = recv_response(udp, "200 OK")
        require(response_status(ok) == 200, "proxy did not forward WSS 200 OK")

        ack = (
            "ACK sip:uas@example.test SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5090;branch=z9hG4bK-wss-ack\r\n"
            "From: <sip:caller@example.test>;tag=wss-caller\r\n"
            "To: <sip:uas@example.test>;tag=wss-peer\r\n"
            "Call-ID: wss-invite@example.test\r\n"
            "CSeq: 1 ACK\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()
        udp.sendto(ack, ("127.0.0.1", udp_port))
        require(fixture.ack_received.wait(5.0), "proxy did not reuse WSS association for ACK")

        bye = (
            "BYE sip:uas@example.test SIP/2.0\r\n"
            "Via: SIP/2.0/UDP 127.0.0.1:5090;branch=z9hG4bK-wss-bye\r\n"
            "From: <sip:caller@example.test>;tag=wss-caller\r\n"
            "To: <sip:uas@example.test>;tag=wss-peer\r\n"
            "Call-ID: wss-invite@example.test\r\n"
            "CSeq: 2 BYE\r\n"
            "Max-Forwards: 70\r\n"
            "Content-Length: 0\r\n\r\n"
        ).encode()
        udp.sendto(bye, ("127.0.0.1", udp_port))
        bye_response = recv_response(udp, "200 BYE")
        require(response_status(bye_response) == 200, "proxy did not forward WSS BYE response")
        require(fixture.bye_received.is_set(), "WSS upstream did not receive BYE")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--base-port", type=int, default=19460)
    args = parser.parse_args()
    openssl = shutil.which("openssl")
    require(openssl is not None, "openssl is required for WSS certificate validation")

    udp_port = args.base_port
    proxy_wss_port = args.base_port + 2
    admin_port = args.base_port + 20
    upstream_port = args.base_port + 10
    with tempfile.TemporaryDirectory(prefix="mako-wss-") as temp:
        ca_cert, server_cert, server_key = make_certificates(openssl, Path(temp))
        fixture = WssFixture(server_cert, server_key, upstream_port)
        fixture.start()
        env = os.environ.copy()
        env.update(
            {
                "SIP_UDP_PORT": str(udp_port),
                "SIP_TLS_PORT": str(args.base_port + 1),
                "SIP_WSS_PORT": str(proxy_wss_port),
                "SIP_ADMIN_PORT": str(admin_port),
                "SIP_UDP_WORKERS": "1",
                "SIP_TCP_WORKERS": "1",
                "SIP_IPV6": "0",
                "SIP_UPSTREAM_CA": str(ca_cert),
                "SIP_UPSTREAM_TLS_INSECURE": "0",
            }
        )
        root = Path(__file__).resolve().parents[1]
        log_path = os.environ.get("WSS_PROXY_LOG", "")
        proxy_log = open(log_path, "w", encoding="utf-8") if log_path else None
        process = subprocess.Popen(
            [args.binary],
            cwd=root,
            env=env,
            stdout=proxy_log if proxy_log is not None else subprocess.DEVNULL,
            stderr=subprocess.STDOUT if proxy_log is not None else subprocess.DEVNULL,
        )
        try:
            wait_ready(admin_port)
            exercise_proxy(udp_port, upstream_port, fixture)
            print("WSS outbound matrix: CA validation, RFC 6455 framing, 180/200 polling, ACK/BYE reuse")
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            fixture.stop()
            if proxy_log is not None:
                proxy_log.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"WSS outbound matrix: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
