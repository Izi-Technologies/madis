#!/usr/bin/env python3
"""Click-to-call via the MADIS Application Fabric (MAF).

Usage:
    python click_to_call.py --from sip:alice@example.net --to sip:bob@example.net \\
        --url https://proxy.example.net --token <maf-token>

Creates an outbound call and polls MAF events until the call is answered
or fails. Exits 0 on answer, 1 on failure, 2 on timeout.
"""

from __future__ import annotations

import argparse
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MafError  # noqa: E402

POLL_INTERVAL = 1.0
TIMEOUT = 60.0
MAX_RETRIES = 3

_shutdown = False


def _handle_sigint(_sig, _frame):
    global _shutdown
    _shutdown = True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MAF click-to-call")
    p.add_argument("--from", dest="from_uri", required=True, help="Caller SIP URI")
    p.add_argument("--to", dest="to_uri", required=True, help="Callee SIP URI")
    p.add_argument("--url", required=True, help="MAF base URL")
    p.add_argument("--token", required=True, help="MAF bearer token")
    p.add_argument("--timeout", type=float, default=TIMEOUT, help="Seconds to wait (default 60)")
    return p.parse_args()


def main() -> int:
    signal.signal(signal.SIGINT, _handle_sigint)
    args = parse_args()

    try:
        client = MadisMaf(args.url, args.token)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    # Create the call
    retries = 0
    receipt = None
    while retries < MAX_RETRIES and not _shutdown:
        try:
            receipt = client.create_call(args.from_uri, args.to_uri)
            break
        except MafError as e:
            retries += 1
            if retries >= MAX_RETRIES:
                print(f"Failed to create call after {MAX_RETRIES} attempts: {e}", file=sys.stderr)
                return 1
            time.sleep(1.0)

    if _shutdown:
        print("Interrupted.", file=sys.stderr)
        return 130

    call_id = receipt.get("command_id") or receipt.get("resource_id", "unknown")
    print(f"Call created: {call_id}")

    # Poll events for outcome
    cursor = 0
    deadline = time.monotonic() + args.timeout

    while time.monotonic() < deadline and not _shutdown:
        try:
            page = client.events(cursor=cursor)
        except MafError:
            time.sleep(POLL_INTERVAL)
            continue

        for event in page.get("events", []):
            etype = event.get("type", "")
            ecall = event.get("call_id", "")

            if ecall != call_id:
                continue

            if etype == "call.answered":
                print(f"Call answered: {event}")
                return 0

            if etype == "call.failed":
                reason = event.get("reason", "unknown")
                print(f"Call failed: {reason}", file=sys.stderr)
                return 1

        cursor = page.get("next_cursor", cursor)
        time.sleep(POLL_INTERVAL)

    if _shutdown:
        print("Interrupted.", file=sys.stderr)
        return 130

    print("Timeout waiting for call outcome.", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
