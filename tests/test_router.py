"""Tests for the router conversation — against the real pages captured
from this very router (tests/fixtures/), plus the verified password
scrambling from its own login script."""

import base64
import hashlib
import os
import unittest
from unittest.mock import patch

from whoson import router

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


def fixture(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8", errors="replace") as f:
        return f.read()


class TestLoginFormula(unittest.TestCase):
    def test_matches_the_routers_own_javascript(self):
        # rebuilt here step by step, straight from user_login.js:
        #   plaintPwd = UserName + base64Encode(SHA256(Password))
        #               + csrf_param + csrf_token
        #   Password   = SHA256(plaintPwd)
        # with SHA256() -> lowercase hex (see their base64.js) and
        # base64Encode() encoding the hex *string* as ASCII.
        user, pw = "admin", "s3cret-pw"
        param, token = "P4r4m", "T0k3n"
        step1 = hashlib.sha256(pw.encode()).hexdigest()          # hex string
        step2 = base64.b64encode(step1.encode("ascii")).decode()  # b64 of the hex text
        expected = hashlib.sha256((user + step2 + param + token).encode()).hexdigest()
        self.assertEqual(
            router.login_password_hash(user, pw, param, token), expected)

    def test_password_bytes_not_b64_of_raw_digest(self):
        # the classic mistake: b64 of the 32 raw digest *bytes* instead of
        # the 64-char hex text — must NOT match what we send
        wrong = base64.b64encode(hashlib.sha256(b"s3cret-pw").digest()).decode()
        right = base64.b64encode(hashlib.sha256(b"s3cret-pw").hexdigest().encode()).decode()
        self.assertNotEqual(wrong, right)   # sanity: they differ
        out = router.login_password_hash("admin", "s3cret-pw", "p", "t")
        self.assertIn(hashlib.sha256(("admin" + right + "pt").encode()).hexdigest(), [out])


class TestCsrfParsing(unittest.TestCase):
    def test_tokens_from_the_real_login_page(self):
        html = fixture("login_page.html")
        param, token = router.parse_csrf(html)
        self.assertEqual(param, "Ze3rbL2mwzeBhvu8PWlwtQPf0sxF83G")
        self.assertEqual(token, "RjdnpQuC70EygZ3MLz2CYxGB24TahcL")

    def test_empty_on_garbage(self):
        self.assertEqual(router.parse_csrf("<html></html>"), ("", ""))


class TestUnwrap(unittest.TestCase):
    def test_strips_the_envelope(self):
        body = 'while(1); /* {"errorCategory":"ok"} */'
        self.assertEqual(router.unwrap(body), '{"errorCategory":"ok"}')

    def test_plain_json_passes_through(self):
        self.assertEqual(router.unwrap('{"a": 1}'), '{"a": 1}')


class TestDeviceNormalization(unittest.TestCase):
    def test_huawei_style_keys(self):
        rows = [{"HostName": "Sebas-Phone", "MacAddress": "AA:BB:CC:11:22:33",
                 "IpAddress": "192.168.1.24"}]
        dev = router._normalize_device(rows[0])
        self.assertEqual(dev, {"ip": "192.168.1.24",
                               "mac": "aa:bb:cc:11:22:33",
                               "name": "Sebas-Phone"})

    def test_extract_rows_finds_the_list(self):
        self.assertEqual(router._extract_rows({"hosts": [{"ip": "1.2.3.4"}]}),
                         [{"ip": "1.2.3.4"}])
        self.assertEqual(router._extract_rows([{"ip": "1.2.3.4"}]),
                         [{"ip": "1.2.3.4"}])
        self.assertEqual(router._extract_rows({"nothing": 1}), [])


class TestDiscovery(unittest.TestCase):
    def test_objnames_from_a_view_script(self):
        # shaped like the router's real page scripts
        fake_js = """
        Atp.MultiObjController.create ({
          objName: 'homenetwork/lanhosts',
          modelClass: Atp.LanHostItem
        });
        Atp.SingleObjController.create ({
          objName: 'homenetwork/landevstat'
        });
        """
        client = router.RouterClient("192.168.1.1", "u", "p")
        with patch.object(client, "_fetch_page", return_value=fake_js):
            found = client._discover_objnames("/html/landevices_view.js")
        self.assertEqual(found["homenetwork/lanhosts"], "MultiObj")
        self.assertEqual(found["homenetwork/landevstat"], "SingleObj")


class TestLoginFlow(unittest.TestCase):
    def _client(self):
        return router.RouterClient("192.168.1.1", "admin", "pw")

    def test_login_ok(self):
        c = self._client()
        responses = {
            "/": fixture("login_page.html"),
            "/api/system/user_login": '{"errorCategory":"ok","level":2,'
                                      '"csrf_param":"np","csrf_token":"nt"}',
        }
        with patch.object(c, "_fetch_page", return_value=responses["/"]), \
             patch.object(c, "_request", return_value=__import__("json").loads(
                 responses["/api/system/user_login"])):
            c.login()
        self.assertEqual((c.csrf_param, c.csrf_token), ("np", "nt"))

    def test_login_wrong_password_raises_with_plain_words(self):
        import json as _json
        c = self._client()
        refused = {"errorCategory": "wrongPassword", "count": 1}
        with patch.object(c, "_fetch_page", return_value=fixture("login_page.html")), \
             patch.object(c, "_request", return_value=refused):
            with self.assertRaises(router.RouterError) as ctx:
                c.login()
        self.assertIn("wrong username or password", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
