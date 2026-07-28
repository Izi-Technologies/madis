#!/usr/bin/env python3
"""Hold many SIP/TCP connections and emit measurements.

This is a measurement fixture, not a capacity claim. It intentionally sends
OPTIONS rather than INVITE so connection retention can be measured separately
from call/dialog setup and media behavior.
"""

from __future__ import annotations

import argparse
import errno
import selectors
import socket
import time
from dataclasses import dataclass, field


def options(call_id: int) -> bytes:
    return (
        "OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
        "Via: SIP/2.0/TCP 127.0.0.1:5090;branch=z9hG4bK-capacity-"
        f"{call_id}\r\n"
        "From: <sip:capacity@127.0.0.1>;tag=capacity\r\n"
        "To: <sip:127.0.0.1>\r\n"
        f"Call-ID: capacity-{call_id}@127.0.0.1\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode()


@dataclass
class Peer:
    sock: socket.socket
    payload: bytes
    sent: int = 0
    received: bytearray = field(default_factory=bytearray)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5060)
    parser.add_argument("--connections", type=int, default=1000)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args()
    if args.connections < 1 or args.duration <= 0 or args.interval <= 0:
        parser.error("connections, duration, and interval must be positive")

    selector = selectors.DefaultSelector()
    peers: dict[int, Peer] = {}
    connected = 0
    failed = 0
    responses = 0
    sent = 0

    for index in range(args.connections):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setblocking(False)
        try:
            result = sock.connect_ex((args.host, args.port))
        except OSError:
            failed += 1
            sock.close()
            continue
        if result not in (0, errno.EINPROGRESS, errno.EWOULDBLOCK, errno.EALREADY, errno.EISCONN):
            failed += 1
            sock.close()
            continue
        peer = Peer(sock, options(index))
        peers[sock.fileno()] = peer
        selector.register(sock, selectors.EVENT_READ | selectors.EVENT_WRITE, peer)

    started = time.monotonic()
    deadline = started + args.duration
    next_send = started
    while peers and time.monotonic() < deadline:
        now = time.monotonic()
        timeout = max(0.0, min(0.25, next_send - now))
        for key, mask in selector.select(timeout):
            peer = key.data
            if mask & selectors.EVENT_WRITE and peer.sent == 0:
                try:
                    peer.sock.sendall(peer.payload)
                    peer.sent = 1
                    sent += 1
                    connected += 1
                    selector.modify(peer.sock, selectors.EVENT_READ, peer)
                except OSError:
                    selector.unregister(peer.sock)
                    peers.pop(peer.sock.fileno(), None)
                    peer.sock.close()
                    failed += 1
            if mask & selectors.EVENT_READ:
                try:
                    chunk = peer.sock.recv(65535)
                except OSError:
                    chunk = b""
                if not chunk:
                    selector.unregister(peer.sock)
                    peers.pop(peer.sock.fileno(), None)
                    peer.sock.close()
                    continue
                peer.received.extend(chunk)
                while b"\r\n\r\n" in peer.received:
                    end = peer.received.index(b"\r\n\r\n") + 4
                    message = bytes(peer.received[:end])
                    del peer.received[:end]
                    if message.startswith(b"SIP/2.0 "):
                        responses += 1

        now = time.monotonic()
        if now >= next_send:
            for peer in list(peers.values()):
                try:
                    peer.sock.sendall(peer.payload)
                    sent += 1
                except OSError:
                    selector.unregister(peer.sock)
                    peers.pop(peer.sock.fileno(), None)
                    peer.sock.close()
                    failed += 1
            next_send = now + args.interval

    open_at_end = len(peers)
    for peer in list(peers.values()):
        selector.unregister(peer.sock)
        peer.sock.close()
    selector.close()
    elapsed = max(time.monotonic() - started, 0.001)
    print(
        f"connections_requested={args.connections} connected={connected} "
        f"failed={failed} open_at_end={open_at_end} sends={sent} "
        f"responses={responses} elapsed_s={elapsed:.3f} "
        f"send_rate={sent / elapsed:.2f}"
    )
    return 0 if connected > 0 and failed == 0 else 1
if __name__ == "__main__":
    raise SystemExit(main())
