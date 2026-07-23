#!/usr/bin/env python3
"""Deterministic UDP fault matrix for proxy transaction timers.

The local UAS deliberately drops, delays, duplicates, and reorders responses.
This exercises the proxy over real UDP without pretending that a unit test is
an independent network.
"""

from __future__ import annotations

import argparse
import os
import select
import socket
import subprocess
import threading
import time
import urllib.request


def header(message: bytes, name: bytes) -> bytes:
    wanted = name.lower() + b":"
    for line in message.split(b"\r\n"):
        if line.lower().startswith(wanted):
            return line.split(b":", 1)[1].strip()
    return b""


def vias(message: bytes) -> list[bytes]:
    result = []
    for line in message.split(b"\r\n"):
        if line.lower().startswith(b"via:"):
            result.append(line.split(b":", 1)[1].strip())
    return result


def response(request: bytes, code: int, reason: bytes, tag: bytes = b"uas") -> bytes:
    to = header(request, b"To")
    if b";tag=" not in to:
        to += b";tag=" + tag
    lines = [b"SIP/2.0 " + str(code).encode() + b" " + reason]
    lines.extend(b"Via: " + value for value in vias(request))
    lines.extend(
        [
            b"From: " + header(request, b"From"),
            b"To: " + to,
            b"Call-ID: " + header(request, b"Call-ID"),
            b"CSeq: " + header(request, b"CSeq"),
            b"Content-Length: 0",
            b"",
            b"",
        ]
    )
    return b"\r\n".join(lines)


class FaultUas:
    def __init__(self, port: int):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind(("127.0.0.1", port))
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.invites: dict[bytes, int] = {}
        self.thread.start()

    def run(self) -> None:
        while not self.stop.is_set():
            ready, _, _ = select.select([self.socket], [], [], 0.1)
            if not ready:
                continue
            packet, address = self.socket.recvfrom(65535)
            if packet.startswith(b"ACK "):
                continue
            if packet.startswith(b"BYE "):
                self.socket.sendto(response(packet, 200, b"OK"), address)
                continue
            if not packet.startswith(b"INVITE "):
                continue
            call_id = header(packet, b"Call-ID")
            count = self.invites.get(call_id, 0) + 1
            self.invites[call_id] = count
            if call_id.startswith(b"drop-") and count == 1:
                continue
            if call_id.startswith(b"reorder-"):
                self.socket.sendto(response(packet, 200, b"OK"), address)
                time.sleep(0.05)
                self.socket.sendto(response(packet, 180, b"Ringing"), address)
                self.socket.sendto(response(packet, 200, b"OK"), address)
                continue
            if call_id.startswith(b"delay-"):
                time.sleep(0.7)
            self.socket.sendto(response(packet, 100, b"Trying"), address)
            self.socket.sendto(response(packet, 180, b"Ringing"), address)
            self.socket.sendto(response(packet, 200, b"OK"), address)

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=2)
        self.socket.close()


def request(method: bytes, call_id: bytes, branch: bytes, cseq: int = 1) -> bytes:
    return b"\r\n".join(
        [
            method + b" sip:uas@mako.local SIP/2.0",
            b"Via: SIP/2.0/UDP 127.0.0.1:5099;branch=z9hG4bK-" + branch,
            b"From: <sip:caller@mako.local>;tag=caller-" + call_id,
            b"To: <sip:uas@mako.local>",
            b"Call-ID: " + call_id,
            b"CSeq: " + str(cseq).encode() + b" " + method,
            b"Contact: <sip:caller@127.0.0.1:5099>",
            b"Max-Forwards: 70",
            b"Content-Length: 0",
            b"",
            b"",
        ]
    )


def wait_ready(port: int) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/readyz", timeout=0.3) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def collect(sock: socket.socket, seconds: float) -> list[bytes]:
    sock.settimeout(0.1)
    deadline = time.monotonic() + seconds
    packets = []
    while time.monotonic() < deadline:
        try:
            packets.append(sock.recv(65535))
        except socket.timeout:
            pass
    return packets


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--base-port", type=int, default=18960)
    args = parser.parse_args()
    timing_scale = float(os.environ.get("FAULT_TIMING_SCALE", "1"))
    if timing_scale <= 0:
        raise ValueError("FAULT_TIMING_SCALE must be positive")
    proxy_port = args.base_port
    uas_port = args.base_port + 10
    admin_port = args.base_port + 20
    env = os.environ.copy()
    env.update(
        {
            "SIP_UDP_PORT": str(proxy_port),
            "SIP_TLS_PORT": str(args.base_port + 1),
            "SIP_WSS_PORT": str(args.base_port + 2),
            "SIP_ADMIN_PORT": str(admin_port),
            "SIP_UDP_WORKERS": "1",
            "SIP_TCP_WORKERS": "1",
        }
    )
    uas = FaultUas(uas_port)
    proxy_log = os.environ.get("FAULT_PROXY_LOG")
    log_handle = open(proxy_log, "w", encoding="utf-8") if proxy_log else None
    process = subprocess.Popen(
        [args.binary],
        env=env,
        stdout=log_handle if log_handle else subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_ready(admin_port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.bind(("127.0.0.1", 5099))
            client.settimeout(3)
            register = (
                b"REGISTER sip:mako.local SIP/2.0\r\n"
                b"Via: SIP/2.0/UDP 127.0.0.1:5099;branch=z9hG4bK-register\r\n"
                b"From: <sip:uas@mako.local>;tag=register\r\n"
                b"To: <sip:uas@mako.local>\r\n"
                b"Call-ID: register-fault\r\n"
                b"CSeq: 1 REGISTER\r\n"
                b"Contact: <sip:uas@127.0.0.1:"
                + str(uas_port).encode()
                + b";transport=udp>\r\nExpires: 300\r\nMax-Forwards: 70\r\nContent-Length: 0\r\n\r\n"
            )
            client.sendto(register, ("127.0.0.1", proxy_port))
            registered, _ = client.recvfrom(65535)
            if b"SIP/2.0 200" not in registered:
                raise RuntimeError("registration failed")
            if process.poll() is not None:
                raise RuntimeError(f"proxy exited after registration: {process.returncode}")

            # First INVITE is dropped by the UAS. The proxy must retransmit it
            # and eventually deliver the final response.
            drop = request(b"INVITE", b"drop-loss", b"drop-loss")
            client.sendto(drop, ("127.0.0.1", proxy_port))
            drop_packets = collect(client, 3.5 * timing_scale)
            if process.poll() is not None:
                raise RuntimeError(f"proxy exited during loss scenario: {process.returncode}")
            if uas.invites.get(b"drop-loss", 0) < 2:
                raise RuntimeError("proxy did not retransmit after upstream loss")
            if not any(b"SIP/2.0 200" in packet for packet in drop_packets):
                raise RuntimeError("lost-response scenario never completed")
            if sum(b"SIP/2.0 200" in packet for packet in drop_packets) < 2:
                raise RuntimeError("server transaction did not retransmit unacknowledged 2xx")

            reorder = request(b"INVITE", b"reorder-race", b"reorder-race")
            client.sendto(reorder, ("127.0.0.1", proxy_port))
            reorder_packets = collect(client, 1.5 * timing_scale)
            statuses = b" ".join(reorder_packets)
            if b"SIP/2.0 200" not in statuses or b"SIP/2.0 180" not in statuses:
                raise RuntimeError("reordered/duplicated response scenario incomplete")

            delay = request(b"INVITE", b"delay-timer", b"delay-timer")
            client.sendto(delay, ("127.0.0.1", proxy_port))
            delay_packets = collect(client, 2.5 * timing_scale)
            if uas.invites.get(b"delay-timer", 0) < 2:
                raise RuntimeError("timer retransmission was not observed during delay")
            if not any(b"SIP/2.0 200" in packet for packet in delay_packets):
                raise RuntimeError("delayed-response scenario never completed")
        print("fault matrix: loss/retransmit, unacknowledged 2xx, reorder/duplicate, and delay passed")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        uas.close()
        if log_handle:
            log_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
