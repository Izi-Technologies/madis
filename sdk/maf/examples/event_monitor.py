#!/usr/bin/env python3
"""MAF event monitor -- streams events as JSON lines.

Usage:
    python event_monitor.py --url https://proxy.example.net --token <maf-token>
    python event_monitor.py --url https://proxy.example.net --token <maf-token> \\
        --event-type call.created

Polls the MAF event stream in a loop, printing each event as a JSON line.
Reconnects on network errors. Exits cleanly on Ctrl-C.
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MafError  # noqa: E402

POLL_INTERVAL = 1.0
RECONNECT_DELAY = 5.0

_shutdown = False


def _handle_sigint(_sig, _frame):
    global _shutdown
    _shutdown = True


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MAF event monitor")
    p.add_argument("--url", required=True, help="MAF base URL")
    p.add_argument("--token", required=True, help="MAF bearer token")
    p.add_argument("--event-type", default=None, help="Filter by event type")
    p.add_argument("--cursor", type=int, default=0, help="Starting cursor (default 0)")
    return p.parse_args()


def main() -> int:
    signal.signal(signal.SIGINT, _handle_sigint)
    args = parse_args()

    try:
        client = MadisMaf(args.url, args.token)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    cursor = args.cursor
    print(f"Monitoring events from cursor={cursor}", file=sys.stderr)

    while not _shutdown:
        try:
            page = client.events(cursor=cursor, event_type=args.event_type)
        except MafError as e:
            print(f"Error polling events (status={e.status}), retrying in {RECONNECT_DELAY}s",
                  file=sys.stderr)
            time.sleep(RECONNECT_DELAY)
            continue
        except Exception as e:
            print(f"Network error: {e}, retrying in {RECONNECT_DELAY}s", file=sys.stderr)
            time.sleep(RECONNECT_DELAY)
            continue

        events = page.get("events", [])
        for event in events:
            print(json.dumps(event, separators=(",", ":"), ensure_ascii=False), flush=True)

        new_cursor = page.get("next_cursor", cursor)
        if new_cursor != cursor:
            cursor = new_cursor
        else:
            time.sleep(POLL_INTERVAL)

    print(f"\nStopped at cursor={cursor}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
