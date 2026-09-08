#!/usr/bin/env python3
"""Fail a benchmark unless SIPp completed every requested dialog successfully."""

import csv
import sys
from pathlib import Path


def check_stats(path: Path, expected: int) -> tuple[int, int]:
    if expected < 1:
        raise ValueError("expected call count must be positive")
    with path.open(newline="", encoding="utf-8") as source:
        rows = list(csv.DictReader(source, delimiter=";"))
    if not rows:
        raise ValueError("SIPp did not produce a statistics sample")
    last = rows[-1]
    successful = int(last["SuccessfulCall(C)"])
    failed = int(last["FailedCall(C)"])
    if failed != 0 or successful != expected:
        raise ValueError(
            f"completed {successful}/{expected} dialogs; {failed} failed"
        )
    return successful, failed


if __name__ == "__main__":
    try:
        successful, _ = check_stats(Path(sys.argv[1]), int(sys.argv[2]))
    except (IndexError, KeyError, OSError, TypeError, ValueError) as error:
        print(f"FAIL: invalid or unsuccessful SIPp run: {error}", file=sys.stderr)
        sys.exit(1)
    print(f"PASS: {successful} dialogs completed; 0 failed")
