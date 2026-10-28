import hashlib
import hmac
import base64
import gzip
import re
import unittest
import queue
import tempfile
from pathlib import Path
from unittest.mock import Mock

import companion

KEY = 'ab' * 32
NOW = 1800000000
CLIENT = '12' * 16
NONCE = '34' * 16


def request(key=KEY, timestamp=NOW, nonce=NONCE):
    body = f'discover|1|{timestamp}|{nonce}|{CLIENT}|WINDOWS-PC|aa:bb:cc:dd:ee:ff|192.168.1.5'
    signature = hmac.new(bytes.fromhex(key), body.encode('ascii'), hashlib.sha256).hexdigest()
    return f'{body}|{signature}'.encode('ascii')


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        self.booth = Mock()
        self.booth.register_pc.return_value = '192.168.1.253'
        self.protocol = companion.Discovery(KEY, self.booth)

    def test_authenticated_registration_and_signed_ready_reply(self):
        reply = self.protocol.reply(request(), '192.168.1.5', now=NOW)
        self.booth.register_pc.assert_called_once_with(CLIENT, '192.168.1.5',
                                                       'WINDOWS-PC', 'aa:bb:cc:dd:ee:ff')
        body = f'ready|1|{NONCE}|192.168.1.253'
        signature = hmac.new(bytes.fromhex(KEY), body.encode(), hashlib.sha256).hexdigest()
        self.assertEqual(reply.decode(), f'{body}|{signature}')

    def test_wrong_key_stale_replayed_or_malformed_requests_do_nothing(self):
        for raw in (request('cd' * 32), request(timestamp=NOW-61),
                    b'garbage', b'\xff', b'x' * 2049):
            self.assertIsNone(self.protocol.reply(raw, '192.168.1.5', now=NOW))
        self.booth.register_pc.assert_not_called()
        self.protocol.reply(request(), '192.168.1.5', now=NOW)
        self.assertIsNone(self.protocol.reply(request(), '192.168.1.5', now=NOW))
        self.assertEqual(self.booth.register_pc.call_count, 1)

    def test_authenticated_clock_skew_is_reported_without_registering(self):
        warning = Mock()
        protocol = companion.Discovery(KEY, self.booth, on_clock_skew=warning)
        self.assertIsNone(protocol.reply(request(timestamp=NOW-7345), '192.168.1.20', now=NOW))
        warning.assert_called_once_with('192.168.1.20', 7345)
        self.booth.register_pc.assert_not_called()
        warning.reset_mock()
        protocol.reply(request(key='cd'*32, timestamp=NOW-7345), '192.168.1.20', now=NOW)
        warning.assert_not_called()

    def test_signed_request_cannot_register_a_different_source_address(self):
        self.assertIsNone(self.protocol.reply(request(), '192.168.1.8', now=NOW))
        self.booth.register_pc.assert_not_called()

    def test_no_ready_response_when_cable_mode_is_off(self):
        self.booth.register_pc.return_value = ''
        self.assertIsNone(self.protocol.reply(request(), '192.168.1.5', now=NOW))

    def test_paste_command_contains_complete_paired_script_without_downloads(self):
        command = companion.setup_command(KEY)
        self.assertNotIn("\n", command)
        payload = re.search(r"FromBase64String\('([^']+)'\)", command).group(1)
        script = gzip.decompress(base64.b64decode(payload)).decode('utf-8-sig')
        self.assertIn(f"$BundledKey = '{KEY}'", script)
        self.assertIn("New-ScheduledTaskTrigger -AtStartup", script)
        self.assertNotIn('__WHOSON_PAIRING_KEY__', script)
        self.assertNotIn('Invoke-WebRequest', command)
        self.assertNotIn('http://', command)
        self.assertIn('-ExecutionPolicy Bypass -File $p -Action install', command)

    def test_paste_command_rejects_untrusted_pairing_input(self):
        with self.assertRaises(ValueError):
            companion.setup_command("'; injected-code")


class TestClockWarning(unittest.TestCase):
    def test_warning_is_limited_per_peer_and_does_not_change_authentication(self):
        from unittest.mock import patch
        updates = queue.Queue()
        server = companion.Server(KEY, Mock(), updates)
        with patch.object(companion.time, 'monotonic', side_effect=[100, 110, 161]):
            server._warn_clock_skew('192.168.1.20', 7345)
            server._warn_clock_skew('192.168.1.20', 7345)
            server._warn_clock_skew('192.168.1.20', -7345)
        self.assertEqual(updates.qsize(), 2)
        self.assertIn('behind', updates.get_nowait()[1])
        self.assertIn('ahead of', updates.get_nowait()[1])


class TestStandaloneInstaller(unittest.TestCase):
    def test_one_cmd_file_contains_the_paired_helper_and_fits_windows_line_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'whoson-install.cmd'
            companion.save_installer(path, KEY)
            raw = path.read_bytes()
            self.assertTrue(raw.startswith(b'@echo off\r\n'))
            command = next(line for line in raw.decode('ascii').splitlines()
                           if line.startswith('powershell.exe '))
            self.assertLessEqual(len(command), 8191)
            payload = re.search(r"FromBase64String\('([^']+)'\)", command).group(1)
            script = gzip.decompress(base64.b64decode(payload)).decode('utf-8-sig')
            self.assertIn(f"$BundledKey = '{KEY}'", script)
            self.assertIn('New-ScheduledTaskTrigger -AtStartup', script)
