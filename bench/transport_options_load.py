#!/usr/bin/env python3
"""Load OPTIONS over TCP, TLS, or WSS against a running proxy.

This intentionally uses stateless OPTIONS so transport framing and connection
handling can be measured without provisioning routing data or a terminating UAS.
It is a benchmark fixture, not a capacity claim.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import os
import socket
import ssl
import struct
import threading
import time


def sip_options(index: int, transport: str) -> bytes:
    via_transport = "WS" if transport == "wss" else transport.upper()
    return (
        f"OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
        f"Via: SIP/2.0/{via_transport} 127.0.0.1:5090;branch=z9hG4bK-load-{index}\r\n"
        "From: <sip:load@127.0.0.1>;tag=load\r\n"
        "To: <sip:127.0.0.1>\r\n"
        f"Call-ID: load-{index}@127.0.0.1\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode()


def read_until(sock: socket.socket, marker: bytes, timeout: float) -> bytes:
    sock.settimeout(timeout)
    data = bytearray()
    deadline = time.monotonic() + timeout
    while marker not in data and time.monotonic() < deadline:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def read_exact(sock: socket.socket, count: int) -> bytes:
    data = bytearray()
    while len(data) < count:
        chunk = sock.recv(count - len(data))
        if not chunk:
            return b""
        data.extend(chunk)
    return bytes(data)


def ws_frame(payload: bytes) -> bytes:
    mask = os.urandom(4)
    length = len(payload)
    if length < 126:
        header = bytes([0x81, 0x80 | length])
    elif length <= 0xFFFF:
        header = bytes([0x81, 0x80 | 126]) + struct.pack("!H", length)
    else:
        header = bytes([0x81, 0x80 | 127]) + struct.pack("!Q", length)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return header + mask + masked


def ws_read_message(sock: socket.socket, timeout: float) -> bytes:
    sock.settimeout(timeout)
    header = read_exact(sock, 2)
    if len(header) < 2:
        return b""
    length = header[1] & 0x7F
    if length == 126:
        length_bytes = read_exact(sock, 2)
        if len(length_bytes) < 2:
            return b""
        length = struct.unpack("!H", length_bytes)[0]
    elif length == 127:
        length_bytes = read_exact(sock, 8)
        if len(length_bytes) < 8:
            return b""
        length = struct.unpack("!Q", length_bytes)[0]
    mask = b""
    if header[1] & 0x80:
        mask = read_exact(sock, 4)
        if len(mask) < 4:
            return b""
    payload = bytearray(read_exact(sock, length))
    if len(payload) < length:
        return b""
    if mask:
        payload = bytearray(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    return bytes(payload)


def sample(data: bytes, limit: int = 120) -> str:
    return data[:limit].replace(b"\r", b"\\r").replace(b"\n", b"\\n").decode("utf-8", "replace")


def connect(args: argparse.Namespace) -> socket.socket:
    raw = socket.create_connection((args.host, args.port), timeout=args.timeout)
    if args.transport == "tls":
        ctx = ssl._create_unverified_context()
        return ctx.wrap_socket(raw, server_hostname=args.host)
    if args.transport == "wss":
        key = base64.b64encode(os.urandom(16)).decode()
        request = (
            f"GET / HTTP/1.1\r\nHost: {args.host}:{args.port}\r\n"
            "Upgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
            "Sec-WebSocket-Protocol: sip\r\n\r\n"
        ).encode()
        raw.sendall(request)
        response = read_until(raw, b"\r\n\r\n", args.timeout)
        accept_src = (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
        expected = base64.b64encode(hashlib.sha1(accept_src).digest())
        if b"101" not in response or expected not in response:
            raise RuntimeError("websocket handshake failed")
    return raw


def worker(args: argparse.Namespace, worker_id: int, results: dict[str, int], lock: threading.Lock) -> None:
    ok = 0
    failed = 0
    attempted = 0
    try:
        sock = connect(args)
        try:
            for index in range(args.messages):
                attempted += 1
                payload = sip_options(worker_id * args.messages + index, args.transport)
                if args.transport == "wss":
                    sock.sendall(ws_frame(payload))
                    response = ws_read_message(sock, args.timeout)
                else:
                    sock.sendall(payload)
                    response = read_until(sock, b"\r\n\r\n", args.timeout)
                if b"SIP/2.0 200" in response:
                    ok += 1
                else:
                    failed += 1
                    if args.verbose:
                        with lock:
                            print(
                                f"worker={worker_id} response_missing_200 len={len(response)} "
                                f"sample={sample(response)!r}"
                            )
        finally:
            sock.close()
    except Exception as exc:
        failed += args.messages - attempted
        if args.verbose:
            with lock:
                print(f"worker={worker_id} error={type(exc).__name__}: {exc}")
    with lock:
        results["ok"] += ok
        results["failed"] += failed


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--transport", choices=["tcp", "tls", "wss"], required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--connections", type=int, default=100)
    parser.add_argument("--messages", type=int, default=10, help="messages per connection")
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()
    if args.connections < 1 or args.messages < 1:
        parser.error("connections and messages must be positive")

    started = time.monotonic()
    results = {"ok": 0, "failed": 0}
    lock = threading.Lock()
    threads = [
        threading.Thread(target=worker, args=(args, idx, results, lock), daemon=True)
        for idx in range(args.connections)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    elapsed = max(time.monotonic() - started, 0.001)
    total = args.connections * args.messages
    print(
        "transport={transport} connections={connections} messages={messages} "
        "total={total} ok={ok} failed={failed} elapsed_s={elapsed:.3f} mps={mps:.2f}".format(
            transport=args.transport,
            connections=args.connections,
            messages=args.messages,
            total=total,
            ok=results["ok"],
            failed=results["failed"],
            elapsed=elapsed,
            mps=total / elapsed,
        )
    )
    return 0 if results["ok"] == total and results["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
