"""Who is online right now — one combined list from up to three places.

* "booth"  — devices on this laptop's own Wi-Fi (the toll booth).  The
  laptop sees them directly, so joins/leaves show up within a second
  or two.  Only these can be capped or blocked.
* "router" — devices on the router's own Wi-Fi/cables, asked from the
  router's admin page every ~12 seconds (gentle on the little CPU in
  there).  This list can lag a few seconds behind reality.
* "scan"   — fallback door-knocking when the router won't talk to us.
  Honest, but it misses deeply-asleep devices.

A phone moving between the router's Wi-Fi and the toll booth will look
like a *new* device (different address, and phones use a different
random MAC per network) — same phone, two identities.  Where the router
or the toll booth knows a hostname, we show it, which usually reveals
they're the same gadget.
"""

from dataclasses import dataclass

import makers
import scanner

ROUTER_INTERVAL = 12.0     # seconds between polite asks of the router
ROUTER_MAX_INTERVAL = 60.0
BOOTH_INTERVAL = 1.0       # toll-booth devices are cheap to check — fast
SCAN_INTERVAL = 10.0       # door-knocking takes a few seconds — gentler pace


@dataclass
class Device:
    ip: str
    mac: str
    name: str = ""
    source: str = "scan"          # booth | router | scan
    blocked: bool = False
    cap: tuple = None             # (down_kbit, up_kbit) or None
    associated: bool = True       # booth: actually connected to the Wi-Fi

    client_id: str = ""
    connection: str = "unknown"  # wired | wireless | unknown

    download_now: float = None
    upload_now: float = None
    used_down: int = None
    used_up: int = None
    daily_limit: int = None
    quota_exhausted: bool = False

    @property
    def key(self):
        # the serial number (MAC) is what makes it the same gadget, even
        # when a different list is the one reporting it (scan -> router)
        return self.mac or self.ip


def booth_devices(booth) -> list:
    """Devices on the toll booth right now, with their caps and blocks."""
    try:
        booth.sync_caps()      # caps follow devices across address changes
    except Exception:
        pass                   # listing must never die on meter trouble
    caps = booth.caps()
    blocked = set(booth.blocked())
    out = []
    for c in booth.devices():
        cap = caps.get(c["mac"]) or caps.get(c["ip"])
        out.append(Device(
            ip=c["ip"], mac=c["mac"], name=c.get("name") or "",
            source="booth", connection="wireless",
            blocked=c["ip"] in blocked,
            cap=tuple(cap) if cap else None,
            associated=c.get("associated", True),
        ))
    return out


def cable_devices(booth) -> list:
    blocked = set(booth.blocked())
    return [Device(ip=r["ip"], mac=r["mac"], name=r["name"],
                   source="cable", connection="wired", client_id=r["client_id"],
                   blocked=r["ip"] in blocked,
                   cap=tuple(r["cap"]) if r["cap"] else None)
            for r in booth.registered_pcs()]


def scan_devices() -> list:
    """One round of door-knocking (works on any router, no password)."""
    import asyncio
    subnet = scanner.autodetect_subnet()
    out = []
    for ip, mac in asyncio.run(scanner.scan(subnet)):
        out.append(Device(ip=ip, mac=mac, source="scan"))
    return out


class RouterPoller:
    """Asks the router for its device list, gently.

    Routers of this family allow one admin session and have small
    CPUs, so: poll every ~12s, on errors wait twice as long each time
    (up to a minute), and after two failures in a row fall back to
    door-knocking until the router behaves again.
    """

    def __init__(self, client):
        self.client = client
        self.interval = ROUTER_INTERVAL
        self.failures = 0
        self.last_ok = 0.0
        self.status = "not asked yet"
        self._last_rows = []

    def poll(self, now: float) -> list:
        """The router list as of the last successful ask.

        Between asks (and while the router is moody) the previous list
        is returned, so the window doesn't make devices blink out and
        back in — the status line tells the honest story instead.
        """
        if now - self.last_ok < self.interval:
            return self._last_rows
        self.last_ok = now
        try:
            rows = self.client.devices()
        except Exception as e:  # noqa: BLE001 - any failure means: back off
            self.failures += 1
            self.interval = min(self.interval * 2, ROUTER_MAX_INTERVAL)
            self.status = (f"router unreachable ({e}) — "
                           + ("using door-knocking instead" if self.failures >= 2
                              else "retrying"))
            return self._last_rows
        self.failures = 0
        self.interval = ROUTER_INTERVAL
        self.status = "ok"
        self._last_rows = [
            Device(ip=r["ip"], mac=r["mac"], name=r.get("name") or "",
                   source="router", connection=r.get("connection", "unknown"))
            for r in rows]
        return self._last_rows


def diff(old: list, new: list):
    """Compare two snapshots -> (joined, left) events for the log.

    A device counts as the same one while its serial number (MAC)
    matches — so when the router answers and replaces the door-knocking
    list, nobody appears to leave and re-join.

    Note the honest asymmetry: joins are certain the moment they're
    seen; a "leave" from the router/scan sources may just mean the
    list is catching up (or a phone dozed off).
    """
    old_keys = {d.key for d in old}
    new_keys = {d.key for d in new}
    joined = [d for d in new if d.key not in old_keys]
    left = [d for d in old if d.key not in new_keys]
    return joined, left


def describe(device: Device) -> str:
    """One line for the log, e.g. 'sebas-phone (10.42.0.7) via hotspot'."""
    who = device.name or makers.maker_of(device.mac)
    where = {"booth": "my Wi-Fi", "router": "router", "scan": "scan", "cable": "paired PC"}[device.source]
    return f"{who or 'device'} ({device.ip or 'no address yet'}) via {where}"
