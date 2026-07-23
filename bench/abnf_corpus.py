#!/usr/bin/env python3
"""Deterministic generated-style RFC 3261 ingress corpus.

This is a process-level grammar corpus, not a claim that the proxy contains a
complete generated ABNF parser.  Valid cases are crossed across compact and
long headers, quoted display names, URI escaping/parameters, IPv4/IPv6
authorities, and Via parameters.  Invalid cases mutate one grammar rule at a
time and must receive a 4xx response.
"""

from __future__ import annotations

import argparse
import itertools
import os
import socket
import subprocess
import sys
import time
import urllib.request


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def message(index: int, compact: bool, quoted: bool, host: str, uri: str, params: str) -> bytes:
    names = {
        "via": "v" if compact else "Via",
        "from": "f" if compact else "From",
        "to": "t" if compact else "To",
        "call": "i" if compact else "Call-ID",
        "length": "l" if compact else "Content-Length",
    }
    display = '"Doe, Jane"' if quoted else "Doe Jane"
    via_host = f"[{host}]" if ":" in host else host
    via_params = f";branch=z9hG4bK-corpus-{index}{params}"
    return (
        f"OPTIONS {uri} SIP/2.0\r\n"
        f"{names['via']}: SIP/2.0/UDP {via_host}:5060{via_params}\r\n"
        f"{names['from']}: {display} <sip:alice@{via_host}>;tag=corpus{index}\r\n"
        f"{names['to']}: <sip:{via_host}>\r\n"
        f"{names['call']}: corpus-{index}@example.test\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        f"{names['length']}: 0\r\n\r\n"
    ).encode()


def status(response: bytes) -> int:
    try:
        return int(response.split(b" ", 2)[1])
    except (IndexError, ValueError):
        return 0


def wait_ready(admin_port: int) -> None:
    deadline = time.monotonic() + 8
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{admin_port}/readyz", timeout=0.4) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def send(sock: socket.socket, port: int, payload: bytes) -> bytes:
    sock.sendto(payload, ("127.0.0.1", port))
    try:
        response, _ = sock.recvfrom(8192)
        return response
    except socket.timeout:
        return b""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--base-port", type=int, default=19260)
    args = parser.parse_args()

    udp_port = args.base_port
    admin_port = args.base_port + 20
    env = os.environ.copy()
    env.update(
        {
            "SIP_UDP_PORT": str(udp_port),
            "SIP_TLS_PORT": str(args.base_port + 1),
            "SIP_WSS_PORT": str(args.base_port + 2),
            "SIP_ADMIN_PORT": str(admin_port),
            "SIP_UDP_WORKERS": "1",
            "SIP_TCP_WORKERS": "1",
        }
    )
    process = subprocess.Popen([args.binary], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    valid_cases = []
    index = 0
    for compact, quoted, host, params in itertools.product(
        (False, True),
        (False, True),
        ("127.0.0.1", "2001:db8::10"),
        ("", ";rport", ";rport=5060;received=192.0.2.20;maddr=198.51.100.8;ttl=64"),
    ):
        uri_host = f"[{host}]" if ":" in host else host
        uri = f"sip:alice:pa%3Ass@{uri_host};transport=udp?subject=hello%20world"
        valid_cases.append(message(index, compact, quoted, host, uri, params))
        index += 1

    base = message(999, False, True, "127.0.0.1", "sip:127.0.0.1", "")
    invalid_cases = [
        ("bad-version", base.replace(b"SIP/2.0", b"SIP/9.9", 1)),
        ("cseq-method-case", base.replace(b"CSeq: 1 OPTIONS", b"CSeq: 1 options", 1)),
        ("duplicate-from", base.replace(b"To: <sip:127.0.0.1>", b"From: <sip:other@127.0.0.1>;tag=other\r\nTo: <sip:127.0.0.1>", 1)),
        ("duplicate-max-forwards", base.replace(b"Max-Forwards: 70", b"Max-Forwards: 70\r\nMax-Forwards: 69", 1)),
        ("content-length-mismatch", base.replace(b"Content-Length: 0", b"Content-Length: 4", 1)),
        ("empty-branch", base.replace(b"branch=z9hG4bK-corpus-999", b"branch=z9hG4bK", 1)),
        ("bad-rport", base.replace(b";branch=z9hG4bK-corpus-999", b";branch=z9hG4bK-corpus-999;rport=65536", 1)),
        ("bad-via-name", base.replace(b";branch=z9hG4bK-corpus-999", b";branch=z9hG4bK-corpus-999;bad name=value", 1)),
        ("orphan-fold", base.replace(b"Via:", b"\tcontinued\r\nVia:", 1)),
        ("header-control", base.replace(b"Max-Forwards: 70", b"Max-Forwards: 7\x00", 1)),
        ("unsupported-extension", base.replace(b"Max-Forwards: 70", b"Max-Forwards: 70\r\nProxy-Require: 100rel", 1)),
        ("bad-uri-port", base.replace(b"OPTIONS sip:127.0.0.1 SIP/2.0", b"OPTIONS sip:127.0.0.1:65536 SIP/2.0", 1)),
        ("bad-uri-escape", base.replace(b"sip:127.0.0.1", b"sip:127.0.0.1%ZZ", 1)),
    ]

    try:
        wait_ready(admin_port)
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(1.5)
            for case_index, payload in enumerate(valid_cases):
                response = send(client, udp_port, payload)
                require(status(response) == 200, f"valid corpus case {case_index} returned {status(response)}")
            for name, payload in invalid_cases:
                response = send(client, udp_port, payload)
                code = status(response)
                require(400 <= code < 500, f"invalid corpus case {name} returned {code}")
        print(f"ABNF corpus: {len(valid_cases)} valid combinations and {len(invalid_cases)} invalid mutations passed")
        return 0
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"ABNF corpus: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
