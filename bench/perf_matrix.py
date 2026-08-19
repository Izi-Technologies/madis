#!/usr/bin/env python3
"""Run a generic Madis performance matrix.

The matrix combines:
- UDP INVITE CPS/RSS/state sampling via benchmark.sh
- long-dialog UDP retention by generating an alternate INVITE scenario
- TCP/TLS/WSS stateless OPTIONS load against one proxy instance
- TCP connection retention using tcp_connection_soak.py

Results are written under --out-dir. They are local measurements, not release
capacity claims.
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, env: dict[str, str], output: Path) -> None:
    started = time.monotonic()
    with output.open("w", encoding="utf-8") as handle:
        handle.write("+ " + " ".join(cmd) + "\n")
        handle.flush()
        proc = subprocess.run(cmd, cwd=ROOT, env=env, stdout=handle, stderr=subprocess.STDOUT)
        handle.write(f"\nexit_code={proc.returncode} elapsed_s={time.monotonic() - started:.3f}\n")
    if proc.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(cmd)}; see {output}")


def write_long_scenario(out_dir: Path, hold_ms: int) -> Path:
    src = ROOT / "bench" / "invite.xml"
    dst = out_dir / f"invite_hold_{hold_ms}.xml"
    text = src.read_text(encoding="utf-8")
    text = text.replace('<pause milliseconds="1000" />', f'<pause milliseconds="{hold_ms}" />')
    dst.write_text(text, encoding="utf-8")
    return dst


def wait_ready(port: int, token: str) -> None:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/readyz",
        headers={"Authorization": f"Bearer {token}"},
    )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(request, timeout=0.5) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise RuntimeError("proxy did not become ready")


def read_status(pid: int) -> tuple[int, int, int]:
    rss = 0
    vsz = 0
    fds = 0
    try:
        for line in Path(f"/proc/{pid}/status").read_text(encoding="utf-8").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("VmSize:"):
                vsz = int(line.split()[1])
        fds = len(os.listdir(f"/proc/{pid}/fd"))
    except OSError:
        pass
    return rss, vsz, fds


def run_stream_matrix(args: argparse.Namespace, env: dict[str, str], out_dir: Path) -> None:
    admin_token = "perf-matrix-admin-token"
    ports = {
        "udp": args.base_port,
        "tls": args.base_port + 1,
        "wss": args.base_port + 2,
        "admin": args.base_port + 20,
    }
    proxy_env = env.copy()
    proxy_env.update(
        {
            "SIP_UDP_PORT": str(ports["udp"]),
            "SIP_TLS_PORT": str(ports["tls"]),
            "SIP_WSS_PORT": str(ports["wss"]),
            "SIP_ADMIN_PORT": str(ports["admin"]),
            "SIP_ADMIN_TOKEN": admin_token,
            "SIP_STATELESS_OPTIONS": "1",
            "SIP_UDP_WORKERS": str(args.udp_workers),
            "SIP_TCP_WORKERS": "1",
            "SIP_PER_IP_CONN_LIMIT": str(max(args.tcp_soak_connections, args.stream_connections, 100)),
        }
    )
    proxy_log = (out_dir / "stream_proxy.log").open("w", encoding="utf-8")
    proxy = subprocess.Popen([args.binary], cwd=ROOT, env=proxy_env, stdout=proxy_log, stderr=subprocess.STDOUT)
    metrics_path = out_dir / "stream_metrics.csv"
    try:
        wait_ready(ports["admin"], admin_token)
        with metrics_path.open("w", encoding="utf-8", newline="") as metrics:
            writer = csv.writer(metrics)
            writer.writerow(["phase", "rss_kb", "vsz_kb", "fd_count"])
            writer.writerow(["before", *read_status(proxy.pid)])
            for transport, port in (("tcp", ports["udp"]), ("tls", ports["tls"]), ("wss", ports["wss"])):
                run(
                    [
                        sys.executable,
                        "bench/transport_options_load.py",
                        "--transport",
                        transport,
                        "--port",
                        str(port),
                        "--connections",
                        str(args.stream_connections),
                        "--messages",
                        str(args.stream_messages),
                        "--verbose",
                    ],
                    env=env,
                    output=out_dir / f"{transport}_options_load.log",
                )
                writer.writerow([transport, *read_status(proxy.pid)])
            run(
                [
                    sys.executable,
                    "bench/tcp_connection_soak.py",
                    "--port",
                    str(ports["udp"]),
                    "--connections",
                    str(args.tcp_soak_connections),
                    "--duration",
                    str(args.tcp_soak_duration),
                    "--interval",
                    "5",
                ],
                env=env,
                output=out_dir / "tcp_connection_soak.log",
            )
            writer.writerow(["tcp_soak", *read_status(proxy.pid)])
    finally:
        proxy.terminate()
        try:
            proxy.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proxy.kill()
            proxy.wait(timeout=5)
        proxy_log.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", default=str(ROOT / "main"))
    parser.add_argument("--out-dir", default="")
    parser.add_argument("--base-port", type=int, default=22060)
    parser.add_argument("--udp-workers", type=int, default=2)
    parser.add_argument("--udp-rate", type=int, default=600)
    parser.add_argument("--udp-calls", type=int, default=3000)
    parser.add_argument("--udp-concurrency", type=int, default=1000)
    parser.add_argument("--observe-seconds", type=int, default=70)
    parser.add_argument("--long-hold-ms", type=int, default=30000)
    parser.add_argument("--long-calls", type=int, default=300)
    parser.add_argument("--long-rate", type=int, default=50)
    parser.add_argument("--long-concurrency", type=int, default=300)
    parser.add_argument("--stream-connections", type=int, default=100)
    parser.add_argument("--stream-messages", type=int, default=10)
    parser.add_argument("--tcp-soak-connections", type=int, default=1000)
    parser.add_argument("--tcp-soak-duration", type=int, default=30)
    args = parser.parse_args()

    out_dir = Path(args.out_dir) if args.out_dir else Path(tempfile.mkdtemp(prefix="madis-perf."))
    out_dir.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.setdefault("MAKO_RUNTIME", str(Path.home() / "mako" / "runtime"))
    env.setdefault("SIPP", shutil.which("sipp") or "/opt/homebrew/bin/sipp")

    udp_env = env.copy()
    udp_env.update(
        {
            "BENCH_BUILD": "0",
            "BENCH_PROXY_BIN": args.binary,
            "BENCH_UDP_WORKERS": str(args.udp_workers),
            "BENCH_TARGET_CPS": str(args.udp_rate),
            "BENCH_CALLS": str(args.udp_calls),
            "BENCH_CONCURRENCY": str(args.udp_concurrency),
            "BENCH_POST_RUN_SLEEP": str(args.observe_seconds),
            "BENCH_SAMPLE_STATE": "1",
            "STATS": str(out_dir / "udp_sipp_stat.csv"),
            "METRICS": str(out_dir / "udp_sipp_stat.csv.metrics"),
            "STATE_METRICS": str(out_dir / "udp_sipp_stat.csv.state"),
            "PROXY_PORT": str(args.base_port),
            "UAS_PORT": str(args.base_port + 10),
            "TLS_PORT": str(args.base_port + 1),
            "WSS_PORT": str(args.base_port + 2),
            "ADMIN_PORT": str(args.base_port + 20),
            "REGISTER_SOURCE_PORT": str(args.base_port + 30),
            "UAC_SOURCE_PORT": str(args.base_port + 31),
        }
    )
    run(["sh", "bench/benchmark.sh"], env=udp_env, output=out_dir / "udp_benchmark.log")

    long_scenario = write_long_scenario(out_dir, args.long_hold_ms)
    long_env = env.copy()
    long_env.update(
        {
            "BENCH_BUILD": "0",
            "BENCH_PROXY_BIN": args.binary,
            "BENCH_UDP_WORKERS": str(args.udp_workers),
            "BENCH_TARGET_CPS": str(args.long_rate),
            "BENCH_CALLS": str(args.long_calls),
            "BENCH_CONCURRENCY": str(args.long_concurrency),
            "BENCH_POST_RUN_SLEEP": str(max(5, args.long_hold_ms // 1000)),
            "BENCH_SAMPLE_STATE": "1",
            "BENCH_INVITE_SCENARIO": str(long_scenario),
            "STATS": str(out_dir / "long_udp_sipp_stat.csv"),
            "METRICS": str(out_dir / "long_udp_sipp_stat.csv.metrics"),
            "STATE_METRICS": str(out_dir / "long_udp_sipp_stat.csv.state"),
            "PROXY_PORT": str(args.base_port + 100),
            "UAS_PORT": str(args.base_port + 110),
            "TLS_PORT": str(args.base_port + 101),
            "WSS_PORT": str(args.base_port + 102),
            "ADMIN_PORT": str(args.base_port + 120),
            "REGISTER_SOURCE_PORT": str(args.base_port + 130),
            "UAC_SOURCE_PORT": str(args.base_port + 131),
        }
    )
    run(["sh", "bench/benchmark.sh"], env=long_env, output=out_dir / "long_udp_benchmark.log")

    run_stream_matrix(args, env, out_dir)
    print(f"perf_matrix_out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
