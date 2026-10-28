"""Tests for gateway state-reading: leases, station merge, blocked set."""

import json
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

import tollbooth


LEASE_SAMPLE = """\
1762300000 52:90:b3:96:8a:29 10.42.0.176 android-31f2 * 01:04:5e:2f:41:04:22
1762290000 aa:bb:cc:00:00:02 10.42.0.107 * *
"""


class TestLeaseParsing(unittest.TestCase):
    def test_records_from_file(self):
        with tempfile.NamedTemporaryFile("w", suffix=".leases", delete=False) as f:
            f.write(LEASE_SAMPLE)
            path = f.name
        try:
            recs = tollbooth.parse_leases_records([path])
        finally:
            os.unlink(path)
        by_mac = {r["mac"]: r for r in recs}
        self.assertEqual(by_mac["52:90:b3:96:8a:29"]["ip"], "10.42.0.176")
        self.assertEqual(by_mac["52:90:b3:96:8a:29"]["name"], "android-31f2")
        # '*' hostname means "device didn't tell us its name" -> empty
        self.assertEqual(by_mac["aa:bb:cc:00:00:02"]["name"], "")

    def test_missing_files_are_skipped(self):
        self.assertEqual(tollbooth.parse_leases_records(["/nope/nada.leases"]), [])


class TestClientMerge(unittest.TestCase):
    def test_phone_gets_ip_from_lease(self):
        """The real-world bug: a phone is associated (Wi-Fi level) and has
        an address from DHCP, but never appears in the neighbor table —
        because the laptop never initiates conversations with it."""
        with tempfile.NamedTemporaryFile("w", suffix=".leases", delete=False) as f:
            f.write(LEASE_SAMPLE)
            lease_path = f.name
        try:
            def fake_run(argv, dry=False, check=True, quiet=False):
                argv = list(argv)
                if argv[:4] == ["iw", "dev", "ap0", "station"]:
                    return "Station 52:90:b3:96:8a:29 (on ap0)\n"
                if argv[:3] == ["ip", "-j", "neigh"]:
                    return "[]"          # neighbor table: empty — the bug case
                return ""

            g = tollbooth.TollBooth({"router_ip": "192.168.1.1"})
            with patch.object(tollbooth, "run", side_effect=fake_run), \
                 patch.object(tollbooth, "parse_leases_records",
                              return_value=tollbooth.parse_leases_records([lease_path])):
                clients = g.devices()
        finally:
            os.unlink(lease_path)

        self.assertEqual(len(clients), 1)
        c = clients[0]
        self.assertEqual(c["mac"], "52:90:b3:96:8a:29")
        self.assertEqual(c["ip"], "10.42.0.176")      # from the lease record
        self.assertEqual(c["name"], "android-31f2")
        self.assertTrue(c["associated"])


class TestBlockedParsing(unittest.TestCase):
    def test_real_nft_json_shape(self):
        """The real `nft -j list set` shape: a metainfo header first, then
        the set, with elements as plain strings."""
        import json
        sample = json.dumps({"nftables": [
            {"metainfo": {"version": "1.1.7"}},
            {"set": {"family": "inet", "name": "blocked_v4", "table": "whoson",
                     "type": "ipv4_addr", "elem": ["10.42.0.9", "10.42.0.2"]}}]})
        g = tollbooth.TollBooth({})
        with patch.object(tollbooth, "run", return_value=sample):
            self.assertEqual(g.blocked(), ["10.42.0.2", "10.42.0.9"])  # sorted


class TestStickyCaps(unittest.TestCase):
    """A cap should ride on the hardware address (which never changes),
    and follow the device if its network address is reissued."""

    MAC = "52:90:b3:96:8a:29"

    def _gateway_with(self, leases, neigh_json="[]"):
        g = tollbooth.TollBooth({})
        issued = []

        def fake_run(argv, dry=False, check=True, quiet=False):
            argv = [str(a) for a in argv]
            if argv[:3] == ["ip", "-j", "neigh"]:
                return neigh_json
            if argv[0] == "tc":
                issued.append(" ".join(argv))
            return ""

        for p in (patch.object(tollbooth, "run", side_effect=fake_run),
                  patch.object(tollbooth, "parse_leases_records", return_value=leases)):
            p.start()
            self.addCleanup(p.stop)
        return g, issued

    def test_cap_follows_a_moved_device(self):
        # the device used to be at .107, now holds .150 (new lease)
        g, issued = self._gateway_with(
            [{"mac": self.MAC, "ip": "10.42.0.150", "name": "phone"}])
        caps = {self.MAC: [400, 80]}
        g._apply_caps(caps)
        # the address appears in the match rule; the rate in its bucket
        self.assertTrue(any("match ip dst 10.42.0.150" in c for c in issued),
                        f"cap not applied at the new address: {issued}")
        self.assertTrue(any("400kbit" in c and "classid 1:250" in c for c in issued))
        self.assertFalse(any("10.42.0.107" in c for c in issued))

    def test_old_style_ip_key_still_works(self):
        g, issued = self._gateway_with([])
        g._apply_caps({"10.42.0.7": [5000, 1000]})
        self.assertTrue(any("match ip dst 10.42.0.7" in c for c in issued))
        self.assertTrue(any("5000kbit" in c and "classid 1:107" in c for c in issued))

    def test_offline_device_is_skipped_not_crashed(self):
        g, issued = self._gateway_with([])     # nowhere to be found
        g._apply_caps({"aa:bb:cc:dd:ee:ff": [400, 80]})
        self.assertEqual([c for c in issued if "class" in c], [])

    def test_force_reinstalls_rules_that_something_else_cleared(self):
        """Cable mode deletes shared ifb0 filters; the booth must be able
        to put its own rules back even though the caps didn't change."""
        g, issued = self._gateway_with([])
        g._apply_caps({"10.42.0.7": [800, 160]})
        issued.clear()
        g._apply_caps({"10.42.0.7": [800, 160]})       # cached: no-op
        self.assertEqual(issued, [])
        g._apply_caps({"10.42.0.7": [800, 160]}, force=True)
        self.assertTrue(any("800kbit" in c for c in issued))


class TestDryRun(unittest.TestCase):
    """Dry mode must work with no admin rights at all: it only prints
    the exact commands it would run."""

    def test_start_and_stop_print_commands_without_sudo(self):
        g = tollbooth.TollBooth({"hotspot_psk": "12345678"}, dry=True)
        with patch.object(tollbooth, "sudo_available", return_value=False), \
             redirect_stdout(io.StringIO()) as out:
            text = g.start()
            g.stop()
        printed = out.getvalue()
        self.assertIn("hostapd", printed)
        self.assertIn("dnsmasq", printed)
        self.assertIn("nft add table inet whoson", printed)
        self.assertIn("tc qdisc replace dev ap0", printed)
        self.assertIn("nft delete table inet whoson", printed)
        self.assertIn("Password", text)


class TestCableMode(unittest.TestCase):
    """Cable mode: the laptop answers as a second address and meters PCs
    that point their gateway at it.  No hotspot involved."""

    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.caps = os.path.join(self.dir, "caps.json")
        self.lan_caps = os.path.join(self.dir, "lan_caps.json")
        for p in (patch.object(tollbooth, "CAPS_PATH", self.caps),
                  patch.object(tollbooth.TollBooth, "LAN_CAPS_PATH",
                               self.lan_caps),
                  patch.object(tollbooth.scanner, "autodetect_subnet",
                               return_value="192.168.1.0/24")):
            p.start()
            self.addCleanup(p.stop)
        self.issued = []

    def _fake_run(self, argv, dry=False, check=True, quiet=False):
        self.issued.append(" ".join(str(a) for a in argv))
        return ""

    def test_lan_up_creates_the_firewall_table_and_remembers_the_alias(self):
        g = tollbooth.TollBooth({"lan_alias_ip": ""})
        with patch.object(tollbooth, "run", side_effect=self._fake_run), \
             patch.object(tollbooth, "sudo_available", return_value=True), \
             patch.object(tollbooth.settings, "load", return_value={}), \
             patch.object(tollbooth.settings, "save") as save, \
             patch.object(g, "lan_alias", return_value="192.168.1.253"):
            g.lan_up("192.168.1.253")
        self.assertIn("nft add table inet whoson", self.issued)
        self.assertTrue(any("ip addr add 192.168.1.253/24" in c
                            for c in self.issued))
        self.assertEqual(g.cfg["lan_alias_ip"], "192.168.1.253")
        self.assertTrue(save.called)

    def test_lan_cap_installs_a_meter_then_uncap_removes_it(self):
        g = tollbooth.TollBooth({"lan_alias_ip": "192.168.1.253"})
        with patch.object(tollbooth, "run", side_effect=self._fake_run):
            g.lan_cap("192.168.1.50", 800, 160)
        self.assertEqual(g.lan_caps(), {"192.168.1.50": [800, 160]})
        self.assertTrue(any("800kbit" in c and "1:150" in c
                            for c in self.issued))
        self.assertTrue(any("masquerade" in c and "192.168.1.50" in c
                            for c in self.issued))
        self.issued.clear()
        with patch.object(tollbooth, "run", side_effect=self._fake_run):
            g.lan_uncap("192.168.1.50")
        self.assertEqual(g.lan_caps(), {})
        # the buckets are gone and the stale filter was cleared, so the
        # PC is not left in a "filter points at nothing" black hole
        self.assertTrue(any("tc class del" in c and "1:150" in c
                            for c in self.issued))
        self.assertTrue(any("tc filter del" in c for c in self.issued))
        self.assertFalse(any("800kbit" in c for c in self.issued))

    def test_lan_down_takes_the_alias_off_and_forgets_it(self):
        g = tollbooth.TollBooth({"lan_alias_ip": "192.168.1.253"})
        with patch.object(tollbooth, "run", side_effect=self._fake_run), \
             patch.object(tollbooth.settings, "load", return_value={}), \
             patch.object(tollbooth.settings, "save"):
            g.lan_down()
        self.assertTrue(any("ip addr del 192.168.1.253/24" in c
                            for c in self.issued))
        self.assertEqual(g.cfg["lan_alias_ip"], "")

    def test_alias_counts_as_on_only_while_it_is_really_worn(self):
        g = tollbooth.TollBooth({"lan_alias_ip": "192.168.1.253"})
        worn = '[{"ifname": "wlan0", "addr_info": [{"local": "192.168.1.253"}]}]'
        with patch.object(tollbooth, "run", return_value=worn):
            self.assertEqual(g.lan_alias(), "192.168.1.253")
        with patch.object(tollbooth, "run", return_value="[]"):
            self.assertEqual(g.lan_alias(), "")

    def test_free_alias_follows_the_laptops_own_street(self):
        """The spare address must sit next to the laptop's real address,
        even on a wide (non-/24) network."""
        g = tollbooth.TollBooth({})
        with patch.object(tollbooth, "run",
                          return_value='[{"local": "10.0.5.20"}]'), \
             patch.object(tollbooth.subprocess, "run",
                          return_value=SimpleNamespace(returncode=1)):
            self.assertEqual(g._free_alias(), "10.0.5.253")

    def test_stopping_the_booth_puts_cable_rules_back(self):
        """The booth's teardown deletes the shared firewall table.  With
        cable mode in use, its sharing rules must be restored."""
        with open(self.lan_caps, "w") as f:
            json.dump({"192.168.1.50": [800, 160]}, f)
        g = tollbooth.TollBooth({"lan_alias_ip": "192.168.1.253"})
        with patch.object(tollbooth, "run", side_effect=self._fake_run):
            g.stop()
        joined = self.issued
        deleted = joined.index("nft delete table inet whoson")
        self.assertTrue(any("nft add table inet whoson" == c
                            for c in joined[deleted + 1:]))
        self.assertTrue(any("masquerade" in c for c in joined[deleted + 1:]))


if __name__ == "__main__":
    unittest.main()

class TestRegisteredPCs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.booth = tollbooth.TollBooth({'router_ip': '192.168.1.1'})
        self.booth.LAN_CAPS_PATH = os.path.join(self.tmp.name, 'caps.json')
        self.booth._lan_ready = True
        self.client = '12' * 16

    def test_registration_prepares_nat_and_caps_follow_pc_address_changes(self):
        with patch.object(self.booth, 'lan_alias', return_value='192.168.1.253'), \
             patch.object(tollbooth.scanner, 'autodetect_subnet', return_value='192.168.1.0/24'), \
             patch.object(tollbooth, 'run', return_value='') as runner:
            self.assertEqual(self.booth.register_pc(self.client, '192.168.1.5', 'PC', 'aa:bb:cc:dd:ee:ff'),
                             '192.168.1.253')
            self.assertTrue(any('masquerade' in call.args[0] for call in runner.call_args_list))
            self.booth.lan_cap('192.168.1.5', 800, 160, client_id=self.client)
            runner.reset_mock()
            self.booth.register_pc(self.client, '192.168.1.8', 'PC', 'aa:bb:cc:dd:ee:ff')
            calls = [call.args[0] for call in runner.call_args_list]
            filters = [c for c in calls if 'u32' in c]
            self.assertTrue(any('192.168.1.8' in c for c in filters))
            self.assertFalse(any('192.168.1.5' in c for c in filters))
            self.assertEqual(self.booth.lan_caps()[f'pc-{self.client}'], [800, 160])
            self.booth.lan_uncap('192.168.1.8', client_id=self.client)
            self.assertTrue(any('masquerade' in call.args[0] for call in runner.call_args_list))

    def test_expired_client_loses_old_address_rules_but_keeps_saved_cap(self):
        with patch.object(self.booth, 'lan_alias', return_value='192.168.1.253'), \
             patch.object(tollbooth.scanner, 'autodetect_subnet', return_value='192.168.1.0/24'), \
             patch.object(tollbooth, 'run', return_value='') as runner:
            self.booth.register_pc(self.client, '192.168.1.5', 'PC', 'aa:bb:cc:dd:ee:ff')
            self.booth.lan_cap('192.168.1.5', 800, 160, client_id=self.client)
            self.booth._pcs[self.client]['seen'] -= 46
            runner.reset_mock()
            self.booth.expire_pcs()
            self.assertEqual(self.booth.registered_pcs(), [])
            self.assertIn(f'pc-{self.client}', self.booth.lan_caps())
            self.assertFalse(any('192.168.1.5' in call.args[0] for call in runner.call_args_list))

    def test_not_ready_or_off_subnet_never_registers(self):
        self.booth._lan_ready = False
        self.assertEqual(self.booth.register_pc(self.client, '192.168.1.5', 'PC', 'aa:bb:cc:dd:ee:ff'), '')
        self.booth._lan_ready = True
        with patch.object(self.booth, 'lan_alias', return_value='192.168.1.253'), \
             patch.object(tollbooth.scanner, 'autodetect_subnet', return_value='192.168.1.0/24'):
            self.assertEqual(self.booth.register_pc(self.client, '10.0.0.5', 'PC', 'aa:bb:cc:dd:ee:ff'), '')
            self.assertEqual(self.booth.register_pc(self.client, '192.168.1.1', 'PC', 'aa:bb:cc:dd:ee:ff'), '')
        self.assertEqual(self.booth.registered_pcs(), [])
