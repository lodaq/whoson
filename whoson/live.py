"""The live view: one combined, self-updating table of who's online.

Devices come from up to three places, and the table says which:

* "booth"  — devices on this laptop's hotspot.  The laptop sees them
  directly, so joins/leaves show up within a second or two.
* "router" — devices on the router's own Wi-Fi/cables, asked from the
  router's admin page every ~12 seconds (gentle on the little CPU in
  there).  This list can lag a few seconds behind reality.
* "scan"   — fallback door-knocking when the router won't talk to us.
  Honest, but it misses deeply-asleep devices.

A phone moving between the router's Wi-Fi and the hotspot will look
like a *new* device (different address, and phones use a different
random MAC per network) — same phone, two identities.  Where the
router or the hotspot knows a hostname, we show it, which usually
reveals they're the same gadget.
"""

import time
from dataclasses import dataclass, field

from . import scanner, vendor

ROUTER_INTERVAL = 12.0     # seconds between polite asks of the router
ROUTER_MAX_INTERVAL = 60.0
BOOTH_INTERVAL = 2.0       # hotspot clients are cheap to check — fast
SCAN_INTERVAL = 10.0       # door-knocking takes a few seconds — gentler pace


@dataclass
class Device:
    ip: str
    mac: str
    name: str = ""
    source: str = "scan"          # booth | router | scan
    blocked: bool = False
    limit: tuple = None           # (down_mbps, up_mbps) or None
    associated: bool = True       # booth: actually connected to the Wi-Fi

    @property
    def key(self):
        return (self.source, self.mac or self.ip)


def booth_devices(gateway) -> list:
    try:
        gateway.sync_limits()   # caps follow devices across address changes
    except Exception:
        pass                    # listing must never die on meter trouble
    limits = gateway.limits()
    blocked = set(gateway.blocked())
    out = []
    for c in gateway.clients():
        cap = limits.get(c["mac"]) or limits.get(c["ip"])
        out.append(Device(
            ip=c["ip"], mac=c["mac"], name=c.get("name") or "",
            source="booth",
            blocked=c["ip"] in blocked,
            limit=tuple(cap) if cap else None,
            associated=c.get("associated", True),
        ))
    return out


def scan_devices() -> list:
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

    def poll(self, now: float) -> list:
        if now - self.last_ok < self.interval:
            return []
        self.last_ok = now
        try:
            rows = self.client.devices()
        except Exception as e:  # noqa: BLE001 - any failure means: back off
            self.failures += 1
            self.interval = min(self.interval * 2, ROUTER_MAX_INTERVAL)
            self.status = (f"router unreachable ({e}) — "
                           + ("using door-knocking instead" if self.failures >= 2
                              else "retrying"))
            return []
        self.failures = 0
        self.interval = ROUTER_INTERVAL
        self.status = "ok"
        return [Device(ip=r["ip"], mac=r["mac"], name=r.get("name") or "",
                       source="router") for r in rows]


def diff(old: list, new: list):
    """Compare two snapshots -> events for the log.

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
    who = device.name or vendor.vendor_of(device.mac)
    where = {"booth": "hotspot", "router": "router", "scan": "scan"}[device.source]
    return f"{who or 'device'} ({device.ip or 'no address yet'}) via {where}"


def render(devices: list, footer_lines: list = None, width: int = 100) -> str:
    """Draw the table.  Flags: 📶 on the hotspot, ⛔ blocked, 5/1 capped,
    ~ asleep (associated to hotspot Wi-Fi but quiet)."""
    def sort_key(d):
        import ipaddress
        try:
            return (0, ipaddress.ip_address(d.ip or "0.0.0.0"))
        except ValueError:
            return (1, d.ip)
    rows = sorted(devices, key=sort_key)
    flags = []
    for d in rows:
        f = ""
        if d.source == "booth":
            f += "📶"
            if not d.associated:
                f += "~"
        if d.blocked:
            f += "⛔"
        if d.limit:
            down, up = d.limit
            def short(k):
                return f"{k // 1000}M" if k % 1000 == 0 and k >= 1000 else f"{k // 8}KB/s"
            f += f" {short(down)}↓/{short(up)}↑"
        flags.append(f.strip())
    name_w = max([len(d.name or "-") for d in rows] + [4])
    vend = [vendor.vendor_of(d.mac) for d in rows]
    vend_w = max([len(v) for v in vend] + [6])
    head = f"{'NAME':<{name_w}}  {'IP':<15}  {'MAC':<17}  {'MAKER':<{vend_w}}  FLAGS"
    lines = [head, "-" * min(len(head) + 20, width)]
    for d, v, f in zip(rows, vend, flags):
        lines.append(
            f"{(d.name or '-'):<{name_w}}  {(d.ip or '-'):<15}  {(d.mac or '-'):<17}  "
            f"{(v if v != 'unknown' else '-'):<{vend_w}}  {f}")
    lines.append("")
    lines.append(f"{len(rows)} device(s).  📶=on this hotspot  ⛔=blocked  "
                 f"5M↓/1M↑= speed cap (down/up)")
    for line in footer_lines or []:
        lines.append(line)
    return "\n".join(lines)


def watch(gateway, router_poller: RouterPoller = None, once: bool = False,
          json_mode: bool = False, print_fn=print):
    """The main live loop (or a single snapshot when once=True)."""
    import json as _json
    router_devices = []
    while True:
        now = time.time()
        devices = booth_devices(gateway)
        use_scan = router_poller is None or router_poller.failures >= 2
        if use_scan:
            # no router (or it's sulking): fall back to door-knocking,
            # which is slower and sleepier — so we run it on its own clock
            if now - getattr(watch, "_last_scan", 0) >= SCAN_INTERVAL:
                try:
                    watch._scan_cache = scan_devices()
                except Exception:
                    watch._scan_cache = []
                watch._last_scan = now
            devices += getattr(watch, "_scan_cache", [])
        else:
            router_devices = router_poller.poll(now) or router_devices
            devices += router_devices
        if json_mode:
            print_fn(_json.dumps([_device_dict(d) for d in devices], indent=2))
            return
        if once:
            footer = []
            if router_poller:
                footer.append(f"router source: {router_poller.status}")
            print_fn(render(devices, footer))
            return
        joined, left = diff(watch._prev, devices)
        events = [f"+ {time.strftime('%H:%M:%S')} {describe(d)}" for d in joined]
        events += [f"- {time.strftime('%H:%M:%S')} {describe(d)}" for d in left]
        footer = []
        if router_poller:
            footer.append(f"router source: {router_poller.status} (refreshes "
                          f"every {router_poller.interval:.0f}s; may lag)")
        if getattr(watch, "_events", None) is None:
            watch._events = []
        watch._events = (events + watch._events)[:8]
        footer += ["", *watch._events]
        print_fn("\033[2J\033[H" + render(devices, footer))
        watch._prev = devices
        time.sleep(BOOTH_INTERVAL)


watch._prev = []


def _device_dict(d: Device) -> dict:
    return {
        "name": d.name, "ip": d.ip, "mac": d.mac,
        "maker": vendor.vendor_of(d.mac), "source": d.source,
        "blocked": d.blocked,
        "limit_mbps": list(d.limit) if d.limit else None,
    }
