#!/usr/bin/env python3
"""Delay the BYE response and retransmit the request over isolated UDP ports."""
import argparse
import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import time

from fault_matrix import header, response


def run(binary, output, base):
    output.mkdir(parents=True, exist_ok=False)
    caller = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    uas = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    caller.bind(("127.0.0.1", base + 2))
    uas.bind(("127.0.0.1", base + 1))
    uas.settimeout(4)
    env = dict(PATH=os.environ.get("PATH", "/usr/bin:/bin"), SIP_DB_URL="",
               SIP_BIND_IP="127.0.0.1", SIP_IPV6="0", SIP_UDP_PORT=str(base),
               SIP_TCP_PORT=str(base), SIP_TLS_PORT=str(base + 3),
               SIP_ADMIN_PORT=str(base + 4), SIP_WSS_PORT=str(base + 5),
               SIP_ADMIN_TOKEN="isolated-bye-test", SIP_UDP_WORKERS="1",
               SIP_ALLOW_PRIVATE_TARGETS="1", SIP_USER_RATE_LIMIT="1000000")
    trace = []

    def request(method, branch, seq=1, tagged=False, route=False):
        uri = f"sip:bench@127.0.0.1:{base + 1}" if tagged else "sip:bench@mako.local"
        extra = f"Route: <sip:127.0.0.1:{base};lr>\r\n" if route else ""
        return (f"{method} {uri} SIP/2.0\r\n"
                f"Via: SIP/2.0/UDP 127.0.0.1:{base+2};branch=z9hG4bK-{branch};rport\r\n"
                "From: <sip:bench@mako.local>;tag=caller\r\n"
                f"To: <sip:bench@mako.local>{';tag=uas' if tagged else ''}\r\n"
                f"Call-ID: bye-regression\r\nCSeq: {seq} {method}\r\n"
                f"Contact: <sip:bench@127.0.0.1:{base+1}>\r\n"
                f"{extra}Expires: 3600\r\nMax-Forwards: 70\r\nContent-Length: 0\r\n\r\n").encode()

    def send(packet):
        trace.append("CALLER " + packet.decode())
        caller.sendto(packet, ("127.0.0.1", base))

    def collect(seconds):
        packets = []
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            if select.select([caller], [], [], min(.05, max(0, end-time.monotonic())))[0]:
                p = caller.recv(65535)
                trace.append("PROXY " + p.decode())
                packets.append(p)
        return packets

    def receive(method):
        while True:
            p, addr = uas.recvfrom(65535)
            trace.append("UAS " + p.decode())
            if p.startswith(method + b" "): return p, addr

    def codes(packets):
        return [int(p.split()[1]) for p in packets if p.startswith(b"SIP/2.0")]

    with (output / "proxy.log").open("w") as log:
        proc = subprocess.Popen([str(binary.resolve())], env=env, cwd=output,
                                stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            registered = False
            for _ in range(20):
                send(request("REGISTER", "registration"))
                if 200 in codes(collect(.25)): registered = True; break
                if proc.poll() is not None: raise RuntimeError("proxy exited")
            assert registered, "registration failed"
            send(request("INVITE", "invite"))
            invite, addr = receive(b"INVITE")
            reply = response(invite, 200, b"OK")
            contact = f"Contact: <sip:bench@127.0.0.1:{base+1}>\r\n".encode()
            uas.sendto(reply.replace(b"Content-Length:", contact + b"Content-Length:"), addr)
            assert 200 in codes(collect(.2)), "INVITE response missing"
            send(request("ACK", "ack", tagged=True, route=True))
            receive(b"ACK")
            bye = request("BYE", "bye", seq=2, tagged=True, route=True)
            send(bye)
            forwarded, addr = receive(b"BYE")
            send(bye)
            before = codes(collect(.2))
            uas.sendto(response(forwarded, 200, b"OK"), addr)
            final = codes(collect(.2))
            send(bye)
            replay = codes(collect(.2))
            send(request("BYE", "new-bye", seq=3, tagged=True, route=True))
            new = codes(collect(.2))
            result = dict(before_final=before, final=final, replay=replay, new_transaction=new,
                          valid=not any(c >= 200 for c in before) and 200 in final
                          and replay == [200] and new == [481])
            (output / "result.json").write_text(json.dumps(result, indent=2))
            print(json.dumps(result), flush=True)
            return result["valid"]
        finally:
            (output / "wire.txt").write_text("\n".join(trace))
            if proc.poll() is None: os.killpg(proc.pid, signal.SIGTERM)
            try: proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            caller.close()
            uas.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--binary", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--base-port", type=int, default=18760)
    a = p.parse_args()
    raise SystemExit(0 if run(a.binary, a.output.resolve(), a.base_port) else 1)
