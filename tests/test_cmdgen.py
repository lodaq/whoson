"""Tests for the command generators — no admin rights needed.

If these pass, the exact bytes of every network change we make are
pinned down; running them is then just execution.
"""

import unittest

from whoson import cmdgen


class TestClassId(unittest.TestCase):
    def test_stable_and_unique(self):
        self.assertEqual(cmdgen.classid_for_ip("10.42.0.7"), "1:107")
        self.assertEqual(cmdgen.classid_for_ip("10.42.0.254"), "1:354")
        self.assertNotEqual(cmdgen.classid_for_ip("10.42.0.1"),
                            cmdgen.classid_for_ip("10.42.0.2"))


class TestLimitCommands(unittest.TestCase):
    def test_limit_shape(self):
        cmds = cmdgen.tc_limit_cmds("ap0", "10.42.0.7", 800, 160, "ifb0")
        # one bucket per direction + one match rule per direction
        self.assertEqual(len(cmds), 4)
        down_class, down_filter, up_class, up_filter = cmds
        # download bucket is on the hotspot interface, capped hard (rate==ceil)
        self.assertEqual(down_class[:6], ["tc", "class", "replace", "dev", "ap0", "parent"])
        self.assertEqual(down_class.count("800kbit"), 2)
        # burst scales with the cap: half a second of quota (800kbit = 100KB/s)
        self.assertIn("50kb", down_class)
        # tiny cap -> proportionally tiny burst
        self.assertIn("10kb", up_class)
        self.assertEqual(up_class.count("160kbit"), 2)
        # download matches traffic TO the phone, upload FROM it (on ifb)
        self.assertIn("dst", down_filter)
        self.assertIn("10.42.0.7", down_filter)
        self.assertIn("ifb0", up_class)
        self.assertIn("src", up_filter)
        # whole-megabit caps still come out in round numbers
        big = cmdgen.tc_limit_cmds("ap0", "10.42.0.9", 5000, 1000, "ifb0")[0]
        self.assertIn("5000kbit", big)

    def test_init_installs_both_meters(self):
        cmds = cmdgen.tc_init_cmds("ap0", "ifb0")
        roots = [c for c in cmds if c[:4] == ["tc", "qdisc", "replace", "dev"]
                 and "handle" in c]
        devs = {(c[4], c[c.index("handle") + 1]) for c in roots}
        self.assertIn(("ap0", "1:"), devs)     # download meter
        self.assertIn(("ifb0", "1:"), devs)    # upload meter
        # the ingress->ifb redirect exists (the upload trick)
        self.assertTrue(any("mirred" in c and "redirect" in c for c in cmds))
        # unlimited default bucket exists on both meters
        self.assertEqual(sum("1:10" in c for c in cmds), 2)

    def test_teardown_removes_meters(self):
        cmds = cmdgen.tc_teardown_cmds("ap0", "ifb0")
        self.assertEqual([c[2] for c in cmds], ["del", "del", "del"])


class TestNft(unittest.TestCase):
    def test_table_has_isolation_and_block_rules(self):
        cmds = cmdgen.nft_init_cmds("ap0")
        joined = [" ".join(c) for c in cmds]
        # both chains exist
        self.assertTrue(any("add" in j and "chain" in j and " input " in j for j in joined))
        self.assertTrue(any("add" in j and "chain" in j and " forward " in j for j in joined))
        # isolation: allow DHCP+DNS from the hotspot, then drop the rest to the laptop
        self.assertTrue(any("53" in j and "67" in j and "accept" in j for j in joined))
        self.assertTrue(any("ap0" in j and j.endswith(" drop") for j in joined))
        # blocking: drop both directions for members of the set
        self.assertEqual(sum("blocked_v4" in j and "drop" in j for j in joined), 2)
        # no quoted-iface leakage (quotes belong to nft syntax, exactly once)
        self.assertTrue(any('"ap0"' in j for j in joined))

    def test_block_unblock_are_element_ops_in_our_table(self):
        add = cmdgen.nft_block_cmds("10.42.0.9")[0]
        self.assertEqual(add[:6], ["nft", "add", "element", "inet", "whoson", "blocked_v4"])
        self.assertIn("10.42.0.9", add)
        dele = cmdgen.nft_unblock_cmds("10.42.0.9")[0]
        self.assertEqual(dele[1], "delete")

    def test_teardown_is_one_table_delete(self):
        self.assertEqual(cmdgen.nft_teardown_cmds(),
                         [["nft", "delete", "table", "inet", "whoson"]])


class TestHotspotSetup(unittest.TestCase):
    def test_freq_to_channel(self):
        self.assertEqual(cmdgen.freq_to_channel(2472), 13)
        self.assertEqual(cmdgen.freq_to_channel(2452), 9)
        self.assertEqual(cmdgen.freq_to_channel(2412), 1)
        self.assertEqual(cmdgen.freq_to_channel(2484), 14)
        self.assertEqual(cmdgen.freq_to_channel(5180), 36)
        with self.assertRaises(ValueError):
            cmdgen.freq_to_channel(9000)

    def test_hostapd_conf_is_wpa2_on_given_channel(self):
        text = cmdgen.hostapd_conf_text("whoson", "hunter2hunter2", 13)
        self.assertIn("ssid=whoson", text)
        self.assertIn("channel=13", text)
        self.assertIn("hw_mode=g", text)          # channel 13 is 2.4GHz
        self.assertIn("wpa_passphrase=hunter2hunter2", text)
        self.assertIn("wpa=2", text)              # WPA2
        self.assertIn("wpa_key_mgmt=WPA-PSK", text)
        self.assertIn("rsn_pairwise=CCMP", text)
        # 5GHz channel switches the band marker
        self.assertIn("hw_mode=a", cmdgen.hostapd_conf_text("x", "12345678", 36))

    def test_dnsmasq_serves_the_booth_subnet(self):
        cmds = cmdgen.dnsmasq_start_cmd("192.168.1.1")
        argv = cmds[-1]
        self.assertEqual(argv[0], "dnsmasq")
        joined = " ".join(argv)
        self.assertIn("10.42.0.100,10.42.0.200", joined)   # handout pool
        self.assertIn("option:router,10.42.0.1", joined)   # gateway = laptop
        self.assertIn("--server=192.168.1.1", joined)      # DNS via router
        self.assertIn(cmdgen.DNSMASQ_LEASES, joined)       # names we read later

    def test_nat_masquerades_booth_traffic(self):
        cmds = cmdgen.nat_cmds("ap0")
        self.assertIn("masquerade", cmds[1])
        self.assertIn(cmdgen.BOOTH_CIDR, cmds[1])
        self.assertIn('"ap0"', cmds[1])   # everything NOT leaving via hotspot


if __name__ == "__main__":
    unittest.main()
