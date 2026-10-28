"""Tests for the window's quiet background loop — no window needed.

The loop decides what lands in the log: real joins/leaves, but no noise
when the same gadgets are simply reported by a different source.
"""

import queue
import unittest
from unittest.mock import patch

import main
import watch


class FakeBooth:
    def devices(self):
        return []

    def caps(self):
        return {}

    def blocked(self):
        return set()

    def sync_caps(self):
        pass

    def is_up(self):
        return False

    def lan_alias(self):
        return ""


class FakePoller:
    def __init__(self, rows, failing=False):
        self.rows = rows
        self.failures = 0
        self.status = "ok"
        self.failing = failing

    def poll(self, now):
        if self.failing:
            self.failures = 1
            self.status = "router unreachable — using door-knocking instead"
        return self.rows


def device(mac, ip, source="scan"):
    return watch.Device(ip=ip, mac=mac, source=source)


class TestSnapshotterEvents(unittest.TestCase):
    def setUp(self):
        self.out = queue.Queue()
        self.snap = main.Snapshotter(FakeBooth(), self.out)
        self.scan = []
        for p in (patch.object(main.watch, "booth_devices", return_value=[]),
                  patch.object(main.watch, "scan_devices",
                               side_effect=lambda: list(self.scan)),
                  patch.object(main.watch, "BOOTH_INTERVAL", 0)):
            p.start()
            self.addCleanup(p.stop)
        self.clock = 0.0

    def _round(self):
        self.clock += 1000          # make the scan "due" every round
        with patch.object(main.time, "time", return_value=self.clock):
            self.snap._one_round()
        return self.out.get_nowait()

    def test_first_round_is_quiet(self):
        self.scan = [device("aa", "192.168.1.2")]
        msg = self._round()
        self.assertEqual(msg[0], "snapshot")
        self.assertEqual(msg[2], [])            # no "everyone joined!" spam
        self.assertEqual(len(msg[1]), 1)

    def test_new_device_is_announced_and_departures_too(self):
        self.scan = [device("aa", "192.168.1.2")]
        self._round()
        self.scan = [device("aa", "192.168.1.2"), device("bb", "192.168.1.3")]
        events = self._round()[2]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith("+ "))
        self.scan = [device("bb", "192.168.1.3")]
        events = self._round()[2]
        self.assertEqual(len(events), 1)
        self.assertTrue(events[0].startswith("- "))

    def test_router_taking_over_does_not_spam_the_log(self):
        seen = device("aa", "192.168.1.2")
        self.scan = [seen]
        self._round()
        # the background login finished: now the router reports the same
        # gadget (same serial number) — nothing joined or left
        self.snap.poller = FakePoller([device("aa", "192.168.1.2",
                                              source="router")])
        msg = self._round()
        self.assertEqual(msg[2], [])
        self.assertEqual(msg[1][0].source, "router")   # row updated anyway

    def test_fallback_to_door_knocking_is_also_quiet(self):
        rows = [device("aa", "192.168.1.2", source="router")]
        self.snap.poller = FakePoller(rows)
        self.scan = [device("aa", "192.168.1.2")]
        self._round()
        self.snap.poller.failing = True          # router went quiet
        self.scan = [device("aa", "192.168.1.2")]
        msg = self._round()
        self.assertEqual(msg[2], [])             # not "everything left"
        self.assertIn("door-knocking", msg[3])   # the status line tells it


if __name__ == "__main__":
    unittest.main()
