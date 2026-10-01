#!/usr/bin/env python3
"""Linux loopback SIPp comparison; never starts or stops system services.

Runs one supplied candidate at a time, pinned to CPU 2; SIPp uses CPUs 3/4.
Requires unused ports 15060, 15061, 15070, 15071, 15080, 15081, 18080 and 18443.
Reports workload latency/completion, not a universal capacity ranking.
"""
import argparse
import csv
import hashlib
import json
import os
import platform
from pathlib import Path
import signal
import socket
import subprocess
import time
import uuid

HERE = Path(__file__).resolve().parent


def stats(path):
    with path.open() as f:
        rows = list(csv.DictReader(f, delimiter=";"))
    row = rows[-1]
    return {key: int(row[key]) for key in ("SuccessfulCall(C)", "FailedCall(C)",
                                         "Retransmissions(C)", "WatchdogMajor(C)")}


def sample_udp(peaks):
    """Sample only the three isolated IPv4 benchmark sockets, not host totals."""
    for line in Path("/proc/net/udp").read_text().splitlines()[1:]:
        fields = line.split()
        address, port_hex = fields[1].split(":")
        port = int(port_hex, 16)
        if address != "0100007F" or port not in (15060, 15070, 15071):
            continue
        rx_bytes = int(fields[4].split(":")[1], 16)
        drops = int(fields[-1])
        peak = peaks.setdefault(str(port), dict(sampled_max_rx_bytes=0, drops=0))
        peak["sampled_max_rx_bytes"] = max(peak["sampled_max_rx_bytes"], rx_bytes)
        peak["drops"] = max(peak["drops"], drops)


def cpu_snapshot():
    return {fields[0]: list(map(int, fields[1:9]))
            for line in Path("/proc/stat").read_text().splitlines()
            if (fields := line.split()) and fields[0] in ("cpu2", "cpu3", "cpu4")}


def cpu_usage(before, after):
    result = {}
    for name, start in before.items():
        delta = [end - initial for initial, end in zip(start, after[name])]
        total = sum(delta)
        if total:
            result[name] = dict(busy_fraction=(total - delta[3] - delta[4] - delta[7]) / total,
                                steal_fraction=delta[7] / total)
    return result


def register():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        ident = uuid.uuid4().hex
        msg = (f"REGISTER sip:mako.local SIP/2.0\r\n"
               f"Via: SIP/2.0/UDP 127.0.0.1:{port};branch=z9hG4bK{ident};rport\r\n"
               "From: <sip:bench@mako.local>;tag=registration\r\n"
               "To: <sip:bench@mako.local>\r\n"
               f"Call-ID: {ident}\r\nCSeq: 1 REGISTER\r\n"
               "Contact: <sip:bench@127.0.0.1:15070>\r\nExpires: 3600\r\n"
               "Max-Forwards: 70\r\nContent-Length: 0\r\n\r\n").encode()
        s.settimeout(0.5)
        for _ in range(20):
            s.sendto(msg, ("127.0.0.1", 15060))
            try:
                reply = s.recv(65535).decode()
            except socket.timeout:
                continue
            if reply.startswith("SIP/2.0 100"):
                continue
            if not reply.startswith("SIP/2.0 200"):
                raise RuntimeError("Registration rejected: " + reply.splitlines()[0])
            return
        raise RuntimeError("Registration timed out")


def run(args, directory):
    directory.mkdir(parents=True)
    # Check the fixed benchmark listeners before launching any candidate.
    held = []
    try:
        for kind, ports in ((socket.SOCK_DGRAM, (15060, 15070, 15071, 15080, 15081)),
                            (socket.SOCK_STREAM, (15060, 15061, 18080, 18443))):
            for port in ports:
                s = socket.socket(socket.AF_INET, kind)
                held.append(s)
                s.bind(("127.0.0.1", port))
    finally:
        for s in held:
            s.close()
    env = os.environ.copy()
    env.update(SIP_DB_URL="", SIP_BIND_IP="127.0.0.1", SIP_IPV6="0",
               SIP_UDP_PORT="15060", SIP_TCP_PORT="15060", SIP_TLS_PORT="15061",
               SIP_WSS_PORT="18443", SIP_ADMIN_PORT="18080", SIP_ADMIN_TOKEN=uuid.uuid4().hex,
               SIP_LOG_LEVEL="error",
               SIP_UDP_WORKERS="1", SIP_ALLOW_PRIVATE_TARGETS="1",
               SIP_USER_RATE_LIMIT="1000000")
    procs, logs = [], []

    def start(name, cpu, command):
        log = (directory / (name + ".log")).open("w")
        logs.append(log)
        p = subprocess.Popen(["taskset", "-c", str(cpu), *command], cwd=directory,
                             env=env, stdout=log, stderr=subprocess.STDOUT,
                             start_new_session=True)
        procs.append(p)
        return p

    try:
        if args.kind == "opensips":
            config = (HERE / "opensips.cfg.in").read_text().replace("@MODULES@", str(args.modules))
            cfg = directory / "opensips.cfg"
            cfg.write_text(config)
            command = [str(args.binary), "-F", "-m", "256", "-M", "16",
                       "-f", str(cfg), "-w", str(directory)]
        else:
            command = [str(args.binary)]
        proxy = start("proxy", 2, command)
        count = int(args.rate * args.seconds)
        common = ["-i", "127.0.0.1", "-m", str(count), "-nostdin", "-trace_stat",
                  "-fd", "1", "-trace_err", "-timeout", str(args.seconds + 15),
                  "-timeout_error", "-buff_size", "1048576", "-ci", "127.0.0.1"]
        uas = start("uas", 4, [str(args.sipp), "-sf", str(HERE / "compare_uas.xml"),
                               "-p", "15070", "-cp", "15080",
                               "-stf", str(directory / "uas.csv"), *common])
        time.sleep(0.5)
        if proxy.poll() is not None or uas.poll() is not None:
            raise RuntimeError("Candidate or callee exited during startup; inspect logs")
        register()
        cpu_before = cpu_snapshot()
        start_time = time.monotonic()
        uac = start("uac", 3, [str(args.sipp), "127.0.0.1:15060", "-sf",
                               str(HERE / "compare_uac.xml"), "-p", "15071", "-cp", "15081",
                               "-r", str(args.rate),
                               "-l", str(max(count, 100)), "-stf", str(directory / "uac.csv"),
                               "-trace_rtt", "-rtt_freq", "10000", *common])
        socket_peaks = {}
        deadline = time.monotonic() + args.seconds + 25
        while True:
            sample_udp(socket_peaks)
            try:
                uac_rc = uac.wait(timeout=0.05)
                break
            except subprocess.TimeoutExpired:
                if time.monotonic() >= deadline:
                    raise RuntimeError("Caller exceeded its shutdown deadline")
        elapsed = time.monotonic() - start_time
        cpu_after = cpu_snapshot()
        # A failed caller can exit while the callee is still awaiting missing
        # messages. Allow SIPp's own timeout to flush its final statistics.
        uas_rc = uas.wait(timeout=args.seconds + 25)
        caller, callee = stats(directory / "uac.csv"), stats(directory / "uas.csv")
        rtts = []
        for path in directory.glob("*_rtt.csv"):
            with path.open() as f:
                rtts.extend(float(r["response_time_ms"]) for r in csv.DictReader(f, delimiter=";"))
        rtts.sort()
        generator_drops = sum(socket_peaks.get(str(p), {}).get("drops", 0)
                              for p in (15070, 15071))
        valid = (uac_rc == uas_rc == 0 and proxy.poll() is None and len(rtts) == count and
                 generator_drops == 0 and len(socket_peaks) == 3 and
                 all(s["SuccessfulCall(C)"] == count and s["FailedCall(C)"] == 0
                     and s["WatchdogMajor(C)"] == 0
                     for s in (caller, callee)))
        result = dict(kind=args.kind, binary_sha256=hashlib.sha256(args.binary.read_bytes()).hexdigest(),
                      proxy_command=command,
                      system=platform.platform(), cpu_affinity=dict(proxy=2, caller=3, callee=4),
                      fixture_sha256={name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
                                      for name in ("compare_opensips.py", "compare_uac.xml",
                                                   "compare_uas.xml", "opensips.cfg.in")},
                      offered_cps=args.rate, expected_calls=count, elapsed_seconds=elapsed,
                      idle_seconds=args.idle_seconds,
                      caller_exit=uac_rc, callee_exit=uas_rc,
                      socket_samples=socket_peaks, generator_socket_drops=generator_drops,
                      sipp_requested_buffer_bytes=1048576,
                      host_cpu_during_caller=cpu_usage(cpu_before, cpu_after),
                      caller=caller, callee=callee, rtt_samples=len(rtts), valid=valid,
                      invite_rtt_ms={str(p): rtts[min(len(rtts)-1, int(p * len(rtts)))]
                                     for p in (0.5, 0.95, 0.99)} if rtts else {})
        if args.idle_seconds:
            time.sleep(args.idle_seconds)
        result["proxy_alive_after_idle"] = proxy.poll() is None
        result["valid"] = valid and result["proxy_alive_after_idle"]
        (directory / "result.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result), flush=True)
        return result["valid"]
    finally:
        for p in reversed(procs):
            try:
                os.killpg(p.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        for p in reversed(procs):
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(p.pid, signal.SIGKILL)
                p.wait()
        for log in logs:
            log.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=("madis", "opensips"), required=True)
    parser.add_argument("--binary", type=Path, required=True)
    parser.add_argument("--sipp", type=Path, required=True)
    parser.add_argument("--modules", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rate", type=int, default=50)
    parser.add_argument("--seconds", type=int, default=5)
    parser.add_argument("--idle-seconds", type=int, default=0,
                        help="Keep the proxy running after traffic for external memory sampling")
    args = parser.parse_args()
    for name in ("binary", "sipp", "modules", "output"):
        value = getattr(args, name)
        if value is not None:
            setattr(args, name, value.resolve())
    if args.rate <= 0 or args.seconds <= 0 or args.idle_seconds < 0 or (args.kind == "opensips" and args.modules is None):
        parser.error("positive rate/duration and OpenSIPS module path required")
    raise SystemExit(0 if run(args, args.output) else 1)
