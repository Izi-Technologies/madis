#!/usr/bin/env python3
"""Check SIGPIPE handling in actual server binaries, outside Mako's test runner."""

import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def wait_http(process, request):
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"server exited with status {process.returncode}")
        try:
            with urllib.request.urlopen(request, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            pass
        time.sleep(0.05)
    raise RuntimeError("server did not return HTTP 200 within 15 seconds")


def check(binary, admin):
    port = free_port()
    token = "broken-pipe-regression-token-000000"
    environment = dict(os.environ)
    environment.update(
        SIP_BIND_IP="127.0.0.1", SIP_IPV6="0", SIP_DB_URL="", SIP_MAF_DB_URL="",
        SIP_UDP_PORT=str(free_port()), SIP_UDP_WORKERS="1", SIP_TCP_WORKERS="1",
        SIP_TLS_WORKERS="0", SIP_WSS_WORKERS="0", SIP_ADMIN_PORT=str(port),
        SIP_ADMIN_TOKEN=token, ADMIN_BIND="127.0.0.1", ADMIN_PORT=str(port),
    )
    path = "/admin/login" if admin else "/healthz"
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        headers={"Authorization": f"Bearer {token}"},
    )
    with tempfile.TemporaryFile(mode="w+") as log:
        # Python ignores SIGPIPE itself. Restore default dispositions before
        # exec so this test verifies the server's handler, not Python's.
        process = subprocess.Popen(
            [str(Path(binary).resolve())], env=environment, stdout=log,
            stderr=subprocess.STDOUT, restore_signals=True,
        )
        try:
            wait_http(process, request)
            process.send_signal(signal.SIGPIPE)
            time.sleep(0.1)
            wait_http(process, request)
            print(f"PASS: {binary} remains healthy after SIGPIPE")
        except Exception:
            log.seek(0)
            print(log.read()[-4000:], file=sys.stderr)
            raise
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()


if __name__ == "__main__":
    if not hasattr(signal, "SIGPIPE"):
        raise SystemExit("SIGPIPE regression requires a POSIX host")
    if len(sys.argv) != 3:
        raise SystemExit("usage: check-broken-pipe.py PROXY_BINARY ADMIN_BINARY")
    check(sys.argv[1], admin=False)
    check(sys.argv[2], admin=True)
