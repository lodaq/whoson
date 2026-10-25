"""Tests for the live view: merging, diffing, polling behavior."""

import unittest

from whoson import live
from whoson.live import Device


def dev(**kw):
    kw.setdefault("ip", "10.42.0.7")
    kw.setdefault("mac", "aa:bb:cc:00:00:01")
    return Device(**kw)


class TestDiff(unittest.TestCase):
    def test_join_and_leave(self):
        old = [dev(), dev(ip="10.42.0.8", mac="aa:bb:cc:00:00:02")]
        new = [dev(), dev(ip="10.42.0.9", mac="aa:bb:cc:00:00:03")]
        joined, left = live.diff(old, new)
        self.assertEqual([d.ip for d in joined], ["10.42.0.9"])
        self.assertEqual([d.ip for d in left], ["10.42.0.8"])

    def test_same_device_moving_networks_counts_as_both(self):
        # a phone hopping router <-> hotspot: new identity on each side.
        # it joins the new source and leaves the old — honest, if chatty.
        old = [dev(source="router", ip="192.168.1.24", mac="02:11:22:33:44:55")]
        new = [dev(source="booth", ip="10.42.0.7", mac="02:aa:bb:cc:dd:ee")]
        joined, left = live.diff(old, new)
        self.assertEqual(len(joined), 1)
        self.assertEqual(len(left), 1)


class TestRouterPollerBackoff(unittest.TestCase):
    def test_backoff_doubles_on_failure(self):
        class Failing:
            def devices(self):
                raise RuntimeError("router busy")
        poller = live.RouterPoller(Failing())
        poller.last_ok = 0  # force a poll attempt
        self.assertEqual(poller.poll(1000), [])
        self.assertEqual(poller.failures, 1)
        self.assertEqual(poller.interval, live.ROUTER_INTERVAL * 2)
        poller.last_ok = 0
        poller.poll(1000)
        self.assertEqual(poller.interval, live.ROUTER_INTERVAL * 4)
        self.assertIn("door-knocking", poller.status)

    def test_success_resets_backoff(self):
        class Happy:
            def devices(self):
                return [{"ip": "192.168.1.5", "mac": "aa:bb:cc:dd:ee:ff", "name": "tv"}]
        poller = live.RouterPoller(Happy())
        poller.interval = 48
        poller.last_ok = 0
        out = poller.poll(1000)
        self.assertEqual(out[0].name, "tv")
        self.assertEqual(out[0].source, "router")
        self.assertEqual(poller.interval, live.ROUTER_INTERVAL)
        self.assertEqual(poller.status, "ok")

    def test_poll_skipped_before_interval(self):
        class TooEager:
            def __init__(self):
                self.calls = 0
            def devices(self):
                self.calls += 1
                return []
        client = TooEager()
        poller = live.RouterPoller(client)
        poller.poll(1000)          # first poll happens
        poller.poll(1000 + 1)      # one second later: skipped
        self.assertEqual(client.calls, 1)


class TestRender(unittest.TestCase):
    def test_table_shows_flags_and_counts(self):
        devices = [
            dev(name="sebas-phone", source="booth", blocked=True, limit=(5000, 1000)),
            dev(name="tv", ip="192.168.1.30", mac="60:6b:bd:11:22:33", source="router"),
        ]
        text = live.render(devices)
        self.assertIn("sebas-phone", text)
        self.assertIn("10.42.0.7", text)
        self.assertIn("⛔", text)
        self.assertIn("5M↓/1M↑", text)
        self.assertIn("tv", text)
        self.assertIn("2 device(s)", text)


if __name__ == "__main__":
    unittest.main()
