#!/usr/bin/env python3
"""Dependency-free UDP/TCP/TLS/WSS/admin interoperability smoke matrix.

This is intentionally a wire-level client, not an internal unit test. It is
used by the sanitizer and CI jobs to exercise the same framing and transport
boundaries as an independent SIP stack would.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import subprocess
import sys
import time
import urllib.request


def sip_options(transport: str, branch: str, call_id: str) -> bytes:
    return (
        f"OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
        f"Via: SIP/2.0/{transport} 127.0.0.1:5090;branch=z9hG4bK-{branch}\r\n"
        "From: <sip:test@127.0.0.1>;tag=matrix\r\n"
        "To: <sip:127.0.0.1>\r\n"
        f"Call-ID: {call_id}@127.0.0.1\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def wait_ready(admin_port: int, deadline: float, admin_token: str) -> None:
    url = f"http://127.0.0.1:{admin_port}/readyz"
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                if response.status == 200 and json.loads(response.read()).get("ready"):
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def read_socket(sock: socket.socket, expected: bytes, count: int = 1) -> bytes:
    sock.settimeout(3.0)
    data = bytearray()
    while data.count(expected) < count:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--base-port", type=int, default=18560)
    args = parser.parse_args()

    udp_port = args.base_port
    tls_port = args.base_port + 1
    wss_port = args.base_port + 2
    admin_port = args.base_port + 20
    admin_token = "transport-matrix-admin-token"
    env = os.environ.copy()
    env.update(
        {
            "SIP_UDP_PORT": str(udp_port),
            "SIP_TLS_PORT": str(tls_port),
            "SIP_WSS_PORT": str(wss_port),
            "SIP_ADMIN_PORT": str(admin_port),
            "SIP_ADMIN_TOKEN": admin_token,
            "SIP_UDP_WORKERS": os.environ.get("MADIS_MATRIX_UDP_WORKERS", "2"),
            "SIP_TCP_WORKERS": "1",
        }
    )

    log_path = os.environ.get("MADIS_TEST_LOG", os.devnull)
    log = open(log_path, "w", encoding="utf-8")
    process = subprocess.Popen([args.binary], env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        wait_ready(admin_port, time.monotonic() + 8.0, admin_token)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
            udp.settimeout(3.0)
            udp.sendto(sip_options("UDP", "matrix-udp", "matrix-udp"), ("127.0.0.1", udp_port))
            response, _ = udp.recvfrom(8192)
            require(b"SIP/2.0 200" in response, "UDP did not return 200")

        with socket.create_connection(("127.0.0.1", udp_port), timeout=3.0) as tcp:
            request = sip_options("TCP", "matrix-tcp-1", "matrix-tcp-1")
            request += sip_options("TCP", "matrix-tcp-2", "matrix-tcp-2")
            tcp.sendall(request)
            response = read_socket(tcp, b"SIP/2.0 200", 2)
            require(response.count(b"SIP/2.0 200") >= 2, "TCP pipeline did not return two 200 responses")

        context = ssl._create_unverified_context()
        with context.wrap_socket(socket.create_connection(("127.0.0.1", tls_port), timeout=3), server_hostname="127.0.0.1") as tls:
            tls.sendall(sip_options("TLS", "matrix-tls", "matrix-tls"))
            response = read_socket(tls, b"SIP/2.0 200")
            require(b"SIP/2.0 200" in response, "TLS did not return 200")

        with socket.create_connection(("127.0.0.1", wss_port), timeout=3) as wss:
            wss.sendall(
                (
                    f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{wss_port}\r\n"
                    "Upgrade: websocket\r\nConnection: Upgrade\r\n"
                    "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    "Sec-WebSocket-Version: 13\r\n\r\n"
                ).encode()
            )
            response = read_socket(wss, b"101 Switching Protocols")
            require(b"101 Switching Protocols" in response, "WSS did not return 101")

        health_request = urllib.request.Request(
            f"http://127.0.0.1:{admin_port}/healthz",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        with urllib.request.urlopen(health_request, timeout=3) as health:
            body = json.loads(health.read())
            require(health.status == 200 and body.get("ok") is True, "health check failed")
        print("transport matrix: UDP 200, TCP pipeline 2x200, TLS 200, WSS 101, admin ready/health")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"transport matrix: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
