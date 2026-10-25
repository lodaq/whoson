"""Tests for gateway state-reading: leases, station merge, blocked set."""

import os
import tempfile
import unittest
from unittest.mock import patch

from whoson import gateway


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
            recs = gateway.parse_leases_records([path])
        finally:
            os.unlink(path)
        by_mac = {r["mac"]: r for r in recs}
        self.assertEqual(by_mac["52:90:b3:96:8a:29"]["ip"], "10.42.0.176")
        self.assertEqual(by_mac["52:90:b3:96:8a:29"]["name"], "android-31f2")
        # '*' hostname means "device didn't tell us its name" -> empty
        self.assertEqual(by_mac["aa:bb:cc:00:00:02"]["name"], "")

    def test_missing_files_are_skipped(self):
        self.assertEqual(gateway.parse_leases_records(["/nope/nada.leases"]), [])


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

            g = gateway.Gateway({"router_ip": "192.168.1.1"})
            with patch.object(gateway, "run", side_effect=fake_run), \
                 patch.object(gateway, "parse_leases_records",
                              return_value=gateway.parse_leases_records([lease_path])):
                clients = g.clients()
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
        g = gateway.Gateway({})
        with patch.object(gateway, "run", return_value=sample):
            self.assertEqual(g.blocked(), ["10.42.0.2", "10.42.0.9"])  # sorted


class TestMacStickyLimits(unittest.TestCase):
    """A cap should ride on the hardware address (which never changes),
    and follow the device if its network address is reissued."""

    MAC = "52:90:b3:96:8a:29"

    def _gateway_with(self, leases, neigh_json="[]"):
        g = gateway.Gateway({})
        issued = []

        def fake_run(argv, dry=False, check=True, quiet=False):
            argv = [str(a) for a in argv]
            if argv[:3] == ["ip", "-j", "neigh"]:
                return neigh_json
            if argv[0] == "tc":
                issued.append(" ".join(argv))
            return ""

        for p in (patch.object(gateway, "run", side_effect=fake_run),
                  patch.object(gateway, "parse_leases_records", return_value=leases)):
            p.start()
            self.addCleanup(p.stop)
        return g, issued

    def test_cap_follows_a_moved_device(self):
        # the device used to be at .107, now holds .150 (new lease)
        g, issued = self._gateway_with(
            [{"mac": self.MAC, "ip": "10.42.0.150", "name": "phone"}])
        limits = {self.MAC: [400, 80]}
        g._apply_limits(limits)
        # the address appears in the match rule; the rate in its bucket
        self.assertTrue(any("match ip dst 10.42.0.150" in c for c in issued),
                        f"cap not applied at the new address: {issued}")
        self.assertTrue(any("400kbit" in c and "classid 1:250" in c for c in issued))
        self.assertFalse(any("10.42.0.107" in c for c in issued))

    def test_old_style_ip_key_still_works(self):
        g, issued = self._gateway_with([])
        g._apply_limits({"10.42.0.7": [5000, 1000]})
        self.assertTrue(any("match ip dst 10.42.0.7" in c for c in issued))
        self.assertTrue(any("5000kbit" in c and "classid 1:107" in c for c in issued))

    def test_offline_device_is_skipped_not_crashed(self):
        g, issued = self._gateway_with([])     # nowhere to be found
        g._apply_limits({"aa:bb:cc:dd:ee:ff": [400, 80]})
        self.assertEqual([c for c in issued if "class" in c], [])


if __name__ == "__main__":
    unittest.main()
