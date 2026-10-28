"""Tests for the window's pure helpers (no window opened, no network)."""

import unittest

import helpers


class FakeBooth:
    """Just enough of a TollBooth for guard_protected."""

    def __init__(self, devices=None):
        self._devices = devices or []
        self.cfg = {"router_ip": "192.168.1.1"}

    def devices(self):
        return self._devices

    def ap_ip(self):
        return "10.42.0.1"


class TestValidateWifi(unittest.TestCase):
    def test_keeps_a_good_name_and_password(self):
        self.assertEqual(helpers.validate_wifi("  Home  ", "hunter2hunter2"),
                         ("Home", "hunter2hunter2"))

    def test_spaces_inside_the_password_are_fine(self):
        self.assertEqual(helpers.validate_wifi("Home", "two words"),
                         ("Home", "two words"))

    def test_name_is_required(self):
        with self.assertRaises(ValueError):
            helpers.validate_wifi("   ", "hunter2hunter2")

    def test_name_fits_in_32_bytes(self):
        helpers.validate_wifi("é" * 16, "hunter2hunter2")   # 32 bytes
        with self.assertRaises(ValueError):
            helpers.validate_wifi("é" * 17, "hunter2hunter2")

    def test_password_needs_8_to_63_characters(self):
        with self.assertRaises(ValueError):
            helpers.validate_wifi("Home", "short")
        with self.assertRaises(ValueError):
            helpers.validate_wifi("Home", "x" * 64)
        self.assertEqual(helpers.validate_wifi("Home", "x" * 8)[1], "x" * 8)
        self.assertEqual(helpers.validate_wifi("Home", "x" * 63)[1], "x" * 63)

    def test_line_breaks_are_refused(self):
        with self.assertRaises(ValueError):
            helpers.validate_wifi("Home\nssid=evil", "hunter2hunter2")
        with self.assertRaises(ValueError):
            helpers.validate_wifi("Home", "hunter2\nhunter2")


class TestGuardProtected(unittest.TestCase):
    def test_refuses_the_router(self):
        with self.assertRaises(ValueError):
            helpers.guard_protected(FakeBooth([]), "192.168.1.1")

    def test_refuses_the_laptop_itself(self):
        with self.assertRaises(ValueError):
            helpers.guard_protected(FakeBooth([]), "127.0.0.1")


class TestDoctorRows(unittest.TestCase):
    def test_rows_are_name_ok_note_triples(self):
        rows = helpers.doctor_checks()
        self.assertTrue(rows)
        for name, ok, note in rows:
            self.assertIsInstance(name, str)
            self.assertIsInstance(ok, bool)
            self.assertTrue(note)


if __name__ == "__main__":
    unittest.main()
