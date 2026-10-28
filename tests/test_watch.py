"""Tests for watching who is online: merging, diffing, polling."""

import unittest

import watch
from watch import Device


def dev(**kw):
    kw.setdefault("ip", "10.42.0.7")
    kw.setdefault("mac", "aa:bb:cc:00:00:01")
    return Device(**kw)


class TestDiff(unittest.TestCase):
    def test_join_and_leave(self):
        old = [dev(), dev(ip="10.42.0.8", mac="aa:bb:cc:00:00:02")]
        new = [dev(), dev(ip="10.42.0.9", mac="aa:bb:cc:00:00:03")]
        joined, left = watch.diff(old, new)
        self.assertEqual([d.ip for d in joined], ["10.42.0.9"])
        self.assertEqual([d.ip for d in left], ["10.42.0.8"])

    def test_same_device_moving_networks_counts_as_both(self):
        # a phone hopping router <-> hotspot: new identity on each side.
        # it joins the new source and leaves the old — honest, if chatty.
        old = [dev(source="router", ip="192.168.1.24", mac="02:11:22:33:44:55")]
        new = [dev(source="booth", ip="10.42.0.7", mac="02:aa:bb:cc:dd:ee")]
        joined, left = watch.diff(old, new)
        self.assertEqual(len(joined), 1)
        self.assertEqual(len(left), 1)

    def test_switching_data_source_is_not_a_join(self):
        # the router finally answered and took over from door-knocking:
        # same gadgets, same serial numbers -> no log spam
        old = [dev(source="scan", ip="192.168.1.2", mac="aa:bb:cc:00:00:02")]
        new = [dev(source="router", ip="192.168.1.2", mac="aa:bb:cc:00:00:02")]
        self.assertEqual(watch.diff(old, new), ([], []))


class TestRouterPollerBackoff(unittest.TestCase):
    def test_backoff_doubles_on_failure(self):
        class Failing:
            def devices(self):
                raise RuntimeError("router busy")
        poller = watch.RouterPoller(Failing())
        poller.last_ok = 0  # force a poll attempt
        self.assertEqual(poller.poll(1000), [])
        self.assertEqual(poller.failures, 1)
        self.assertEqual(poller.interval, watch.ROUTER_INTERVAL * 2)
        poller.last_ok = 0
        poller.poll(1000)
        self.assertEqual(poller.interval, watch.ROUTER_INTERVAL * 4)
        self.assertIn("door-knocking", poller.status)

    def test_success_resets_backoff(self):
        class Happy:
            def devices(self):
                return [{"ip": "192.168.1.5", "mac": "aa:bb:cc:dd:ee:ff", "name": "tv"}]
        poller = watch.RouterPoller(Happy())
        poller.interval = 48
        poller.last_ok = 0
        out = poller.poll(1000)
        self.assertEqual(out[0].name, "tv")
        self.assertEqual(out[0].source, "router")
        self.assertEqual(poller.interval, watch.ROUTER_INTERVAL)
        self.assertEqual(poller.status, "ok")

    def test_poll_skipped_before_interval(self):
        class TooEager:
            def __init__(self):
                self.calls = 0
            def devices(self):
                self.calls += 1
                return [{"ip": "192.168.1.5", "mac": "aa:bb:cc:dd:ee:ff",
                         "name": "tv"}]
        client = TooEager()
        poller = watch.RouterPoller(client)
        poller.poll(1000)          # first poll happens
        again = poller.poll(1000 + 1)      # one second later: skipped
        self.assertEqual(client.calls, 1)
        # ...but the last known list stays on screen instead of blinking
        self.assertEqual([d.name for d in again], ["tv"])

    def test_moody_router_keeps_last_known_list(self):
        class Flaky:
            def __init__(self):
                self.fail = False
            def devices(self):
                if self.fail:
                    raise RuntimeError("router busy")
                return [{"ip": "192.168.1.5", "mac": "aa:bb:cc:dd:ee:ff",
                         "name": "tv"}]
        client = Flaky()
        poller = watch.RouterPoller(client)
        self.assertEqual(len(poller.poll(1000)), 1)
        client.fail = True
        poller.last_ok = 0                     # force the next ask
        self.assertEqual(len(poller.poll(2000)), 1)   # cached, not dropped
        self.assertIn("unreachable", poller.status)


if __name__ == "__main__":
    unittest.main()
