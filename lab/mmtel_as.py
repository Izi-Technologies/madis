#!/usr/bin/env python3
"""Lab MMTel / TAS stub for Madis iFC third-party and session triggers.

This is not a production TAS. It exercises Madis iFC / 3pREG / AS fork
boundaries with deterministic call-forwarding and barring responses.

Protocol:
  - Listens for SIP UDP (REGISTER third-party + INVITE AS fork)
  - Provisioning: seed JSON with per-IMPU rules
  - Responses never require AKA secrets

Seed example:
{
  "sip:alice@example.com": {
    "barring_mo": false,
    "cfu": "sip:voicemail@example.com",
    "cfb": "",
    "privacy": false
  }
}
"""

from __future__ import annotations

import argparse
import json
import socket
import sys
from typing import Any


def load_seed(path: str) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise SystemExit("seed must be a JSON object keyed by public identity")
    return data


def sip_header(msg: str, name: str) -> str:
    low = name.lower() + ":"
    for line in msg.split("\r\n"):
        if line.lower().startswith(low):
            return line.split(":", 1)[1].strip()
    return ""


def sip_request_uri(msg: str) -> str:
    first = msg.split("\r\n", 1)[0]
    parts = first.split()
    if len(parts) >= 2:
        return parts[1]
    return ""


def sip_method(msg: str) -> str:
    first = msg.split("\r\n", 1)[0]
    return first.split(" ", 1)[0].upper() if first else ""


def build_response(req: str, code: int, reason: str, extra: str = "") -> bytes:
    via = sip_header(req, "Via")
    from_h = sip_header(req, "From")
    to_h = sip_header(req, "To")
    cid = sip_header(req, "Call-ID")
    cseq = sip_header(req, "CSeq")
    if ";tag=" not in to_h.lower() and code >= 180:
        to_h = to_h + ";tag=mmtel-lab"
    lines = [
        f"SIP/2.0 {code} {reason}",
        f"Via: {via}" if via else "Via: SIP/2.0/UDP 127.0.0.1",
        f"From: {from_h}",
        f"To: {to_h}",
        f"Call-ID: {cid}",
        f"CSeq: {cseq}",
    ]
    if extra:
        lines.append(extra.rstrip("\r\n"))
    lines.append("Content-Length: 0")
    lines.append("")
    lines.append("")
    return "\r\n".join(lines).encode("utf-8")


def identity_from_from(msg: str) -> str:
    raw = sip_header(msg, "From")
    if "<" in raw and ">" in raw:
        return raw[raw.index("<") + 1 : raw.index(">")].split(";")[0].strip()
    return raw.split(";")[0].strip()


def handle(msg: str, rules: dict[str, Any]) -> bytes | None:
    method = sip_method(msg)
    if method == "REGISTER":
        # Third-party REGISTER: always 200 for known profile AS path.
        return build_response(msg, 200, "OK", "Contact: <sip:mmtel-as@lab>;expires=3600")
    if method == "OPTIONS":
        return build_response(msg, 200, "OK", "Allow: INVITE, ACK, BYE, CANCEL, OPTIONS, REGISTER")
    if method != "INVITE":
        return build_response(msg, 405, "Method Not Allowed")

    caller = identity_from_from(msg)
    profile = rules.get(caller) or rules.get(caller.lower()) or {}
    if profile.get("barring_mo"):
        return build_response(msg, 603, "Decline")
    cfu = (profile.get("cfu") or "").strip()
    if cfu:
        # 302 redirect to CFU target — Madis AS fork may terminate here.
        return build_response(msg, 302, "Moved Temporarily", f"Contact: <{cfu}>")
    # Accept and wait for BYE (stateless lab: 180 then 200).
    return build_response(msg, 200, "OK", "Contact: <sip:mmtel-as@lab>")


def main() -> int:
    ap = argparse.ArgumentParser(description="Lab MMTel/TAS stub for Madis")
    ap.add_argument("--bind", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=5090)
    ap.add_argument("--seed-json", required=True)
    args = ap.parse_args()
    rules = load_seed(args.seed_json)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.bind, args.port))
    print(f"mmtel-as lab listening udp {args.bind}:{args.port} profiles={len(rules)}", flush=True)
    while True:
        data, addr = sock.recvfrom(65535)
        try:
            text = data.decode("utf-8", errors="replace")
            resp = handle(text, rules)
            if resp:
                sock.sendto(resp, addr)
        except Exception as exc:  # noqa: BLE001 — lab process keeps serving
            print(f"mmtel-as error from {addr}: {exc}", file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
