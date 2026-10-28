"""The door-knocking scanner — the fallback way to list devices.

Your home network is one "subnet" (a range of addresses, like one
apartment building: 192.168.1.0 to 192.168.1.255, with the router at
.1).  This scanner "knocks on every door": it tries to open a network
connection to each address.  Any answer — even "port closed" — proves
someone lives there, and the system then remembers their address in
its "neighbor table", which we read at the end.

Honest limitations (why this is only the fallback):
* a device that is connected but deep asleep may not answer;
* it sees devices only on this machine's own subnet;
* it can list devices but not limit or block them (only the toll booth
  or the router can do that).
"""

import asyncio
import ipaddress
import json
import re
import subprocess

# A spread of "doors" almost every gadget answers on: web (80/443/8080),
# Windows file sharing (445/139), remote login (22/23), printers (9100),
PROBE_PORTS = (80, 443, 445, 139, 22, 23, 8080, 9100)

# Neighbor-table states that mean "a real device answered".
# FAILED/INCOMPLETE mean "we knocked, nobody home".
LIVE_STATES = {"REACHABLE", "STALE", "DELAY", "PROBE", "PERMANENT"}


def default_gateway_iface(route_output: str) -> str:
    """Which network card leads to the router, from `ip route` text."""
    for line in route_output.splitlines():
        if line.startswith("default"):
            m = re.search(r"\bdev\s+(\S+)", line)
            if m:
                return m.group(1)
    return ""


def iface_subnet(addr_json: str, iface: str) -> str:
    """The subnet of a card, from `ip -j addr` output (JSON text)."""
    for entry in json.loads(addr_json):
        if entry.get("ifname") == iface:
            for info in entry.get("addr_info", []):
                if info.get("family") == "inet":
                    net = ipaddress.ip_network(
                        f"{info['local']}/{info.get('prefixlen', 24)}", strict=False
                    )
                    return str(net)
    return ""


def _state(entry: dict) -> str:
    """Neighbor state as text — `ip -j` returns a list, older forms a string."""
    state = entry.get("state", "")
    return " ".join(state).upper() if isinstance(state, list) else str(state).upper()


def parse_neigh_json(neigh_json: str, subnet: str = "") -> list:
    """Live devices from `ip -j neigh` output: [(ip, mac), ...]."""
    net = ipaddress.ip_network(subnet, strict=False) if subnet else None
    out = []
    for entry in json.loads(neigh_json):
        if not (set(_state(entry).split()) & LIVE_STATES):
            continue
        ip, mac = entry.get("dst", ""), entry.get("lladdr", "")
        if not ip or not mac or not entry.get("dev"):
            continue
        try:
            if net and ipaddress.ip_address(ip) not in net:
                continue
        except ValueError:
            continue
        out.append((ip, mac.lower()))
    return out


async def _knock(host: str, port: int, timeout: float) -> None:
    """Try to open one connection.  We don't care if it fails —
    the attempt itself makes the system ask 'who has this address?'."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout
        )
        writer.close()
        await writer.wait_closed()
    except Exception:
        pass


async def scan(subnet: str, timeout: float = 0.4, ports=PROBE_PORTS) -> list:
    """Knock on every door in the subnet, then read the neighbor table.

    Returns [(ip, mac), ...] sorted by address.  Needs no special
    rights, works on any router, misses only deeply-asleep devices.
    """
    net = ipaddress.ip_network(subnet, strict=False)
    hosts = [str(h) for h in net.hosts()]
    tasks = [asyncio.ensure_future(_knock(h, p, timeout))
             for h in hosts for p in ports]
    if tasks:
        await asyncio.gather(*tasks)
    await asyncio.sleep(0.5)  # let the neighbor table settle

    proc = await asyncio.create_subprocess_exec(
        "ip", "-j", "neigh", "show",
        stdout=asyncio.subprocess.PIPE,
    )
    raw = await proc.stdout.read()
    return sorted(parse_neigh_json(raw.decode(), subnet), key=lambda t: ipaddress.ip_address(t[0]))


def autodetect_subnet() -> str:
    """Figure out which subnet to scan: the one this machine talks on."""
    route = subprocess.run(["ip", "route", "show"], capture_output=True, text=True).stdout
    iface = default_gateway_iface(route)
    if not iface:
        return "192.168.1.0/24"
    addr = subprocess.run(["ip", "-4", "-j", "addr", "show", "dev", iface],
                          capture_output=True, text=True).stdout
    return iface_subnet(addr, iface) or "192.168.1.0/24"
