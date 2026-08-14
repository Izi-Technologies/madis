"""Reconnection and cursor recovery tests (mock-only, no server)."""

import json
import sys
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


def _event(seq, event_type="call.state_changed"):
    return {
        "schema": "madis.maf.event.v1",
        "event_id": f"evt-{seq:04d}",
        "event_type": event_type,
        "event_version": 1,
        "sequence": seq,
        "occurred_at": "2026-01-01T00:00:00Z",
        "payload": {"seq": seq},
    }


def _page(events, next_cursor, truncated=False, heartbeat=False):
    page = {
        "schema": "madis.maf.event-page.v1",
        "events": events,
        "next_cursor": str(next_cursor),
        "truncated": truncated,
    }
    if heartbeat:
        page["heartbeat"] = True
    return page


class CursorRecoveryTests(unittest.TestCase):

    def setUp(self):
        self.response_queue = []
        self.captured = []
        self.client = MadisMaf("https://proxy.example.net/admin", "0123456789abcdef")
        self._patcher = patch("madis_maf.urlopen", side_effect=self._intercept)
        self._patcher.start()

    def tearDown(self):
        self._patcher.stop()

    def _intercept(self, request, timeout):
        self.captured.append(request.full_url)
        if self.response_queue:
            payload = self.response_queue.pop(0)
        else:
            payload = _page([], "0")
        return FakeResponse(200, payload)

    # -- Event ordering --

    def test_events_ordered_by_sequence(self):
        events = [_event(1), _event(2), _event(3)]
        self.response_queue.append(_page(events, 3))
        result = self.client.events(cursor=0)
        seqs = [e["sequence"] for e in result["events"]]
        self.assertEqual(seqs, sorted(seqs), "Events must be ordered by sequence")

    # -- Cursor recovery after disconnect --

    def test_cursor_recovery_resumes_from_last(self):
        """After disconnect, client resumes from the last cursor it received."""
        # First page: events 1-3, cursor advances to 3
        self.response_queue.append(_page([_event(1), _event(2), _event(3)], 3))
        page1 = self.client.events(cursor=0)
        last_cursor = int(page1["next_cursor"])
        self.assertEqual(last_cursor, 3)

        # Simulate reconnect: resume from cursor=3
        self.response_queue.append(_page([_event(4), _event(5)], 5))
        page2 = self.client.events(cursor=last_cursor)
        seqs = [e["sequence"] for e in page2["events"]]
        self.assertTrue(all(s > last_cursor for s in seqs),
                        "Resumed events must all be after last cursor")

    # -- No duplicate delivery --

    def test_no_duplicate_events_after_cursor(self):
        """Events with sequence <= last_seen cursor must not appear."""
        last_seen = 5
        new_events = [_event(6), _event(7)]
        self.response_queue.append(_page(new_events, 7))
        result = self.client.events(cursor=last_seen)
        for ev in result["events"]:
            self.assertGreater(ev["sequence"], last_seen,
                               f"Event seq {ev['sequence']} is a duplicate (cursor was {last_seen})")

    # -- Empty page, same cursor = no new events --

    def test_empty_page_same_cursor_means_caught_up(self):
        cursor = 10
        self.response_queue.append(_page([], cursor))
        result = self.client.events(cursor=cursor)
        self.assertEqual(result["events"], [])
        self.assertEqual(int(result["next_cursor"]), cursor)

    # -- Truncated flag --

    def test_truncated_means_more_available(self):
        self.response_queue.append(
            _page([_event(1), _event(2)], 2, truncated=True)
        )
        result = self.client.events(cursor=0)
        self.assertTrue(result["truncated"],
                        "truncated=true means client should fetch next page")

    def test_not_truncated_means_caught_up(self):
        self.response_queue.append(
            _page([_event(1)], 1, truncated=False)
        )
        result = self.client.events(cursor=0)
        self.assertFalse(result["truncated"])

    # -- Heartbeat pages --

    def test_heartbeat_page_has_empty_events(self):
        self.response_queue.append(_page([], 5, heartbeat=True))
        result = self.client.events(cursor=5)
        self.assertEqual(result["events"], [])
        self.assertTrue(result.get("heartbeat", False),
                        "Heartbeat pages should have heartbeat=true")

    # -- Full drain loop simulation --

    def test_drain_loop_until_not_truncated(self):
        """Simulate a client draining all pages after reconnect."""
        self.response_queue.extend([
            _page([_event(1), _event(2)], 2, truncated=True),
            _page([_event(3), _event(4)], 4, truncated=True),
            _page([_event(5)], 5, truncated=False),
        ])
        all_events = []
        cursor = 0
        for _ in range(10):  # safety bound
            page = self.client.events(cursor=cursor)
            all_events.extend(page["events"])
            cursor = int(page["next_cursor"])
            if not page["truncated"]:
                break
        seqs = [e["sequence"] for e in all_events]
        self.assertEqual(seqs, [1, 2, 3, 4, 5])
        self.assertEqual(cursor, 5)


if __name__ == "__main__":
    unittest.main()
