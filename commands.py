"""Pure generators for every system command `whoson` can run.

Nothing in this file touches the system — each function only *builds*
command lists.  That means the unit tests can verify every network
change we make without needing administrator rights.

Every command is a list of program arguments (no shell involved), for
example:  ["nft", "add", "element", ...]

Plain-language background for the three tools used here:

* nmcli  — talks to NetworkManager, the standard Linux service that
  manages network connections.  It can create a Wi-Fi hotspot.
* tc     — "traffic control", the Linux traffic meter.  It can cap how
  fast data flows to/from a given address (this is the speed limit).
* nft    — nftables, the Linux firewall.  Used here to cut a device's
  internet (block) and to keep hotspot clients away from the laptop's
  own services (isolation).
"""

# Names used for the pieces the tool owns.  One nftables table means
# clean teardown: "delete the table" removes every rule we added.
NFT_TABLE = "whoson"
BLOCKED_SET = "blocked_v4"

# Default "no limit" class on the htb tree: clients without a cap land
# here and run at line speed.
DEFAULT_CLASS = "1:10"
LINE_RATE_MBPS = 1000  # "unlimited" bucket, far above real Wi-Fi speed


def classid_for_ip(ip: str) -> str:
    """Stable traffic-control class ID for a client address.

    Uses the last number of the address (e.g. 10.42.0.7 -> 1:107) so
    limits survive re-application and never collide.
    """
    last = int(ip.rsplit(".", 1)[1])
    return f"1:{100 + last}"


# ---------------------------------------------------------------------------
# Hotspot (the toll booth Wi-Fi) — hostapd + dnsmasq directly
#
# Why not NetworkManager?  NM refuses software-AP interfaces on this
# setup (tried: it leaves the device "unavailable").  hostapd is the
# standard Linux tool for running a Wi-Fi hotspot and takes the
# interface as it finds it.  dnsmasq hands out addresses to devices
# that join.  NM keeps managing the laptop's own connection to the
# router the whole time, untouched.
# ---------------------------------------------------------------------------

BOOTH_IP = "10.42.0.1"
BOOTH_CIDR = "10.42.0.0/24"
HOSTAPD_PID = "/run/whoson-hostapd.pid"
DNSMASQ_PID = "/run/whoson-dnsmasq.pid"
DNSMASQ_LEASES = "/var/lib/whoson/dnsmasq.leases"
HOSTAPD_CONF = "hostapd.conf"   # written inside our config dir


def freq_to_channel(freq) -> int:
    """Radio frequency (MHz) -> channel number, e.g. 2472 -> 9."""
    freq = int(float(freq))
    if freq == 2484:
        return 14
    if 2412 <= freq <= 2472:
        return (freq - 2407) // 5
    if 4910 <= freq <= 4980:
        return (freq - 4000) // 5
    if 5000 <= freq <= 5825:
        return (freq - 5000) // 5
    raise ValueError(f"not a Wi-Fi frequency: {freq}")


def hostapd_conf_text(ssid: str, psk: str, channel: int) -> str:
    """The hotspot's configuration file (pure text; caller writes it).

    The channel matches whatever the laptop's own Wi-Fi link uses —
    one radio, one channel (that's the sharing rule for this chip).
    """
    hw = "a" if channel > 14 else "g"
    return f"""interface=ap0
driver=nl80211
ssid={ssid}
channel={channel}
hw_mode={hw}
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_passphrase={psk}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
logger_syslog=-1
logger_syslog_level=3
"""


def ap_create_cmds(wifi_iface: str, ap_iface: str) -> list:
    """Create the extra Wi-Fi interface for the hotspot role.

    Safe to re-run: the 'add' may fail harmlessly if it already
    exists (the gateway checks first).  'managed no' keeps
    NetworkManager from touching it — it runs its own connection to
    the router, hostapd runs ours.
    """
    return [
        ["iw", "dev", wifi_iface, "interface", "add", ap_iface, "type", "__ap"],
        ["nmcli", "device", "set", ap_iface, "managed", "no"],
        ["iw", "dev", ap_iface, "set", "type", "__ap"],
        ["ip", "link", "set", ap_iface, "up"],
        ["ip", "addr", "add", f"{BOOTH_IP}/24", "dev", ap_iface],
    ]


def ap_del_cmds(ap_iface: str) -> list:
    return [["iw", "dev", ap_iface, "del"]]


def hostapd_start_cmd(conf_path: str) -> list:
    # the config file is a bare positional argument — hostapd has no -c
    return [["hostapd", "-B", "-P", HOSTAPD_PID, conf_path]]


def dnsmasq_start_cmd(router_ip: str) -> list:
    """Start the address-handout + name service for hotspot clients.

    Runs as a background service; leases land in DNSMASQ_LEASES,
    which is how we learn device names later.
    """
    return [
        ["mkdir", "-p", "/var/lib/whoson"],
        ["dnsmasq",
         "--conf-file=/dev/null",
         "--interface=ap0",
         "--bind-dynamic",
         "--dhcp-range=10.42.0.100,10.42.0.200,255.255.255.0,12h",
         "--dhcp-option=option:router," + BOOTH_IP,
         "--dhcp-option=option:dns-server," + BOOTH_IP,
         "--no-resolv",
         "--no-hosts",
         f"--server={router_ip}",
         f"--pid-file={DNSMASQ_PID}",
         f"--dhcp-leasefile={DNSMASQ_LEASES}"],
    ]


def stop_daemon_cmds() -> list:
    """Stop both background services (tolerates 'not running')."""
    out = []
    for pidfile in (HOSTAPD_PID, DNSMASQ_PID):
        out += [["sh", "-c", f"if [ -f {pidfile} ]; then kill $(cat {pidfile}) 2>/dev/null; rm -f {pidfile}; fi"]]
    return out


def forwarding_on_cmds() -> list:
    """Allow the laptop to pass traffic between hotspot and router."""
    return [["sysctl", "-q", "-w", "net.ipv4.ip_forward=1"]]


def nat_cmds(ap_iface: str = "ap0") -> list:
    """One-to-many address sharing (NAT) in our own firewall table.

    Without this, packets from the 10.42.x world wouldn't be let back
    in by the router; with it, the whole hotspot appears to the
    router as this one laptop.
    """
    quoted = f'"{ap_iface}"'
    return [
        ["nft", "add", "chain", "inet", NFT_TABLE, "whoson-nat",
         "{ type nat hook postrouting priority 100 ; }"],
        ["nft", "add", "rule", "inet", NFT_TABLE, "whoson-nat",
         "ip", "saddr", BOOTH_CIDR, "oifname", "!=", quoted, "masquerade"],
    ]


# ---------------------------------------------------------------------------
# Speed limits — Linux traffic control (tc)
# ---------------------------------------------------------------------------

def ifb_setup_cmds(ifb: str = "ifb0") -> list:
    """Set up the IFB device — the trick that meters *upload*.

    Linux can only shape traffic it *sends*.  Data arriving from a
    phone is "incoming", so we bounce it through a virtual device
    (IFB) first; the trip turns it into outgoing traffic there, which
    tc can cap.  Download (data going to the phone) is shaped directly
    on the hotspot interface.
    """
    return [
        ["ip", "link", "add", ifb, "type", "ifb"],
        ["ip", "link", "set", ifb, "up"],
    ]


def tc_init_cmds(ap_iface: str, ifb: str = "ifb0") -> list:
    """Install the two traffic meters (download on ap, upload on ifb)."""
    burst = ["burst", "512kb"]
    return [
        # download meter: everything the laptop SENDS to hotspot clients
        ["tc", "qdisc", "replace", "dev", ap_iface, "root", "handle", "1:", "htb", "default", "10"],
        ["tc", "class", "replace", "dev", ap_iface, "parent", "1:", "classid", DEFAULT_CLASS,
         "htb", "rate", f"{LINE_RATE_MBPS}mbit", "ceil", f"{LINE_RATE_MBPS}mbit", *burst],
        # upload meter: mirror hotspot ingress onto the IFB device
        ["tc", "qdisc", "replace", "dev", ap_iface, "ingress"],
        ["tc", "filter", "replace", "dev", ap_iface, "ingress", "matchall",
         "action", "mirred", "egress", "redirect", "dev", ifb],
        ["tc", "qdisc", "replace", "dev", ifb, "root", "handle", "1:", "htb", "default", "10"],
        ["tc", "class", "replace", "dev", ifb, "parent", "1:", "classid", DEFAULT_CLASS,
         "htb", "rate", f"{LINE_RATE_MBPS}mbit", "ceil", f"{LINE_RATE_MBPS}mbit", *burst],
    ]


def tc_limit_cmds(ap_iface: str, ip: str, down_kbit: int, up_kbit: int,
                  ifb: str = "ifb0") -> list:
    """Cap one client.  Speeds are given in kilobits/second (kbit):
    100 KB/s (kilobytes, as downloads display them) = 800 kbit.

    The burst allowance (data that may flow before the cap bites)
    scales with the cap — half a second's worth, clamped to sane
    bounds — so tiny caps stay tiny instead of leaking a huge burst.
    """
    cid = classid_for_ip(ip)

    def burst_for(rate_kbit: int) -> str:
        return f"{min(512, max(4, rate_kbit // 16))}kb"

    def bucket(dev: str, rate_kbit: int, match: str) -> list:
        return [
            ["tc", "class", "replace", "dev", dev, "parent", "1:", "classid", cid,
             "htb", "rate", f"{rate_kbit}kbit", "ceil", f"{rate_kbit}kbit",
             "burst", burst_for(rate_kbit)],
            ["tc", "filter", "replace", "dev", dev, "protocol", "ip", "parent", "1:",
             "prio", "1", "u32", "match", "ip", match, ip, "flowid", cid],
        ]

    # download bucket (traffic to the phone) + upload bucket (from it)
    return bucket(ap_iface, down_kbit, "dst") + bucket(ifb, up_kbit, "src")


def tc_unlimit_cmds(ap_iface: str, ip: str, ifb: str = "ifb0") -> list:
    """Remove one client's cap (delete its buckets and matching rules).

    Re-matching is easier than surgical filter deletes: drop all prio-1
    u32 filters, then re-add filters for every client that still has a
    limit.  The gateway layer calls this followed by the still-limited
    clients' filter lines.
    """
    cid = classid_for_ip(ip)
    return [
        ["tc", "class", "del", "dev", ap_iface, "classid", cid],
        ["tc", "class", "del", "dev", ifb, "classid", cid],
    ]


def tc_teardown_cmds(ap_iface: str, ifb: str = "ifb0") -> list:
    """Remove both meters entirely (back to unlimited for everyone)."""
    return [
        ["tc", "qdisc", "del", "dev", ap_iface, "root"],
        ["tc", "qdisc", "del", "dev", ap_iface, "ingress"],
        ["tc", "qdisc", "del", "dev", ifb, "root"],
    ]


def tc_filter_cmd(ap_iface: str, ip: str, ifb: str = "ifb0"):
    """The two filter lines for one still-limited client (see unlimit)."""
    cid = classid_for_ip(ip)
    return [
        ["tc", "filter", "replace", "dev", ap_iface, "protocol", "ip", "parent", "1:",
         "prio", "1", "u32", "match", "ip", "dst", ip, "flowid", cid],
        ["tc", "filter", "replace", "dev", ifb, "protocol", "ip", "parent", "1:",
         "prio", "1", "u32", "match", "ip", "src", ip, "flowid", cid],
    ]


# ---------------------------------------------------------------------------
# LAN toll-booth mode — metering cabled PCs without any new hardware
#
# A PC on the same network as the laptop can send its internet traffic
# through the laptop simply by being told "your gateway is the laptop"
# (the script on the PC does that).  The laptop then:
#   * wears a second, fixed address on its usual network card (the alias,
#     e.g. 192.168.1.253) so the PC always knows where to send;
#   * shares its own connection back out (one-armed NAT — the PC's
#     traffic leaves wearing the laptop's name);
#   * meters it with the same tc buckets as the Wi-Fi booth, just on
#     the laptop's usual network card instead of the hotspot's.
# ---------------------------------------------------------------------------

LAN_NAT_CHAIN = "whoson-lannat"


def nft_table_cmd() -> list:
    """Make sure our own firewall table exists.

    The hotspot normally creates it, but cable mode must work on its
    own too — without the table every later `nft` call fails and the
    cabled PC silently gets no internet.  Re-running is harmless: nft
    just complains that the table is already there.
    """
    return [["nft", "add", "table", "inet", NFT_TABLE]]


def lan_alias_cmds(wifi_iface: str, alias_ip: str) -> list:
    return [["ip", "addr", "add", f"{alias_ip}/24", "dev", wifi_iface]]


def lan_alias_del_cmds(wifi_iface: str, alias_ip: str) -> list:
    return [["ip", "addr", "del", f"{alias_ip}/24", "dev", wifi_iface]]


def nft_lan_prepare_cmds(chain: str = LAN_NAT_CHAIN) -> list:
    """Create the sharing table + chain, then empty the chain.

    Emptying first means re-applying caps never piles up duplicate
    rules, and a PC that was just uncapped loses its old rule.
    """
    return nft_table_cmd() + [
        ["nft", "add", "chain", "inet", NFT_TABLE, chain,
         "{ type nat hook postrouting priority 100 ; }"],
        ["nft", "flush", "chain", "inet", NFT_TABLE, chain],
    ]


def lan_nat_cmds(client_ip: str, local_subnet: str = "192.168.1.0/24",
                 chain: str = LAN_NAT_CHAIN) -> list:
    """Address-sharing for one cabled PC.

    Traffic from the PC that isn't for the local network leaves wearing
    the laptop's name (masquerade).  Replies come back to the laptop
    and are handed to the PC — that's what makes the one-armed trick work.
    The table/chain are created by `nft_lan_prepare_cmds` first.
    """
    return [
        ["nft", "add", "rule", "inet", NFT_TABLE, chain,
         "ip", "saddr", client_ip, "ip", "daddr", "!=", local_subnet,
         "masquerade"],
    ]

# ---------------------------------------------------------------------------
# Firewall — nftables (blocking + laptop isolation)
# ---------------------------------------------------------------------------

def nft_init_cmds(ap_iface: str) -> list:
    """Create our firewall table with two jobs:
    1. isolation — hotspot clients may use the internet but NOT reach
       the laptop itself (only DHCP and DNS, which the hotspot needs);
    2. blocking  — addresses in the "blocked" set get no internet at
       all, in either direction.
    """
    quoted = f'"{ap_iface}"'  # nft wants interface names as quoted strings
    return [
        ["nft", "add", "table", "inet", NFT_TABLE],
        ["nft", "add", "set", "inet", NFT_TABLE, BLOCKED_SET, "{ type ipv4_addr ; }"],
        ["nft", "add", "chain", "inet", NFT_TABLE, "input",
         "{ type filter hook input priority 0 ; policy accept ; }"],
        ["nft", "add", "chain", "inet", NFT_TABLE, "forward",
         "{ type filter hook forward priority 0 ; policy accept ; }"],
        # isolation: hotspot clients may reach DHCP/DNS (needed to join
        # and to resolve names) but nothing else on the laptop itself
        ["nft", "add", "rule", "inet", NFT_TABLE, "input",
         "iifname", quoted, "udp", "dport", "{ 53, 67, 68 }", "accept"],
        ["nft", "add", "rule", "inet", NFT_TABLE, "input",
         "iifname", quoted, "tcp", "dport", "53", "accept"],
        ["nft", "add", "rule", "inet", NFT_TABLE, "input",
         "iifname", quoted, "drop"],
        # blocking: members of the blocked set get no internet, either direction
        ["nft", "add", "rule", "inet", NFT_TABLE, "forward",
         "ip", "saddr", f"@{BLOCKED_SET}", "drop"],
        ["nft", "add", "rule", "inet", NFT_TABLE, "forward",
         "ip", "daddr", f"@{BLOCKED_SET}", "drop"],
    ]


def nft_block_cmds(ip: str) -> list:
    return [["nft", "add", "element", "inet", NFT_TABLE, BLOCKED_SET, "{", ip, "}"]]


def nft_unblock_cmds(ip: str) -> list:
    return [["nft", "delete", "element", "inet", NFT_TABLE, BLOCKED_SET, "{", ip, "}"]]


def nft_list_blocked_cmd() -> list:
    return [["nft", "-j", "list", "set", "inet", NFT_TABLE, BLOCKED_SET]]


def nft_teardown_cmds() -> list:
    return [["nft", "delete", "table", "inet", NFT_TABLE]]


# ---------------------------------------------------------------------------
# Reading current state (no changes)
# ---------------------------------------------------------------------------

def station_dump_cmd(ap_iface: str) -> list:
    """List devices currently associated to the hotspot (Wi-Fi level)."""
    return [["iw", "dev", ap_iface, "station", "dump"]]


def neigh_cmd(ap_iface: str) -> list:
    """The system's address book for the hotspot: address -> MAC."""
    return [["ip", "-j", "neigh", "show", "dev", ap_iface]]


def addr_cmd(ap_iface: str) -> list:
    """The hotspot's own address (the gateway handed to clients)."""
    return [["ip", "-4", "-j", "addr", "show", "dev", ap_iface]]
