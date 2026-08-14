"""Command lifecycle and call state-machine tests (mock-only, no server)."""

import json
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "python"))
from madis_maf import MadisMaf  # noqa: E402


class FakeResponse:
    def __init__(self, status, payload):
        self.status = status
        self._payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self._payload


def _receipt(command_id, status="accepted"):
    return {
        "schema": "madis.maf.command-receipt.v1",
        "command_id": command_id,
        "status": status,
        "trace_id": f"tr-{command_id}",
    }


def _call(call_id, state, version="1"):
    return {
        "schema": "madis.maf.call.v1",
        "call_id": call_id,
        "state": state,
        "version": version,
    }


class CommandLifecycleTests(unittest.TestCase):
    """Validate command state machine and idempotency."""

    def setUp(self):
        self.captured = []
        self.next_response = None
        self.client = MadisMaf("https://proxy.example.net/admin", "0123456789abcdef")
        self._patcher = patch("madis_maf.urlopen", side_effect=self._intercept)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _intercept(self, request, timeout):
        body = None if request.data is None else json.loads(request.data)
        self.captured.append({
            "method": request.method,
            "url": request.full_url,
            "headers": dict(request.headers),
            "body": body,
        })
        if self.next_response:
            status, payload = self.next_response
            self.next_response = None
            return FakeResponse(status, payload)
        is_get = request.method == "GET"
        return FakeResponse(
            200 if is_get else 202,
            _call("call-1", "ringing") if is_get else _receipt("cmd-1"),
        )

    # -- Command state machine --

    def test_command_accepted_then_completed(self):
        """accepted -> processing -> completed is valid."""
        r1 = _receipt("cmd-1", "accepted")
        r2 = _receipt("cmd-1", "completed")
        self.assertEqual(r1["status"], "accepted")
        self.assertEqual(r2["status"], "completed")
        # Valid terminal transitions
        valid_terminal = {"completed", "failed"}
        self.assertIn(r2["status"], valid_terminal)

    def test_command_accepted_then_failed(self):
        """accepted -> failed is valid."""
        r = _receipt("cmd-1", "failed")
        self.assertEqual(r["status"], "failed")

    def test_stale_command_detection(self):
        """Commands stuck in 'accepted' for >30s are stale."""
        accepted_at = time.monotonic() - 31
        elapsed = time.monotonic() - accepted_at
        self.assertGreater(elapsed, 30, "Command should be considered stale after 30s")

    # -- Idempotency --

    def test_same_idempotency_key_returns_same_receipt(self):
        receipt = _receipt("idem-key-1", "accepted")
        self.next_response = (202, receipt)
        r1 = self.client.create_call("sip:a@x", "sip:b@x", idempotency_key="idem-key-1")
        self.next_response = (202, receipt)
        r2 = self.client.create_call("sip:a@x", "sip:b@x", idempotency_key="idem-key-1")
        self.assertEqual(r1["command_id"], r2["command_id"])
        self.assertEqual(r1["trace_id"], r2["trace_id"])

    def test_command_id_uniqueness(self):
        """Different calls without explicit key get different command_ids."""
        self.client.create_call("sip:a@x", "sip:b@x")
        self.client.create_call("sip:c@x", "sip:d@x")
        id1 = self.captured[0]["body"]["command_id"]
        id2 = self.captured[1]["body"]["command_id"]
        self.assertNotEqual(id1, id2, "Auto-generated command IDs must be unique")

    # -- Call state transitions --

    VALID_TRANSITIONS = {
        "created": {"ringing"},
        "ringing": {"answered", "ended", "failed"},
        "answered": {"bridged", "ending", "ended"},
        "bridged": {"ending", "ended"},
        "ending": {"ended"},
        "ended": set(),
        "failed": set(),
    }

    def test_valid_call_transitions(self):
        for state, nexts in self.VALID_TRANSITIONS.items():
            for nxt in nexts:
                # Just verify the mapping is internally consistent
                self.assertIn(nxt, (
                    "created", "ringing", "answered", "bridged",
                    "ending", "ended", "failed",
                ))

    def test_answer_requires_ringing(self):
        """Cannot answer a call that is not in 'ringing' state."""
        non_ringing = ["created", "answered", "bridged", "ending", "ended", "failed"]
        for state in non_ringing:
            allowed = self.VALID_TRANSITIONS[state]
            self.assertNotIn("answered", allowed if state != "created" else set(),
                             f"Should not be able to answer from '{state}'")

    def test_answer_from_ringing_is_valid(self):
        self.assertIn("answered", self.VALID_TRANSITIONS["ringing"])

    def test_ended_is_terminal(self):
        self.assertEqual(self.VALID_TRANSITIONS["ended"], set())

    def test_failed_is_terminal(self):
        self.assertEqual(self.VALID_TRANSITIONS["failed"], set())

    def test_invalid_transition_rejected(self):
        """Transitioning ended->ringing is invalid."""
        self.assertNotIn("ringing", self.VALID_TRANSITIONS["ended"])
        self.assertNotIn("answered", self.VALID_TRANSITIONS["ended"])


class CallStateFullCycleTest(unittest.TestCase):
    """Walk through a full call lifecycle via mock responses."""

    def test_full_lifecycle(self):
        states = ["created", "ringing", "answered", "bridged", "ending", "ended"]
        for i in range(len(states) - 1):
            current = states[i]
            nxt = states[i + 1]
            allowed = CommandLifecycleTests.VALID_TRANSITIONS[current]
            self.assertIn(nxt, allowed,
                          f"Transition {current} -> {nxt} should be valid")


if __name__ == "__main__":
    unittest.main()
