import tempfile
import unittest
from pathlib import Path

import usage
from watch import Device


class FakeKernel:
    def __init__(self):
        self.counters = {}
        self.installed = []

    def read(self):
        return dict(self.counters)

    def install(self, devices, records, counters, reset=False):
        self.installed.append((devices, records, reset))
        if reset:
            self.counters.clear()
        for key, row in records.items():
            self.counters.setdefault(usage.counter_name(key, 'down'), row['down'])
            self.counters.setdefault(usage.counter_name(key, 'up'), row['up'])


class TestUsage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'usage.json'
        self.kernel = FakeKernel()
        self.monitor = usage.Monitor(self.path, self.kernel)
        self.device = Device('10.42.0.7', 'aa:bb:cc:dd:ee:ff', source='booth')
        self.key = usage.device_key(self.device)

    def sample(self, day='2026-10-28', now=0):
        self.monitor.update([self.device], day=day, now=now)

    def traffic(self, down, up):
        self.kernel.counters[usage.counter_name(self.key, 'down')] = down
        self.kernel.counters[usage.counter_name(self.key, 'up')] = up

    def test_rates_totals_and_persistence_without_double_counting(self):
        self.sample()
        self.traffic(1000, 200)
        self.sample(now=2)
        self.assertEqual(self.device.download_now, 500)
        self.assertEqual(self.device.upload_now, 100)
        self.assertEqual(self.device.used_down, 1000)
        reopened = usage.Monitor(self.path, self.kernel)
        reopened.update([self.device], day='2026-10-28', now=3)
        self.assertEqual(self.device.used_down, 1000)

    def test_quota_is_optional_combined_and_resets_next_day(self):
        self.sample()
        self.monitor.set_limit(self.key, 2_000_000_000)
        self.traffic(1_900_000_000, 100_000_000)
        self.sample(now=2)
        self.assertTrue(self.device.quota_exhausted)
        self.assertEqual(self.device.daily_limit, 2_000_000_000)
        self.sample(day='2026-10-29', now=4)
        self.assertFalse(self.device.quota_exhausted)
        self.assertEqual(self.device.used_down, 0)
        self.assertEqual(self.device.daily_limit, 2_000_000_000)

    def test_address_change_keeps_budget_and_removing_limit_keeps_usage(self):
        self.sample()
        self.monitor.set_limit(self.key, 2_000_000_000)
        self.traffic(600, 200)
        self.sample(now=2)
        self.device.ip = '10.42.0.8'
        self.sample(now=4)
        self.assertEqual(self.device.used_down, 600)
        self.monitor.set_limit(self.key, None)
        self.sample(now=6)
        self.assertIsNone(self.device.daily_limit)
        self.assertEqual(self.device.used_down, 600)

    def test_scan_devices_are_never_presented_as_measured(self):
        scan = Device('192.168.1.5', 'aa:bb:cc:11:22:33')
        self.monitor.update([scan], day='2026-10-28', now=0)
        self.assertIsNone(scan.used_down)

    def test_failed_midnight_install_is_retried_without_restoring_yesterdays_usage(self):
        from unittest.mock import patch
        self.sample()
        self.monitor.set_limit(self.key, 2_000_000_000)
        self.traffic(1000, 500)
        self.sample(now=2)
        with patch.object(self.kernel, 'install', side_effect=RuntimeError('no admin rights')):
            with self.assertRaises(RuntimeError):
                self.sample(day='2026-10-29', now=4)
        self.sample(day='2026-10-29', now=6)
        self.assertEqual(self.device.used_down, 0)
        self.assertEqual(self.device.used_up, 0)

    def test_parse_gigabytes(self):
        self.assertEqual(usage.parse_gb('2'), 2_000_000_000)
        self.assertEqual(usage.parse_gb('0.5'), 500_000_000)
        for value in ('0', '-1', 'NaN', 'Infinity', 'bad'):
            with self.assertRaises(ValueError):
                usage.parse_gb(value)


class TestRegisteredPCUsage(unittest.TestCase):
    setUp = TestUsage.setUp
    sample = TestUsage.sample
    traffic = TestUsage.traffic
    def test_pc_identity_and_quota_survive_both_mac_and_ip_changes(self):
        self.device.source = 'cable'
        self.device.client_id = '12' * 16
        self.key = usage.device_key(self.device)
        self.sample()
        self.monitor.set_limit(self.key, 2_000_000_000)
        self.traffic(1000, 500)
        self.sample(now=2)
        self.device.ip = '192.168.1.99'
        self.device.mac = 'aa:bb:cc:00:00:99'
        reopened = usage.Monitor(self.path, self.kernel)
        reopened.update([self.device], day='2026-10-28', now=4)
        self.assertEqual(self.device.used_down, 1000)
        self.assertEqual(self.device.daily_limit, 2_000_000_000)
