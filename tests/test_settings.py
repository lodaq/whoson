"""Tests for the tiny settings file — especially the saved password."""

import os
import stat
import tempfile
import unittest
from unittest.mock import patch

import settings


class TestSettingsFile(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "config.json")
        for p in (patch.object(settings, "CONFIG_DIR", self.tmp.name),
                  patch.object(settings, "CONFIG_PATH", self.path)):
            p.start()
            self.addCleanup(p.stop)

    def test_router_password_round_trips(self):
        cfg = settings.load()
        cfg["router_user"] = "admin"
        cfg["router_pass"] = "s3cret-pw"
        settings.save(cfg)
        loaded = settings.load()
        self.assertEqual(loaded["router_user"], "admin")
        self.assertEqual(loaded["router_pass"], "s3cret-pw")

    def test_settings_file_is_owner_only(self):
        settings.save(settings.load())
        mode = stat.S_IMODE(os.stat(self.path).st_mode)
        self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
