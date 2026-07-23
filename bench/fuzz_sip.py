#!/usr/bin/env python3
"""Small process-level SIP ingress fuzzer with no third-party dependencies."""

from __future__ import annotations

import argparse
import os
import random
import socket
import subprocess
import time
import urllib.request


BASE = (
    b"OPTIONS sip:127.0.0.1 SIP/2.0\r\n"
    b"Via: SIP/2.0/UDP 127.0.0.1:5090;branch=z9hG4bK-fuzz\r\n"
    b"From: <sip:fuzz@127.0.0.1>;tag=fuzz\r\n"
    b"To: <sip:127.0.0.1>\r\n"
    b"Call-ID: fuzz@127.0.0.1\r\n"
    b"CSeq: 1 OPTIONS\r\n"
    b"Max-Forwards: 70\r\n"
    b"Content-Length: 0\r\n\r\n"
)


def mutate(rng: random.Random, index: int) -> bytes:
    cases = [
        BASE[: index % len(BASE)],
        BASE.replace(b"SIP/2.0", b"SIP/9.9", 1),
        BASE.replace(b"Content-Length: 0", b"Content-Length: 9999999", 1),
        BASE.replace(b"Content-Length: 0", b"Content-Length: 0\r\nContent-Length: 1", 1),
        BASE.replace(b"branch=z9hG4bK-fuzz", b"branch=z9hG4bK", 1),
        BASE.replace(b"OPTIONS", b"BAD METHOD", 1),
        BASE.replace(b"Max-Forwards: 70", b"Max-Forwards: -1", 1),
        BASE.replace(b"Via:", b"Via\x00:", 1),
        BASE.replace(b"\r\n\r\n", b"\r\n\t orphan\r\n\r\n", 1),
        b"\x00\xff\x01" + bytes(rng.randrange(0, 256) for _ in range(rng.randrange(1, 2048))),
    ]
    value = bytearray(rng.choice(cases))
    if index % 7 == 0:
        value.extend(b"A" * 65000)
    elif value and index % 3 == 0:
        value[rng.randrange(len(value))] ^= 1 << rng.randrange(0, 8)
    return bytes(value)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=3261)
    parser.add_argument("--base-port", type=int, default=18660)
    args = parser.parse_args()
    if args.iterations < 1:
        raise ValueError("iterations must be positive")

    udp_port = args.base_port
    admin_port = args.base_port + 20
    env = os.environ.copy()
    env.update(
        {
            "SIP_UDP_PORT": str(udp_port),
            "SIP_TLS_PORT": str(args.base_port + 1),
            "SIP_WSS_PORT": str(args.base_port + 2),
            "SIP_ADMIN_PORT": str(admin_port),
            "SIP_UDP_WORKERS": "2",
            "SIP_TCP_WORKERS": "1",
        }
    )
    process = subprocess.Popen([args.binary], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    rng = random.Random(args.seed)
    try:
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{admin_port}/readyz", timeout=0.3) as response:
                    if response.status == 200:
                        break
            except Exception:
                time.sleep(0.05)
        else:
            raise RuntimeError("proxy did not become ready")

        for index in range(args.iterations):
            if process.poll() is not None:
                raise RuntimeError(f"proxy exited during fuzzing at case {index}: {process.returncode}")
            payload = mutate(rng, index)
            # Keep margin below platform-specific UDP maximums; larger
            # mutations exercise stream framing instead.
            if index % 2 == 0 and len(payload) <= 60000:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
                    udp.settimeout(0.05)
                    try:
                        udp.sendto(payload, ("127.0.0.1", udp_port))
                        udp.recvfrom(8192)
                    except (TimeoutError, socket.timeout, ConnectionResetError):
                        pass
            else:
                try:
                    with socket.create_connection(("127.0.0.1", udp_port), timeout=0.2) as tcp:
                        tcp.sendall(payload)
                        tcp.settimeout(0.05)
                        try:
                            tcp.recv(8192)
                        except (TimeoutError, socket.timeout, ConnectionResetError):
                            pass
                except (ConnectionRefusedError, TimeoutError, socket.timeout):
                    raise RuntimeError(f"TCP listener unavailable at case {index}")
        require_alive = process.poll() is None
        if not require_alive:
            raise RuntimeError(f"proxy exited after fuzzing: {process.returncode}")
        print(f"SIP ingress fuzz: {args.iterations} cases survived (seed={args.seed})")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
