#!/usr/bin/env python3
"""Opt-in adversarial smoke matrix for a deployed MAF HTTP endpoint.

The matrix is intentionally disabled unless MAF_SECURITY_TEST_ENABLE=1. It
creates one bounded test command, exercises credential separation and
idempotency, and never sends SIP bytes directly.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request


BASE = os.environ.get("MAF_BASE_URL", "").rstrip("/")
WRITE = os.environ.get("MAF_WRITE_TOKEN", "")
READ = os.environ.get("MAF_READ_TOKEN", WRITE)
TEST_KEY = os.environ.get("MAF_TEST_IDEMPOTENCY_KEY", "maf-security-00000001")
FROM = os.environ.get("MAF_TEST_FROM", "sip:maf-security@example.invalid")
TO = os.environ.get("MAF_TEST_TO", "sip:maf-target@example.invalid")


def request(method: str, path: str, token: str, body=None, key: str | None = None):
    data = None if body is None else json.dumps(body, separators=(",", ":")).encode()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    if key is not None:
        headers["Idempotency-Key"] = key
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        raw = error.read()
        try:
            payload = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            payload = raw.decode("utf-8", errors="replace")
        return error.code, payload


def require(condition: bool, message: str):
    if not condition:
        raise AssertionError(message)


def main() -> int:
    if os.environ.get("MAF_SECURITY_TEST_ENABLE") != "1":
        print("MAF security matrix skipped; set MAF_SECURITY_TEST_ENABLE=1")
        return 0
    if not BASE or len(WRITE) < 16 or len(READ) < 16:
        print("MAF_BASE_URL, MAF_WRITE_TOKEN, and MAF_READ_TOKEN (>=16 chars) are required", file=sys.stderr)
        return 2

    create_body = {"from": FROM, "to": TO, "application_data": {"test": "security-matrix"}}
    status, receipt = request("POST", "/api/v1/maf/calls", WRITE, create_body, TEST_KEY)
    require(status == 202, f"create expected 202, got {status}: {receipt}")
    call_id = receipt.get("resource_id", "")
    require(isinstance(call_id, str) and len(call_id) >= 8, f"missing resource_id: {receipt}")

    replay_status, replay = request("POST", "/api/v1/maf/calls", WRITE, create_body, TEST_KEY)
    require(replay_status in (200, 202), f"idempotent replay failed: {replay_status} {replay}")
    changed = {"from": FROM, "to": "sip:changed@example.invalid"}
    changed_status, _ = request("POST", "/api/v1/maf/calls", WRITE, changed, TEST_KEY)
    require(changed_status == 409, f"changed idempotency body was not rejected: {changed_status}")

    read_status, _ = request("GET", f"/api/v1/maf/calls/{urllib.parse.quote(call_id, safe='')}", READ)
    require(read_status == 200, f"read token could not read call: {read_status}")
    read_write_status, _ = request("POST", "/api/v1/maf/calls", READ, create_body, "read-only-0000001")
    require(read_write_status in (401, 403), f"read token mutated a call: {read_write_status}")
    event_status, _ = request("GET", "/api/v1/maf/events?cursor=0&limit=1", READ)
    require(event_status == 200, f"read token could not read events: {event_status}")
    bad_path_status, _ = request("GET", f"/api/v1/maf/calls/{call_id}/extra", READ)
    require(bad_path_status in (401, 404), f"unsafe path was accepted: {bad_path_status}")

    # These routes are accepted as asynchronous commands but must not claim
    # successful media ownership while their worker executors are pending.
    bridge_status, _ = request("POST", f"/api/v1/maf/calls/{call_id}/bridges", WRITE, {"channel_ids": ["a", "b"]}, "bridge-security-0001")
    media_status, _ = request("POST", f"/api/v1/maf/calls/{call_id}/media", WRITE, {"operation": "play", "resource": "test"}, "media-security-0001")
    require(bridge_status == 202 and media_status == 202, "bridge/media command acceptance changed")
    print(f"MAF security matrix passed for {call_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
