"""Talking to the Huawei HG630 V2 router (WE firmware) — politely.

The router knows every device connected to it (its admin web page shows
the list when you log in with a browser).  This module logs in exactly
the way the router's own page does — same request format, same
password scrambling — then reads the device list.

Everything below was verified against this router's actual code
(`user_login.js`, `exember.js`), captured from the router itself.

Two quirks of this router worth knowing:

* Old encryption: its web page uses an outdated secure mode ("legacy
  renegotiation").  We allow it explicitly — for this one address,
  which is your own router on your own network.
* Anti-forgery tokens: every request must carry two one-time tokens
  ("csrf").  We fetch fresh ones with each page load, as the router
  expects.
"""

import base64
import hashlib
import json
import re
import ssl
import time
import urllib.error
import urllib.request
from http.cookiejar import CookieJar

BASE_PATH = "/api/"

# The router wraps JSON in this envelope to stop hostile web pages from
# reading it across sites; we simply unwrap it.
_WRAPPER = ("while(1); /*", "*/")


def login_password_hash(username: str, password: str,
                        csrf_param: str, csrf_token: str) -> str:
    """Scramble the password exactly like the router's own login page.

    (Verified against the router's user_login.js + base64.js:)
    SHA256 of ( username + base64( hex-of-SHA256(password) )
                + csrf_param + csrf_token ), as lowercase hex.
    Your real password never travels the wire.
    """
    pw_sha_b64 = base64.b64encode(
        hashlib.sha256(password.encode("utf-8")).hexdigest().encode("ascii")
    ).decode("ascii")
    plain = f"{username}{pw_sha_b64}{csrf_param}{csrf_token}"
    return hashlib.sha256(plain.encode("utf-8")).hexdigest()


def parse_csrf(html: str):
    """Pull the two anti-forgery tokens out of the login page."""
    def meta(name):
        m = re.search(
            rf'<meta\s+name="{name}"\s+content="([^"]+)"', html, re.IGNORECASE)
        return m.group(1) if m else ""
    return meta("csrf_param"), meta("csrf_token")


def unwrap(text: str) -> str:
    """Strip the `while(1); /* ... */` envelope from a response body."""
    text = text.strip()
    if text.startswith(_WRAPPER[0]):
        text = text[len(_WRAPPER[0]):]
    if text.endswith(_WRAPPER[1]):
        text = text[: -len(_WRAPPER[1])]
    return text.strip()


def legacy_ssl_context() -> ssl.SSLContext:
    """A context that tolerates the router's old encryption.

    Three things modern clients reject, allowed *only* for this
    router on this network: no certificate check (its certificate is
    self-signed and would never validate), legacy renegotiation, and
    an old cipher (AES256-SHA256) that modern defaults exclude.
    """
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
    # SSL_OP_LEGACY_SERVER_CONNECT; direct value for older Pythons
    ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 4)
    return ctx


class RouterError(Exception):
    pass


class RouterClient:
    """One logged-in session with the router.

    Routers of this kind allow a single admin session at a time and
    have modest CPUs, so callers should poll slowly (10-15s) and treat
    failures gently — the live view falls back to the door-knocking
    scanner when the router is moody.
    """

    def __init__(self, host: str, username: str, password: str, timeout: float = 8.0):
        self.host = host
        self.username = username
        self.password = password
        self.timeout = timeout
        self.csrf_param = ""
        self.csrf_token = ""
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=legacy_ssl_context()),
            urllib.request.HTTPCookieProcessor(CookieJar()),
        )

    # -- low-level ---------------------------------------------------------

    def _url(self, path: str) -> str:
        return f"https://{self.host}{path}"

    def _request(self, path: str, payload=None):
        """GET or (with payload) POST one JSON call; returns parsed JSON."""
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json;charset=UTF-8"
        req = urllib.request.Request(self._url(path), data=data, headers=headers)
        with self._opener.open(req, timeout=self.timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
        try:
            return json.loads(unwrap(body))
        except json.JSONDecodeError as e:
            raise RouterError(f"router sent something unexpected ({path})") from e

    def _update_csrf(self, result: dict) -> None:
        if isinstance(result, dict):
            self.csrf_param = result.get("csrf_param", self.csrf_param)
            self.csrf_token = result.get("csrf_token", self.csrf_token)

    def _fetch_page(self, path: str) -> str:
        req = urllib.request.Request(self._url(path))
        with self._opener.open(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")

    # -- session -----------------------------------------------------------

    def login(self) -> None:
        """Log in, retrying once if the anti-forgery tokens went stale."""
        for _ in range(2):
            html = self._fetch_page("/")
            self.csrf_param, self.csrf_token = parse_csrf(html)
            if not self.csrf_token:
                raise RouterError("could not find the login tokens on the router page")
            payload = {
                "csrf": {"csrf_param": self.csrf_param,
                         "csrf_token": self.csrf_token},
                "data": {
                    "UserName": self.username,
                    "Password": login_password_hash(
                        self.username, self.password,
                        self.csrf_param, self.csrf_token),
                },
            }
            result = self._request(BASE_PATH + "system/user_login", payload)
            if result.get("errorCategory") == "ok":
                self._update_csrf(result)
                return
            if result.get("errcode") == 1:          # stale tokens — retry
                continue
            raise RouterError(
                "router refused the login — wrong username or password? "
                f"(router said: {result.get('errorCategory', 'unknown error')})")
        raise RouterError("router kept rejecting the login tokens")

    def logout(self) -> None:
        try:
            self._request(BASE_PATH + "system/user_loginout",
                          {"csrf": {"csrf_param": self.csrf_param,
                                    "csrf_token": self.csrf_token},
                           "data": {}})
        except Exception:
            pass  # best effort — the session also expires on its own

    # -- data --------------------------------------------------------------

    def _discover_objnames(self, view_js_path: str) -> dict:
        """Read a page-script from the router and collect its data sources.

        The router's own pages name the data endpoints they use
        (objName: 'something/here'); reading them means we adapt to
        whatever this firmware actually provides, instead of guessing.
        Returns {objName: controller_kind} for 'MultiObj' (lists) and
        others.
        """
        try:
            src = self._fetch_page(view_js_path)
        except (urllib.error.URLError, urllib.error.HTTPError):
            return {}
        found = {}
        for kind in ("MultiObjController", "SingleObjController"):
            for m in re.finditer(
                    rf"{kind}\s*\.\s*create\s*\(\s*\{{(.*?)\}}\s*\)", src, re.S):
                body = m.group(1)
                name = re.search(r"objName\s*:\s*'([^']+)'", body)
                if name:
                    found[name.group(1)] = "MultiObj" if kind.startswith("Multi") else "SingleObj"
        return found

    def devices(self) -> list:
        """All devices the router sees: [{ip, mac, name}, ...].

        Tries the LAN-devices page's own data source first (discovered
        live from the router), with well-known names from this router
        family as backup.
        """
        objnames = []
        discovered = self._discover_objnames("/html/landevices_view.js")
        objnames.extend(k for k, v in discovered.items() if v == "MultiObj")
        objnames.extend(k for k in ("homenetwork/lanhosts", "homenetwork/landevices",
                                    "lan/landevices", "homenetwork/hosts")
                        if k not in objnames)
        for obj in objnames:
            try:
                result = self._request(BASE_PATH + obj)
            except RouterError:
                continue
            self._update_csrf(result if isinstance(result, dict) else {})
            rows = _extract_rows(result)
            if rows:
                return [_normalize_device(r) for r in rows]
        raise RouterError("could not read the device list from the router")

    # -- parental control (blocking at the router) --------------------------

    def parental_control_info(self) -> dict:
        """Discover the router's parental-control data sources.

        Returns the discovered objNames so `block` can use them; the
        exact settings format varies per firmware and is verified
        during live testing.
        """
        return self._discover_objnames("/html/parent_control_view.js")


# -- parsing helpers -------------------------------------------------------

def _extract_rows(result) -> list:
    """Find the list of device records inside a router response,
    whatever key it hides under."""
    if isinstance(result, list):
        return result
    if not isinstance(result, dict):
        return []
    for value in result.values():
        if isinstance(value, list) and value and isinstance(value[0], dict):
            return value
    return []


def _pick(rec: dict, *names):
    for n in names:
        for key, value in rec.items():
            if key.lower() == n and value:
                return value
    return ""


def _normalize_device(rec: dict) -> dict:
    return {
        "ip": str(_pick(rec, "ipaddress", "ip", "ipaddr")),
        "mac": str(_pick(rec, "macaddress", "mac", "macaddr")).lower(),
        "name": str(_pick(rec, "hostname", "devicename", "name", "username")),
    }
