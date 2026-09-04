#!/usr/bin/env python3
"""Interactive Voice Response (IVR) & Auto-Attendant using MADIS Application Fabric (MAF).

Demonstrates complete programmatic call control using the MAF Python SDK:
- Intercepts incoming calls (call.created / call.ringing)
- Inspects caller ID and dialed number (DNIS)
- Answers the call with answer_sdp
- Listens for real-time DTMF keypad digits (call.dtmf)
- Executes menu options (play audio announcement, transfer to agent, route)
- Hangs up cleanly upon completion or timeout

Usage:
    python ivr_auto_attendant.py --url https://proxy.example.net/admin --token <MAF_TOKEN>
"""

from __future__ import annotations

import argparse
import json
import signal
import sys
import time
from pathlib import Path

# Add SDK to import path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf, MafError

# Minimal valid dummy audio SDP for answering calls in testing/loopback
DEFAULT_ANSWER_SDP = (
    "v=0\r\n"
    "o=madis 1000 1000 IN IP4 127.0.0.1\r\n"
    "s=MAF IVR Session\r\n"
    "c=IN IP4 127.0.0.1\r\n"
    "t=0 0\r\n"
    "m=audio 16384 RTP/AVP 0 8 101\r\n"
    "a=rtpmap:0 PCMU/8000\r\n"
    "a=rtpmap:8 PCMA/8000\r\n"
    "a=rtpmap:101 telephone-event/8000\r\n"
    "a=fmtp:101 0-16\r\n"
    "a=sendrecv\r\n"
)

AGENT_SIP_URI = "sip:sales-queue@example.net"
SUPPORT_SIP_URI = "sip:support-queue@example.net"

_shutdown = False


def _handle_sigint(_sig, _frame):
    global _shutdown
    print("\nShutting down IVR auto-attendant...", file=sys.stderr)
    _shutdown = True


class IvrApp:
    def __init__(self, client: MadisMaf, answer_sdp: str = DEFAULT_ANSWER_SDP):
        self.client = client
        self.answer_sdp = answer_sdp
        # Track in-flight calls: call_id -> dict state
        self.sessions: dict[str, dict] = {}

    def on_call_created(self, event: dict):
        call_id = event.get("call_id", "")
        payload = event.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}

        caller = payload.get("from_uri", "unknown")
        callee = payload.get("to_uri", "unknown")
        print(f"[IVR] Incoming call {call_id} from {caller} to {callee}")

        # Example screening: reject callers with specific invalid prefixes
        if "spammer" in caller.lower():
            print(f"[IVR] Screening out caller {caller} — rejecting call")
            try:
                self.client.reject_call(call_id, sip_code=603, reason="Decline")
            except MafError as e:
                print(f"[IVR] Failed to reject: {e}", file=sys.stderr)
            return

        # Store session state
        self.sessions[call_id] = {
            "caller": caller,
            "callee": callee,
            "menu_level": "main",
            "created_at": time.time(),
        }

        # Answer the incoming call with our media / IVR SDP
        print(f"[IVR] Answering call {call_id} with IVR audio engine...")
        try:
            self.client.answer_call(call_id, self.answer_sdp)
            print(f"[IVR] Call {call_id} answered successfully. Playing welcome menu.")
        except MafError as e:
            print(f"[IVR] Failed to answer call {call_id}: {e}", file=sys.stderr)

    def on_dtmf(self, event: dict):
        call_id = event.get("call_id", "")
        payload = event.get("payload", {})
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}

        digit = payload.get("digit", "")
        direction = payload.get("direction", "inbound")
        if direction != "inbound" or not digit:
            return

        session = self.sessions.get(call_id)
        if not session:
            return

        print(f"[IVR] Call {call_id}: received DTMF digit '{digit}'")

        if digit == "1":
            print(f"[IVR] Option 1 chosen: Transferring {call_id} to Sales ({AGENT_SIP_URI})")
            try:
                self.client.transfer_call(call_id, AGENT_SIP_URI)
            except MafError as e:
                print(f"[IVR] Transfer failed: {e}", file=sys.stderr)

        elif digit == "2":
            print(f"[IVR] Option 2 chosen: Transferring {call_id} to Support ({SUPPORT_SIP_URI})")
            try:
                self.client.transfer_call(call_id, SUPPORT_SIP_URI)
            except MafError as e:
                print(f"[IVR] Transfer failed: {e}", file=sys.stderr)

        elif digit == "9":
            print(f"[IVR] Option 9 chosen: Hanging up {call_id}")
            try:
                self.client.hangup_call(call_id, reason="Caller Completed IVR")
            except MafError as e:
                print(f"[IVR] Hangup failed: {e}", file=sys.stderr)
            self.sessions.pop(call_id, None)

        else:
            print(f"[IVR] Invalid option '{digit}'. Playing repeat prompt.")
            try:
                # Optionally play audio prompt via external media engine
                self.client.media(call_id, operation="play", resource="sound:invalid_option.wav")
            except MafError:
                pass

    def on_call_ended(self, event: dict):
        call_id = event.get("call_id", "")
        if call_id in self.sessions:
            print(f"[IVR] Call {call_id} ended. Cleaned up session.")
            self.sessions.pop(call_id, None)

    def process_event(self, event: dict):
        etype = event.get("type", "")
        if etype in ("call.created", "call.ringing"):
            self.on_call_created(event)
        elif etype == "call.dtmf":
            self.on_dtmf(event)
        elif etype in ("call.ended", "call.failed", "call.canceled", "call.rejected"):
            self.on_call_ended(event)

    def run(self, poll_interval: float = 0.5):
        cursor = 0
        print(f"[IVR] Listening for incoming MAF events from cursor {cursor}...")
        while not _shutdown:
            try:
                page = self.client.events(cursor=cursor)
            except MafError as e:
                print(f"[IVR] Error polling events: {e}, retrying in 2s...", file=sys.stderr)
                time.sleep(2.0)
                continue
            except Exception as e:
                print(f"[IVR] Network exception: {e}, retrying in 2s...", file=sys.stderr)
                time.sleep(2.0)
                continue

            events = page.get("events", []) if isinstance(page, dict) else []
            for event in events:
                self.process_event(event)

            new_cursor = page.get("next_cursor", cursor) if isinstance(page, dict) else cursor
            if new_cursor != cursor:
                cursor = new_cursor
            else:
                time.sleep(poll_interval)


def main() -> int:
    signal.signal(signal.SIGINT, _handle_sigint)
    signal.signal(signal.SIGTERM, _handle_sigint)

    parser = argparse.ArgumentParser(description="MAF IVR Auto-Attendant")
    parser.add_argument("--url", default="http://127.0.0.1:8080/admin", help="MAF API base URL")
    parser.add_argument("--token", required=True, help="MAF bearer token (16-512 characters)")
    parser.add_argument("--sdp-file", default=None, help="Path to custom answer SDP file")
    args = parser.parse_args()

    answer_sdp = DEFAULT_ANSWER_SDP
    if args.sdp_file:
        try:
            answer_sdp = Path(args.sdp_file).read_text(encoding="utf-8")
        except Exception as e:
            print(f"Failed to read SDP file: {e}", file=sys.stderr)
            return 1

    try:
        client = MadisMaf(args.url, args.token)
    except ValueError as e:
        print(f"Configuration error: {e}", file=sys.stderr)
        return 1

    app = IvrApp(client, answer_sdp)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
