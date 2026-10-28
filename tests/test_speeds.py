"""Speed argument parsing — everyday units welcome."""

import unittest

from speeds import parse_speed


class TestParseSpeed(unittest.TestCase):
    def test_plain_numbers_are_megabits(self):
        self.assertEqual(parse_speed("5/1"), (5000, 1000))
        self.assertEqual(parse_speed("5"), (5000, 5000))

    def test_kilobytes_as_downloads_display_them(self):
        # 100 KB/s = 800 kbit/s (8 bits per byte) — the user's case
        self.assertEqual(parse_speed("100kb/20kb"), (800, 160))
        self.assertEqual(parse_speed("100KB/20KB"), (800, 160))

    def test_fractional_megabits(self):
        self.assertEqual(parse_speed("0.8/0.16"), (800, 160))

    def test_megabytes(self):
        self.assertEqual(parse_speed("10mb/2mb"), (80000, 16000))

    def test_kilobits(self):
        self.assertEqual(parse_speed("500k/100k"), (500, 100))

    def test_spaces_are_tolerated(self):
        self.assertEqual(parse_speed(" 5 / 1 "), (5000, 1000))

    def test_garbage_is_rejected_plainly(self):
        for bad in ("banana", "5/x", "-5/1", "0/1"):
            with self.assertRaises(ValueError):
                parse_speed(bad)


if __name__ == "__main__":
    unittest.main()
