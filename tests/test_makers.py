"""Tests for MAC-address handling (maker lookup, privacy detection)."""

import unittest

import makers


class TestPrivateMac(unittest.TestCase):
    def test_randomized_macs_are_detected(self):
        # phones use these "locally administered" prefixes per network
        for mac in ("02:00:00:00:00:00", "b6:9f:24:11:22:33",
                    "aa:bb:cc:dd:ee:ff", "6e:1a:2b:3c:4d:5e"):
            self.assertTrue(makers.is_private_mac(mac), mac)

    def test_real_hardware_macs_are_not(self):
        for mac in ("f0:18:98:11:22:33", "b8:27:eb:11:22:33",
                    "34:23:87:11:22:33", "00:11:22:33:44:55"):
            self.assertFalse(makers.is_private_mac(mac), mac)

    def test_private_beats_maker_lookup(self):
        # 02:xx would otherwise look like an unknown makers; say the truth
        self.assertEqual(makers.maker_of("02:1a:2b:3c:4d:5e"), "Private address")

    def test_known_makers(self):
        self.assertEqual(makers.maker_of("F0:18:98:AA:BB:CC"), "Apple")   # case-insensitive
        self.assertEqual(makers.maker_of("b8:27:eb:00:00:01"), "Raspberry Pi")
        self.assertEqual(makers.maker_of("24:6f:28:9a:bc:de"), "Espressif")

    def test_unknown_is_honest(self):
        self.assertEqual(makers.maker_of("00:00:00:00:00:00"), "unknown")
        self.assertEqual(makers.maker_of(""), "unknown")


if __name__ == "__main__":
    unittest.main()
