"""Tests for the door-knocking scanner's parsing (no network needed)."""

import unittest

from whoson import scanner


ROUTE_SAMPLE = """\
default via 192.168.1.1 dev wlp111s0 proto dhcp src 192.168.1.11 metric 20600
192.168.1.0/24 dev wlp111s0 proto kernel scope link src 192.168.1.11 metric 600
"""

ADDR_SAMPLE = """\
[{"ifindex": 3, "ifname": "wlp111s0", "flags": ["BROADCAST","MULTICAST","UP"],
  "addr_info": [{"family": "inet", "local": "192.168.1.11", "prefixlen": 24}]}]
"""

NEIGH_SAMPLE = """\
[{"dst": "192.168.1.1", "lladdr": "c8:0e:14:aa:bb:cc", "dev": "wlp111s0", "state": ["REACHABLE"]},
 {"dst": "192.168.1.24", "lladdr": "02:1a:2b:3c:4d:5e", "dev": "wlp111s0", "state": ["STALE"]},
 {"dst": "192.168.1.31", "lladdr": "5c:cf:7f:aa:bb:cc", "dev": "wlp111s0", "state": ["PROBE","DELAY"]},
 {"dst": "192.168.1.99", "lladdr": "aa:bb:cc:dd:ee:ff", "dev": "wlp111s0", "state": ["FAILED"]},
 {"dst": "192.168.1.77", "lladdr": "11:22:33:44:55:66", "dev": "wlp111s0", "state": ["INCOMPLETE"]},
 {"dst": "10.5.5.5", "lladdr": "99:88:77:66:55:44", "dev": "other0", "state": ["REACHABLE"]}]
"""


class TestParsers(unittest.TestCase):
    def test_default_gateway_iface(self):
        self.assertEqual(scanner.default_gateway_iface(ROUTE_SAMPLE), "wlp111s0")
        self.assertEqual(scanner.default_gateway_iface("no route"), "")

    def test_iface_subnet(self):
        self.assertEqual(scanner.iface_subnet(ADDR_SAMPLE, "wlp111s0"),
                         "192.168.1.0/24")
        self.assertEqual(scanner.iface_subnet(ADDR_SAMPLE, "eth0"), "")

    def test_neigh_keeps_live_drops_dead(self):
        found = scanner.parse_neigh_json(NEIGH_SAMPLE, "192.168.1.0/24")
        ips = [ip for ip, _ in found]
        self.assertIn("192.168.1.1", ips)    # REACHABLE
        self.assertIn("192.168.1.24", ips)   # STALE still means "lives here"
        self.assertNotIn("192.168.1.99", ips)   # FAILED = nobody home
        self.assertNotIn("192.168.1.77", ips)   # INCOMPLETE = nobody home
        self.assertNotIn("10.5.5.5", ips)    # other subnet, other card

    def test_neigh_macs_are_lowercased(self):
        found = dict(scanner.parse_neigh_json(NEIGH_SAMPLE, "192.168.1.0/24"))
        self.assertEqual(found["192.168.1.1"], "c8:0e:14:aa:bb:cc")


if __name__ == "__main__":
    unittest.main()
