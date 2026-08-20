#!/usr/bin/env python3
import argparse
import base64
import os
import socket
import ssl
import time


def sip_options(host: str, transport: str, call_id: str) -> bytes:
    return (
        f"OPTIONS sip:{host} SIP/2.0\r\n"
        f"Via: SIP/2.0/{transport} 127.0.0.1:5090;branch=z9hG4bK-{call_id};rport\r\n"
        "Max-Forwards: 70\r\n"
        "From: <sip:nat-check@example.invalid>;tag=natcheck\r\n"
        f"To: <sip:{host}>\r\n"
        f"Call-ID: {call_id}@nat-check\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Contact: <sip:nat-check@example.invalid>\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode()


def read_status(data: bytes) -> str:
    first = data.split(b"\r\n", 1)[0].decode("utf-8", "replace")
    return first if first else "no-status"


def check_udp(host: str, port: int, timeout: float) -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(sip_options(host, "UDP", "udp"), (host, port))
    data, _ = s.recvfrom(4096)
    s.close()
    return read_status(data)


def check_tcp(host: str, port: int, timeout: float, use_tls: bool) -> str:
    raw = socket.create_connection((host, port), timeout=timeout)
    raw.settimeout(timeout)
    if use_tls:
        ctx = ssl.create_default_context()
        raw = ctx.wrap_socket(raw, server_hostname=host)
    raw.sendall(sip_options(host, "TLS" if use_tls else "TCP", "tls" if use_tls else "tcp"))
    data = raw.recv(4096)
    raw.close()
    return read_status(data)


def check_wss(host: str, port: int, timeout: float) -> str:
    key = base64.b64encode(os.urandom(16)).decode()
    raw = socket.create_connection((host, port), timeout=timeout)
    raw.settimeout(timeout)
    ctx = ssl.create_default_context()
    s = ctx.wrap_socket(raw, server_hostname=host)
    req = (
        f"GET / HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Protocol: sip\r\n\r\n"
    )
    s.sendall(req.encode())
    data = s.recv(4096)
    s.close()
    return read_status(data)


def main() -> int:
    p = argparse.ArgumentParser(description="Check public SIP NAT transports with OPTIONS probes.")
    p.add_argument("--host", required=True)
    p.add_argument("--udp-port", type=int, default=5060)
    p.add_argument("--tcp-port", type=int, default=5060)
    p.add_argument("--tls-port", type=int, default=5061)
    p.add_argument("--wss-port", type=int, default=7443)
    p.add_argument("--timeout", type=float, default=3.0)
    args = p.parse_args()

    checks = [
        ("udp", lambda: check_udp(args.host, args.udp_port, args.timeout)),
        ("tcp", lambda: check_tcp(args.host, args.tcp_port, args.timeout, False)),
        ("tls", lambda: check_tcp(args.host, args.tls_port, args.timeout, True)),
        ("wss", lambda: check_wss(args.host, args.wss_port, args.timeout)),
    ]
    ok = 0
    for name, fn in checks:
        start = time.time()
        try:
            status = fn()
            print(f"{name}: {status} ({(time.time() - start) * 1000:.0f} ms)")
            ok += 1
        except Exception as exc:
            print(f"{name}: failed: {exc}")
    return 0 if ok == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
