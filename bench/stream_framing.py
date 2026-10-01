#!/usr/bin/env python3
"""Compare the frozen RC array baseline with production StreamFrame on one toolchain."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import statistics
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def run(command, **kwargs):
    return subprocess.run(command, check=True, text=True, capture_output=True, **kwargs).stdout


def percentile(values, fraction):
    values = sorted(values)
    return values[round((len(values) - 1) * fraction)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--batches", type=int, default=100)
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not (1 <= args.runs <= 100 and 1 <= args.batches <= 10000 and 1 <= args.iterations <= 1000000):
        parser.error("runs 1..100, batches 1..10000, iterations 1..1000000 required")
    compiler = shutil.which(os.environ.get("MAKO_BIN", "mako"))
    runtime = Path(os.environ.get("MAKO_RUNTIME", "")).resolve()
    if not compiler or not (runtime / "mako_rt.h").is_file():
        parser.error("set MAKO_BIN and MAKO_RUNTIME to a matching compiler/runtime pair")
    run(["bash", str(ROOT / "scripts/check-makori-version.sh"), compiler])
    cc = os.environ.get("CC", "cc")
    records = []
    with tempfile.TemporaryDirectory(prefix="madis-framing-") as work:
        work = Path(work)
        # Preserve relative pulls and leave generated C outside the repository.
        (work / "bench").mkdir()
        shutil.copy(ROOT / "stream.mko", work / "stream.mko")
        source = work / "bench/stream_framing.mko"
        shutil.copy(ROOT / "bench/stream_framing.mko", source)
        run([compiler, "build", "--backend", "c", "--emit-c", "--release", "--no-incremental",
             str(source), "-o", str(work / "unused")], cwd=work)
        generated = source.with_suffix(".c")
        shutil.copy(generated, work / "stream-framing-generated.c")
        emitted = generated.read_text()
        # Check the actual definition, excluding its forward declaration.
        marker = " stream_next_msg(MakoString buf) {"
        start = emitted.index(marker)
        stop = emitted.index('\n#line 1 "<mako-codegen>"', start)
        definition = emitted[start:stop]
        if "mako_str_array" in definition:
            raise RuntimeError("StreamFrame still allocates a string-array container")
        executable = work / "framing-bench"
        counted = work / "framing-counted"
        flags = [cc, "-std=c11", "-O3", "-DNDEBUG", "-w", "-I" + str(runtime), "-I" + str(work),
                 str(ROOT / "bench/stream_framing_harness.c"), "-pthread", "-lm", "-ldl", "-lresolv"]
        run(flags + ["-o", str(executable)])
        run(flags + ["-DFRAMING_COUNT_ALLOCATIONS", "-o", str(counted)])
        allocation_samples = {}
        for scenario in range(3):
            for variant in range(2):
                allocation_samples[scenario, variant] = json.loads(run(
                    [str(counted), str(variant), str(scenario), str(args.batches), str(args.iterations)]))
        # Alternate order to reduce warmup/thermal bias; each run is a fresh process.
        for repeat in range(args.runs):
            for scenario in range(3):
                for variant in ([0, 1] if repeat % 2 == 0 else [1, 0]):
                    result = json.loads(run([str(executable), str(variant), str(scenario),
                                             str(args.batches), str(args.iterations)]))
                    result["repeat"] = repeat
                    counted_result = allocation_samples[scenario, variant]
                    if result["messages"] != counted_result["messages"]:
                        raise RuntimeError("allocation and timing workloads differ")
                    result["allocations"] = counted_result["allocations"]
                    result["requested_bytes"] = counted_result["requested_bytes"]
                    records.append(result)
    summary = []
    for scenario, name in enumerate(["complete", "fragmented", "pipeline_with_tail"]):
        for variant, label in enumerate(["array_baseline", "typed_result"]):
            rows = [r for r in records if r["scenario"] == scenario and r["variant"] == variant]
            per_batch = args.iterations * (2 if scenario == 2 else 1)
            samples = [ns / per_batch for r in rows for ns in r["batch_ns"]]
            item = dict(scenario=name, variant=label,
                        messages_per_second=statistics.median(r["messages"] * 1e9 / r["total_ns"] for r in rows),
                        batch_mean_ns_per_message_p50=percentile(samples, 0.50),
                        batch_mean_ns_per_message_p95=percentile(samples, 0.95),
                        allocations_per_message=statistics.median(r["allocations"] / r["messages"] for r in rows),
                        requested_bytes_per_message=statistics.median(r["requested_bytes"] / r["messages"] for r in rows),
                        max_rss_kib=statistics.median(r["max_rss_kib"] for r in rows))
            summary.append(item)
    hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in
              ["stream.mko", "bench/stream_framing.mko", "bench/stream_framing_harness.c", "bench/stream_framing.py"]}
    report = dict(platform=platform.platform(), compiler=run([compiler, "--version"]).strip(), source_sha256=hashes,
                  cc=run([cc, "--version"]).splitlines()[0], runs=args.runs, batches=args.batches,
                  iterations=args.iterations, summary=summary, samples=records,
                  methodology="Same release -O3 C backend; warmed fresh processes; uninstrumented timing/RSS binary and separate allocation-counting binary. Allocation wrappers count malloc/calloc/realloc calls in generated code during batches, including per-batch fixture setup, excluding allocator internals. RSS is process high-water, not live bytes. Latency percentiles describe batch means, not request tail latency. No network or end-to-end SIP claim.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for item in summary:
        print(f"{item['scenario']:20} {item['variant']:15} {item['messages_per_second']:10.0f} msg/s "
              f"{item['allocations_per_message']:7.3f} alloc/msg "
              f"{item['batch_mean_ns_per_message_p95']:9.1f} ns/msg p95 batch mean "
              f"{item['max_rss_kib']:7.0f} KiB peak RSS")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as error:
        raise SystemExit(f"command failed: {error.cmd}\n{error.stdout}\n{error.stderr}") from error
