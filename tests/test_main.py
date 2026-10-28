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
    def registered_pcs(self):
        return []

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
        self.snap = main.Snapshotter(FakeBooth(), self.out, active_scan=True)
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
            self.snap._collect_remote()
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


class TestDiscoveryControls(unittest.TestCase):
    def round(self, snap):
        with patch.object(main.watch, "BOOTH_INTERVAL", 0):
            snap._collect_remote()
            snap._one_round()
        return snap.out.get_nowait()

    def test_scanning_is_off_by_default_even_without_router(self):
        snap = main.Snapshotter(FakeBooth(), queue.Queue())
        with patch.object(main.watch, "scan_devices") as scan:
            msg = self.round(snap)
        scan.assert_not_called()
        self.assertIn("scanning off", msg[3])

    def test_router_failure_does_not_enable_disabled_scanning(self):
        snap = main.Snapshotter(FakeBooth(), queue.Queue())
        snap.poller = FakePoller([], failing=True)
        with patch.object(main.watch, "scan_devices") as scan:
            msg = self.round(snap)
        scan.assert_not_called()
        self.assertIn("scanning off", msg[3])

    def test_disabled_polling_does_not_call_router(self):
        from unittest.mock import Mock
        snap = main.Snapshotter(FakeBooth(), queue.Queue(), router_polling=False)
        snap.poller = Mock()
        with patch.object(main.watch, "scan_devices") as scan:
            msg = self.round(snap)
        snap.poller.poll.assert_not_called()
        scan.assert_not_called()
        self.assertIn("polling off", msg[3])

    def test_disabled_polling_skips_automatic_login(self):
        app = main.App.__new__(main.App)
        app.cfg = {"router_polling": False, "router_pass": "test-password"}
        with patch.object(main.router_mod, "RouterClient") as client:
            app._restore_router()
        client.assert_not_called()

    def test_controls_save_both_options_without_changing_other_settings(self):
        from unittest.mock import Mock
        app = main.App.__new__(main.App)
        app.cfg = {"router_pass": "preserved"}
        app.active_scan_var = Mock()
        app.active_scan_var.get.return_value = False
        app.router_polling_var = Mock()
        app.router_polling_var.get.return_value = False
        app.discovery_status = Mock()
        app._log = Mock()
        with patch.object(main.settings, "load", return_value=dict(app.cfg)), \
             patch.object(main.settings, "save") as save:
            app.save_discovery_options()
        save.assert_called_once_with({"router_pass": "preserved", "active_scan": False, "router_polling": False})
        self.assertFalse(app.cfg["router_polling"])
        self.assertIn("reopen", app.discovery_status.config.call_args.kwargs["text"])

    def test_local_devices_still_appear_with_both_options_off(self):
        local = device("aa", "10.42.0.101", "booth")
        snap = main.Snapshotter(FakeBooth(), queue.Queue(), router_polling=False)
        with patch.object(main.watch, "booth_devices", return_value=[local]), \
             patch.object(main.watch, "scan_devices") as scan:
            msg = self.round(snap)
        self.assertEqual(msg[1], [local])
        scan.assert_not_called()

    def test_slow_router_does_not_block_meter_snapshots(self):
        import threading
        from unittest.mock import Mock
        entered, release = threading.Event(), threading.Event()
        snap = main.Snapshotter(FakeBooth(), queue.Queue(), usage_monitor=Mock())
        def slow_poll(now):
            entered.set()
            release.wait(2)
            return []
        snap.poller = Mock(poll=slow_poll, failures=0, status="ok")
        worker = threading.Thread(target=snap._collect_remote)
        worker.start()
        try:
            self.assertTrue(entered.wait(1))
            with patch.object(main.watch, "BOOTH_INTERVAL", 0):
                snap._one_round()
            snap.usage_monitor.update.assert_called_once()
            self.assertEqual(snap.out.get_nowait()[0], "snapshot")
            self.assertTrue(worker.is_alive())
        finally:
            release.set()
            worker.join(2)


class TestPairedPCActions(unittest.TestCase):
    def test_selected_pc_can_be_capped_without_hotspot_or_typed_address(self):
        from unittest.mock import Mock
        app = main.App.__new__(main.App)
        app.booth = Mock()
        app.booth.lan_alias.return_value = "192.168.1.253"
        app.booth.is_up.return_value = False
        pc = watch.Device("192.168.1.5", "aa:bb:cc:dd:ee:ff", source="cable",
                          client_id="12" * 16, connection="wired")
        app._last_devices = [pc]
        app._selected_key = (pc.ip, pc.mac)
        app._current_selection = lambda: app._selected_key
        app._speed_or_complain = lambda: (800, 160)
        app._run = lambda action: action()
        with patch.object(main, "guard_protected"):
            app.cap_picked()
        app.booth.lan_cap.assert_called_once_with(pc.ip, 800, 160, client_id=pc.client_id)
        app.uncap_picked()
        app.booth.lan_uncap.assert_called_once_with(pc.ip, client_id=pc.client_id)

    def test_cut_and_restore_paired_pc_without_hotspot(self):
        from unittest.mock import Mock
        app = main.App.__new__(main.App)
        app.booth = Mock()
        app.booth.lan_alias.return_value = "192.168.1.253"
        app.booth.is_up.return_value = False
        app.booth.blocked.return_value = []
        pc = watch.Device("192.168.1.20", "aa:bb:cc:dd:ee:ff", source="cable", client_id="12" * 16)
        app._last_devices = [pc]
        app._selected_key = (pc.ip, pc.mac)
        app._current_selection = lambda: app._selected_key
        app._run = lambda action: action()
        with patch.object(main, "guard_protected"):
            app.cut_picked()
            app.booth.block.assert_called_once_with(pc.ip)
            app.booth.blocked.return_value = [pc.ip]
            app.cut_picked()
            app.booth.unblock.assert_called_once_with(pc.ip)

    def test_paired_pc_row_reports_manual_block(self):
        from unittest.mock import Mock
        booth = Mock()
        booth.blocked.return_value = ["192.168.1.20"]
        booth.registered_pcs.return_value = [dict(ip="192.168.1.20", mac="aa:bb:cc:dd:ee:ff",
                                                name="PC", client_id="12" * 16, cap=None)]
        self.assertTrue(watch.cable_devices(booth)[0].blocked)


class TestSpeedPreference(unittest.TestCase):
    def test_valid_edit_is_saved_but_incomplete_edit_is_ignored(self):
        from unittest.mock import Mock
        app = main.App.__new__(main.App)
        app.cfg = {"default_speed": "50kb/10kb"}
        app.speed_box = Mock()
        app.speed_box.get.return_value = "75kb/15kb"
        with patch.object(main.settings, "remember_speed", return_value="75kb/15kb") as save:
            self.assertEqual(app._read_speed(), (600, 120))
            save.assert_called_once_with("75kb/15kb")
            self.assertEqual(app.cfg["default_speed"], "75kb/15kb")
            app.speed_box.get.return_value = "75kb/"
            app._remember_speed()
            save.assert_called_once()
            self.assertEqual(app.cfg["default_speed"], "75kb/15kb")

    def test_closing_saves_a_valid_edit_without_applying_a_cap(self):
        from unittest.mock import Mock
        app = main.App.__new__(main.App)
        app.cfg = {"default_speed": "50kb/10kb"}
        app.speed_box = Mock()
        app.speed_box.get.return_value = "60kb/12kb"
        app._companion = Mock()
        app._snap = Mock()
        app.root = Mock()
        with patch.object(main.settings, "remember_speed", return_value="60kb/12kb") as save:
            app.on_close()
            save.assert_called_once_with("60kb/12kb")
            app.root.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
