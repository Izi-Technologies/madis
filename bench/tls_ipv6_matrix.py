#!/usr/bin/env python3
"""Trusted TLS/SNI and IPv6 wire-level validation.

The certificates are generated under a temporary directory.  The client
trusts only the temporary CA, verifies the selected SNI certificate, rejects a
hostname mismatch, and then exercises UDP/TCP/TLS on the IPv6 loopback.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def sip_options(transport: str, branch: str, call_id: str, host: str) -> bytes:
    via_host = f"[{host}]" if ":" in host else host
    uri_host = via_host
    return (
        f"OPTIONS sip:{uri_host} SIP/2.0\r\n"
        f"Via: SIP/2.0/{transport} {via_host}:5090;branch=z9hG4bK-{branch}\r\n"
        f"From: <sip:test@{uri_host}>;tag=matrix\r\n"
        f"To: <sip:{uri_host}>\r\n"
        f"Call-ID: {call_id}@matrix\r\n"
        "CSeq: 1 OPTIONS\r\n"
        "Max-Forwards: 70\r\n"
        "Content-Length: 0\r\n\r\n"
    ).encode()


def wait_ready(admin_port: int, admin_token: str) -> None:
    deadline = time.monotonic() + 8.0
    while time.monotonic() < deadline:
        try:
            request = urllib.request.Request(
                f"http://127.0.0.1:{admin_port}/readyz",
                headers={"Authorization": f"Bearer {admin_token}"},
            )
            with urllib.request.urlopen(request, timeout=0.5) as response:
                if response.status == 200 and json.loads(response.read()).get("ready"):
                    return
        except Exception:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def read_until(sock: socket.socket, marker: bytes) -> bytes:
    sock.settimeout(3.0)
    data = bytearray()
    while marker not in data:
        chunk = sock.recv(8192)
        if not chunk:
            break
        data.extend(chunk)
    return bytes(data)


def run(command: list[str]) -> None:
    subprocess.run(command, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def make_certificates(openssl: str, directory: Path) -> tuple[Path, Path, Path, Path, Path]:
    ca_key = directory / "ca.key"
    ca_cert = directory / "ca.crt"
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
            "/CN=mako test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:1",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ]
    )

    def issue(name: str, hostname: str) -> tuple[Path, Path]:
        key = directory / f"{name}.key"
        csr = directory / f"{name}.csr"
        cert = directory / f"{name}.crt"
        ext = directory / f"{name}.ext"
        ext.write_text(
            "basicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\n"
            "extendedKeyUsage=serverAuth\n"
            f"subjectAltName=DNS:{hostname}\n",
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
                str(key),
                "-out",
                str(csr),
                "-subj",
                f"/CN={hostname}",
            ]
        )
        run(
            [
                openssl,
                "x509",
                "-req",
                "-in",
                str(csr),
                "-CA",
                str(ca_cert),
                "-CAkey",
                str(ca_key),
                "-CAcreateserial",
                "-out",
                str(cert),
                "-days",
                "2",
                "-sha256",
                "-extfile",
                str(ext),
            ]
        )
        return cert, key

    base_cert, base_key = issue("base", "sip.test")
    alt_cert, alt_key = issue("alt", "alt.test")
    return ca_cert, base_cert, base_key, alt_cert, alt_key


def ipv6_available() -> bool:
    try:
        with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as probe:
            probe.bind(("::1", 0))
        return True
    except OSError:
        return False


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default="./main")
    parser.add_argument("--base-port", type=int, default=18760)
    args = parser.parse_args()

    openssl = shutil.which("openssl")
    require(openssl is not None, "openssl is required for trusted certificate validation")
    require(ipv6_available(), "IPv6 loopback ::1 is unavailable")

    udp_port = args.base_port
    tls_port = args.base_port + 1
    admin_port = args.base_port + 20
    admin_token = "tls-ipv6-matrix-admin-token"
    with tempfile.TemporaryDirectory(prefix="mako-tls-") as temp:
        ca_cert, base_cert, base_key, alt_cert, alt_key = make_certificates(openssl, Path(temp))
        env = os.environ.copy()
        env.update(
            {
                "SIP_UDP_PORT": str(udp_port),
                "SIP_TLS_PORT": str(tls_port),
                "SIP_WSS_PORT": str(args.base_port + 2),
                "SIP_ADMIN_PORT": str(admin_port),
                "SIP_ADMIN_TOKEN": admin_token,
                "SIP_UDP_WORKERS": "1",
                "SIP_TCP_WORKERS": "1",
                "SIP_IPV6": "1",
                "SIP_TLS_CERT": str(base_cert),
                "SIP_TLS_KEY": str(base_key),
                "SIP_TLS_SNI": f"alt.test={alt_cert}:{alt_key}",
            }
        )
        process = subprocess.Popen(
            [args.binary], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
        try:
            wait_ready(admin_port, admin_token)
            request = sip_options("UDP", "ipv6-udp", "ipv6-udp", "::1")
            with socket.socket(socket.AF_INET6, socket.SOCK_DGRAM) as udp:
                udp.settimeout(3.0)
                udp.sendto(request, ("::1", udp_port))
                response, _ = udp.recvfrom(8192)
                require(b"SIP/2.0 200" in response, "IPv6 UDP did not return 200")

            with socket.create_connection(("::1", udp_port), timeout=3) as tcp:
                tcp.sendall(sip_options("TCP", "ipv6-tcp", "ipv6-tcp", "::1"))
                require(b"SIP/2.0 200" in read_until(tcp, b"SIP/2.0 200"), "IPv6 TCP did not return 200")

            trusted = ssl.create_default_context(cafile=str(ca_cert))
            with trusted.wrap_socket(
                socket.create_connection(("::1", tls_port), timeout=3), server_hostname="alt.test"
            ) as tls:
                peer = tls.getpeercert()
                names = {value for kind, value in peer.get("subjectAltName", ()) if kind == "DNS"}
                require("alt.test" in names, "TLS SNI did not select the alt.test certificate")
                tls.sendall(sip_options("TLS", "ipv6-tls", "ipv6-tls", "::1"))
                require(b"SIP/2.0 200" in read_until(tls, b"SIP/2.0 200"), "IPv6 TLS did not return 200")

            mismatch = ssl.create_default_context(cafile=str(ca_cert))
            try:
                with mismatch.wrap_socket(
                    socket.create_connection(("127.0.0.1", tls_port), timeout=3), server_hostname="wrong.test"
                ):
                    raise RuntimeError("TLS hostname mismatch was accepted")
            except ssl.SSLCertVerificationError:
                pass

            print("TLS/IPv6 matrix: trusted SNI, hostname rejection, IPv6 UDP/TCP/TLS passed")
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
        print(f"TLS/IPv6 matrix: FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
