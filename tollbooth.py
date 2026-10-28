"""The toll booth: this laptop as a gateway with speed caps.

Devices that join the hotspot Wi-Fi get their internet through this
laptop (device -> laptop -> router).  Because their traffic passes
through us, Linux can meter it exactly (tc) and cut it (nftables).

State ownership, kept deliberately boring:
* who is blocked  -> the firewall's own "blocked" set (kernel truth)
* who is limited  -> a small JSON file (~/.config/whoson/caps.json),
  re-applied wholesale on every change so the kernel never holds stale
  rules
* who is connected-> asked live from the Wi-Fi chip + neighbor table
"""

import glob
import ipaddress
import json
import os
import re
import shlex
import subprocess
import time

import commands
import settings
import speeds
import scanner
from scanner import LIVE_STATES

AP_IFACE = "ap0"
IFB = "ifb0"
CAPS_PATH = os.path.join(settings.CONFIG_DIR, "caps.json")


# ---------------------------------------------------------------------------
# Command runner (sudo-aware, dry-run aware)
# ---------------------------------------------------------------------------

ROOT_TOOLS = {"nmcli", "tc", "nft", "ip", "iw", "sysctl", "dnsmasq",
              "hostapd", "mkdir", "sh"}


class RunError(Exception):
    pass


def run(argv, dry=False, check=True, quiet=False):
    """Run one generated command.

    * dry: print it instead of running (no rights needed)
    * mutating tools get sudo when we're not root; read-only ones don't
    """
    if dry:
        print("  " + " ".join(shlex.quote(str(a)) for a in argv))
        return ""
    argv = [str(a) for a in argv]
    if os.geteuid() != 0 and argv[0] in ROOT_TOOLS:
        argv = ["sudo", "-n"] + argv
    proc = subprocess.run(argv, capture_output=True, text=True)
    if check and proc.returncode != 0:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        raise RunError(f"`{' '.join(argv[:4])}...` failed: {detail[-1] if detail else 'unknown error'}")
    if not quiet:
        return proc.stdout
    return proc.stdout


def run_many(cmds, dry=False):
    for cmd in cmds:
        run(cmd, dry=dry)


def sudo_available() -> bool:
    if os.geteuid() == 0:
        return True
    return subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def pick_wifi_iface() -> str:
    """The laptop's real Wi-Fi card (the one already talking to the router)."""
    for name in sorted(os.listdir("/sys/class/net")):
        if os.path.isdir(f"/sys/class/net/{name}/phy80211") and name != AP_IFACE:
            return name
    return ""


def parse_station_dump(text: str) -> list:
    """MACs currently connected to the hotspot, from `iw station dump`."""
    return re.findall(r"^Station\s+([0-9a-fA-F:]{17})", text, re.M)


def parse_neigh(json_text: str, iface=AP_IFACE) -> dict:
    """{ip: mac} for live entries on the hotspot interface."""
    out = {}
    try:
        entries = json.loads(json_text)
    except json.JSONDecodeError:
        return out
    for e in entries:
        if e.get("dev") != iface:
            continue
        state = e.get("state", "")
        state = " ".join(state) if isinstance(state, list) else str(state)
        if state.upper() not in LIVE_STATES:
            continue
        ip, mac = e.get("dst"), e.get("lladdr")
        if ip and mac:
            out[ip] = mac.lower()
    return out


def parse_leases_records(paths=None) -> list:
    """Address-handout records for the hotspot: [{mac, ip, name}, ...].

    Each line of a dnsmasq lease file reads
    `<expiry> <mac> <ip> <hostname-or-*> [client-id]`.  This is the
    authoritative record of who received which address — the neighbor
    table only learns a mapping when the laptop itself talks to a
    device, which for phones it usually never does.
    """
    if paths is None:
        paths = (glob.glob("/var/lib/NetworkManager/dnsmasq*.leases")
                 + ["/var/lib/misc/dnsmasq.leases",
                    commands.DNSMASQ_LEASES])
    records = []
    for path in paths:
        lines = []
        try:
            with open(path) as f:
                lines = f.readlines()
        except FileNotFoundError:
            continue
        except PermissionError:
            # the file belongs to the background service; ask politely
            out = subprocess.run(["sudo", "-n", "cat", path],
                                 capture_output=True, text=True)
            if out.returncode != 0:
                continue
            lines = out.stdout.splitlines(keepends=True)
        for line in lines:
            parts = line.split()
            if len(parts) >= 4:
                records.append({
                    "mac": parts[1].lower(),
                    "ip": parts[2],
                    "name": "" if parts[3] == "*" else parts[3],
                })
    return records


def parse_addr(json_text: str, iface=AP_IFACE) -> str:
    """The hotspot's own address (e.g. 10.42.0.1), for display only."""
    try:
        for entry in json.loads(json_text):
            if entry.get("ifname") == iface:
                for info in entry.get("addr_info", []):
                    if info.get("family") == "inet":
                        return info["local"]
    except (json.JSONDecodeError, KeyError):
        pass
    return ""


# ---------------------------------------------------------------------------
# The gateway itself
# ---------------------------------------------------------------------------

class TollBooth:
    def __init__(self, cfg: dict, dry: bool = False):
        self.cfg = cfg
        self.dry = dry
        self.wifi = pick_wifi_iface() or "wlp111s0"

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> str:
        """Turn the toll booth on.  Returns a plain-language summary."""
        if not self.dry and not sudo_available():
            raise RunError(
                "admin rights are needed — run `sudo -v` in a terminal first "
                "(it asks for your password once), then press Start again")
        ssid = self.cfg.get("hotspot_ssid") or "whoson"
        psk = self.cfg.get("hotspot_psk") or ""
        if len(psk) < 8:
            raise RunError(
                "the hotspot needs a Wi-Fi password of at least 8 characters — "
                "open 'Wi-Fi name & password…' in the window and choose one")

        channel = self._sta_channel()
        # the interface must match the laptop's own link channel: one
        # radio, one channel — the sharing rule for this Wi-Fi chip
        conf_path = self._write_hostapd_conf(ssid, psk, channel)

        # a previous run (or crash) may have left pieces behind — start clean
        if not self.dry:
            for cmd in (commands.stop_daemon_cmds()
                        + commands.tc_teardown_cmds(AP_IFACE, IFB)
                        + commands.nft_teardown_cmds()):
                run(cmd, check=False, quiet=True)

        # create/prepare the hotspot interface (type AP, unmanaged by NM)
        if not self._ap_exists():
            run(commands.ap_create_cmds(self.wifi, AP_IFACE)[0], dry=self.dry)
        if not self.dry:
            self._ensure_ap_ready()

        run_many(commands.forwarding_on_cmds(), self.dry)
        for cmd in commands.dnsmasq_start_cmd(self.cfg.get("router_ip", "192.168.1.1")):
            run(cmd, dry=self.dry)
        for cmd in commands.hostapd_start_cmd(conf_path):
            run(cmd, dry=self.dry)
        if not self.dry:
            self._wait_for_hostapd()
        # ifb0 may already exist from an earlier run — that's fine, just up it
        for cmd in commands.ifb_setup_cmds(IFB):
            run(cmd, dry=self.dry, check=False)
        if not self.dry and subprocess.run(["ip", "link", "show", IFB],
                                           capture_output=True).returncode != 0:
            raise RunError("could not create the upload-meter device (ifb0)")
        run_many(commands.tc_init_cmds(AP_IFACE, IFB), self.dry)
        run_many(commands.nft_init_cmds(AP_IFACE), self.dry)
        run_many(commands.nat_cmds(AP_IFACE), self.dry)
        if not self.dry:
            self.reapply_caps()
        chan_note = f", channel {channel} (shared with your Wi-Fi)" if channel else ""
        return (f"Hotspot '{ssid}' is up on {AP_IFACE}{chan_note}. "
                f"Password: {psk}. Devices can join it now — point the ones "
                f"you want to cap at this Wi-Fi.")

    def _ensure_ap_ready(self, attempts: int = 6) -> None:
        """Get ap0 into AP mode and up, retrying around NetworkManager.

        NM resets a wifi interface to 'managed' type when it lets go of
        it — a race we win by re-asserting, briefly, until it sticks.
        """
        for _ in range(attempts):
            run(["nmcli", "device", "set", AP_IFACE, "managed", "no"],
                check=False, quiet=True)
            run(["iw", "dev", AP_IFACE, "set", "type", "__ap"],
                check=False, quiet=True)
            run(["ip", "link", "set", AP_IFACE, "up"], check=False, quiet=True)
            run(["ip", "addr", "add", f"{commands.BOOTH_IP}/24", "dev", AP_IFACE],
                check=False, quiet=True)
            info = run(["iw", "dev", AP_IFACE, "info"], check=False, quiet=True) or ""
            flags = run(["ip", "-j", "addr", "show", AP_IFACE],
                        check=False, quiet=True) or ""
            if re.search(r"type AP", info) and commands.BOOTH_IP in flags:
                return
            time.sleep(0.5)
        raise RunError(
            "the hotspot interface would not settle in AP mode — NetworkManager "
            "may be fighting us; try: nmcli device set ap0 managed no, then "
            "press Start again")

    def _sta_channel(self) -> int:
        """Channel of the laptop's own Wi-Fi link (to share the radio)."""
        out = run(["iw", "dev", self.wifi, "link"], check=False, quiet=True) or ""
        m = re.search(r"freq:\s*([0-9.]+)", out)
        if not m:
            return 6  # no link info: common 2.4GHz default, honest fallback
        try:
            return commands.freq_to_channel(float(m.group(1)))
        except ValueError:
            return 6

    def _write_hostapd_conf(self, ssid: str, psk: str, channel: int) -> str:
        os.makedirs(settings.CONFIG_DIR, exist_ok=True)
        path = os.path.join(settings.CONFIG_DIR, commands.HOSTAPD_CONF)
        if self.dry:
            print(commands.hostapd_conf_text(ssid, psk, channel))
            return path
        with open(path, "w") as f:
            f.write(commands.hostapd_conf_text(ssid, psk, channel))
        os.chmod(path, 0o600)  # it contains the Wi-Fi password
        return path

    def _ap_exists(self) -> bool:
        return subprocess.run(["ip", "link", "show", AP_IFACE],
                              capture_output=True).returncode == 0

    def _wait_for_hostapd(self, seconds: float = 8.0) -> None:
        deadline = time.time() + seconds
        while time.time() < deadline:
            if os.path.exists(commands.HOSTAPD_PID):
                return
            time.sleep(0.5)
        raise RunError(
            "the hotspot service (hostapd) did not start — check its log with: "
            "sudo journalctl -t hostapd | tail -20")

    def stop(self) -> str:
        """Turn the toll booth off.  Safe to run any time, even after
        a crash — every step tolerates already-being-cleaned-up."""
        for cmd in commands.stop_daemon_cmds():
            run(cmd, dry=self.dry, check=False)
        for cmd in commands.tc_teardown_cmds(AP_IFACE, IFB):
            run(cmd, dry=self.dry, check=False)
        for cmd in commands.nft_teardown_cmds():
            run(cmd, dry=self.dry, check=False)
        run(["ip", "addr", "flush", "dev", AP_IFACE], dry=self.dry, check=False)
        for cmd in commands.ap_del_cmds(AP_IFACE):
            run(cmd, dry=self.dry, check=False)
        # the teardown above deleted the shared firewall table and the
        # shared upload meter; cable mode (if in use) must get its own
        # rules back, or cabled PCs lose internet
        if not self.dry and self._lan_caps_load():
            run_many(commands.tc_init_cmds(self.wifi, IFB), self.dry)
            self.lan_reapply()
        return ("Toll booth stopped. Speed caps and blocks on the hotspot "
                "are gone; devices that were on it will drift back to the "
                "router's Wi-Fi on their own.")

    def is_up(self) -> bool:
        out = run(commands.addr_cmd(AP_IFACE)[0], check=False, quiet=True) or ""
        return bool(parse_addr(out))

    def ap_ip(self) -> str:
        if self.dry:
            return ""
        out = run(commands.addr_cmd(AP_IFACE)[0], check=False, quiet=True) or ""
        return parse_addr(out)

    # -- who is connected ----------------------------------------------------

    def devices(self) -> list:
        """Devices on the hotspot right now: [{ip, mac, name, associated}].

        Three sources, each covering what the others can't see:
        * the Wi-Fi chip's association list — who is *physically*
          connected this second (authoritative, no address though)
        * the address-handout records — which address each hardware
          address was given (phones show up here, not in the
          neighbor table, because the laptop never phones them first)
        * the neighbor table — extra mappings, just in case
        """
        if self.dry:
            return []
        stations = set(
            parse_station_dump(run(commands.station_dump_cmd(AP_IFACE)[0], check=False, quiet=True) or ""))
        neigh = parse_neigh(run(commands.neigh_cmd(AP_IFACE)[0], check=False, quiet=True) or "")
        records = parse_leases_records()
        mac_to_ipname = {}
        for r in records:                      # later records win = latest state
            mac_to_ipname[r["mac"]] = (r["ip"], r["name"])
        for ip, mac in neigh.items():
            mac_to_ipname.setdefault(mac, (ip, ""))

        out, seen = [], set()
        for mac in stations:                   # connected right now
            ip, name = mac_to_ipname.get(mac, ("", ""))
            out.append({"ip": ip, "mac": mac, "name": name, "associated": True})
            seen.add(mac)
        for ip, mac in neigh.items():          # talking, but not associated
            if mac not in seen:
                out.append({"ip": ip, "mac": mac, "name": "",
                            "associated": False})
                seen.add(mac)
        return out

    # -- speed caps ---------------------------------------------------------

    def _caps_load(self) -> dict:
        try:
            with open(CAPS_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _caps_save(self, caps: dict) -> None:
        os.makedirs(settings.CONFIG_DIR, exist_ok=True)
        with open(CAPS_PATH, "w") as f:
            json.dump(caps, f, indent=2)

    def caps(self) -> dict:
        """Current caps: {hardware-address-or-ip: [down_kbit, up_kbit]}."""
        return self._caps_load()

    def _current_ip_for(self, key: str) -> str:
        """Where a capped device lives *right now*.

        Caps prefer to ride on the hardware address (MAC), which never
        changes, while addresses (IPs) can be reissued.  For a MAC key
        we look up its current address in the handout records and the
        neighbor table; an IP key is used as-is.
        """
        if ":" not in key:
            return key
        for r in parse_leases_records():
            if r["mac"] == key and r["ip"]:
                return r["ip"]
        for ip, mac in parse_neigh(
                run(commands.neigh_cmd(AP_IFACE)[0], check=False, quiet=True) or "").items():
            if mac == key:
                return ip
        return ""

    def _apply_caps(self, caps: dict, force: bool = False) -> None:
        """(Re)apply every cap in one sweep, at each device's *current*
        address — the kernel never keeps stale rules this way, and caps
        follow devices even if their address changes.

        `force` re-installs the rules even when nothing moved (needed
        after another feature cleared our traffic filters).
        """
        resolved = {}
        for key, (down, up) in sorted(caps.items()):
            ip = self._current_ip_for(key)
            if ip:
                resolved[ip] = (int(down), int(up))
        if not force and resolved == getattr(self, "_applied_cache", None):
            return                       # nothing moved since last time
        for iface in (AP_IFACE, IFB):
            run(["tc", "filter", "del", "dev", iface, "pref", "1"],
                dry=self.dry, check=False)
        for ip, (down, up) in resolved.items():
            for cmd in commands.tc_limit_cmds(AP_IFACE, ip, down, up, IFB):
                run(cmd, dry=self.dry)
        self._applied_cache = resolved

    def reapply_caps(self, force: bool = False) -> None:
        self._apply_caps(self._caps_load(), force=force)

    def sync_caps(self) -> None:
        """Called from the live loop: re-resolve caps if a device's
        address changed (cheap no-op when nothing moved)."""
        if self._caps_load():
            self._apply_caps(self._caps_load())

    def cap(self, ip: str, down: int, up: int, mac: str = "") -> str:
        """Cap a device. Speeds are kilobits/second (kbit/s);
        100 KB/s (kilobytes) = 800 kbit.  When the hardware address is
        known the cap rides on it, so it survives address changes."""
        if down <= 0 or up <= 0:
            raise RunError("speeds must be positive numbers")
        if not ip:
            raise RunError("that device has no network address yet — give it "
                           "a second, then try again")
        key = mac.lower() if mac else ip
        human = speeds.human_speed(down, up)
        if self.dry:
            return f"(dry run) would cap {ip} at {human}"
        caps = self._caps_load()
        caps[key] = [down, up]
        self._caps_save(caps)
        self._apply_caps(caps)
        return (f"capped {ip} at {human} "
                "(applies while the device is on this hotspot)")

    def uncap(self, ip: str, mac: str = "") -> str:
        if self.dry:
            return f"(dry run) would remove the cap for {ip}"
        caps = self._caps_load()
        for key in filter(None, (mac.lower(), ip)):
            if key in caps:
                del caps[key]
                self._caps_save(caps)
                self._apply_caps(caps)
                return f"speed cap removed for {ip}"
        return f"{ip} had no cap"

    # -- blocking ---------------------------------------------------------------

    def blocked(self) -> list:
        """Addresses currently cut off, straight from the firewall."""
        out = run(commands.nft_list_blocked_cmd()[0], check=False, quiet=True) or ""
        found = []
        try:
            for item in json.loads(out).get("nftables", []):
                entries = item.get("set", {}).get("elem", [])
                for e in entries:
                    if isinstance(e, str):
                        found.append(e)
                    elif isinstance(e, dict):
                        val = e.get("val", e)
                        if isinstance(val, dict):
                            found.append(val.get("addr", ""))
                        else:
                            found.append(str(val))
        except (json.JSONDecodeError, AttributeError):
            pass
        return sorted({a for a in found if a},
                      key=lambda a: tuple(int(x) for x in a.split(".")))

    # -- LAN toll-booth mode (cabled PCs) -------------------------------

    LAN_CAPS_PATH = os.path.join(settings.CONFIG_DIR, "lan_caps.json")

    def lan_up(self, alias_ip: str = "") -> str:
        """Start metering mode for cabled PCs (no hotspot involved).

        The laptop keeps its normal connection and wears one extra,
        fixed address (an 'alias', default .253) that PCs can be pointed
        at as their gateway.  A small script on each PC does that part.
        """
        if not self.dry and not sudo_available():
            raise RunError("admin rights are needed — run `sudo -v` first")
        alias = alias_ip or self.cfg.get("lan_alias_ip") or self._free_alias()
        if not self.dry:
            # remember the address so "Cable mode" knows it is on, and so
            # the same address is reused next time (the PC's script
            # expects it never to move)
            cfg = settings.load()
            cfg["lan_alias_ip"] = alias
            settings.save(cfg)
            self.cfg["lan_alias_ip"] = alias
        run_many(commands.forwarding_on_cmds(), self.dry)
        for cmd in commands.lan_alias_cmds(self.wifi, alias):
            run(cmd, dry=self.dry, check=False)
        # meters on the laptop's usual network card; the default bucket
        # is effectively unrestricted, so the laptop's own traffic is
        # never slowed — only filtered flows (the PCs) get buckets
        for cmd in commands.tc_init_cmds(self.wifi, IFB):
            run(cmd, dry=self.dry)
        if not self.dry:
            self.lan_reapply()
        return (f"Cable mode is on (the laptop now answers on {alias} too). "
                f"On each Windows PC, open PowerShell as administrator and run:\n"
                f"  powershell -ExecutionPolicy Bypass -File point-to-laptop.ps1 "
                f"-Action install -Gateway {alias}\n"
                f"(that script switches the PC back to the router by itself "
                f"whenever this laptop is off.)\n"
                f"Then type the PC's address in the Cable-PC box and press "
                f"Cap PC to choose its speed.")

    def _free_alias(self) -> str:
        """Pick an address at the top of our own street that nobody answers on."""
        out = run(["ip", "-4", "-j", "addr", "show", "dev", self.wifi],
                  check=False, quiet=True) or ""
        m = re.search(r'"local": "([0-9.]+)"', out)
        if m:
            base = m.group(1).rsplit(".", 1)[0]
        else:
            net = ipaddress.ip_network(scanner.autodetect_subnet(), strict=False)
            parts = str(net.network_address).split(".")
            base = ".".join(parts[:3]) if len(parts) == 4 else "192.168.1"
        for last in ("253", "252", "251", "250"):
            candidate = f"{base}.{last}"
            probe = subprocess.run(["ping", "-c", "1", "-W", "1", candidate],
                                   capture_output=True)
            if probe.returncode != 0 and self._addr_unused(candidate):
                return candidate
        return f"{base}.253"

    def _addr_unused(self, ip: str) -> bool:
        out = run(["ip", "-4", "-j", "addr"], check=False, quiet=True) or ""
        return f'"{ip}"' not in out

    def lan_alias(self) -> str:
        """The alias address currently worn, if any (for display)."""
        if self.dry:
            return ""
        wanted = self.cfg.get("lan_alias_ip") or ""
        if not wanted:
            return ""
        out = run(["ip", "-4", "-j", "addr", "show", "dev", self.wifi],
                  check=False, quiet=True) or ""
        return wanted if f'"{wanted}"' in out else ""

    def _lan_caps_load(self) -> dict:
        try:
            with open(self.LAN_CAPS_PATH) as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def _lan_caps_save(self, caps: dict) -> None:
        os.makedirs(settings.CONFIG_DIR, exist_ok=True)
        with open(self.LAN_CAPS_PATH, "w") as f:
            json.dump(caps, f, indent=2)

    def lan_caps(self) -> dict:
        return self._lan_caps_load()

    def lan_reapply(self) -> None:
        """(Re)apply every LAN cap: meters + address-sharing + buckets."""
        caps = self._lan_caps_load()
        local_subnet = scanner.autodetect_subnet()
        # one clean sharing chain, then one rule per capped PC
        for cmd in commands.nft_lan_prepare_cmds(commands.LAN_NAT_CHAIN):
            run(cmd, dry=self.dry, check=False)
        for key, (down, up) in sorted(caps.items()):
            ip = key if ":" not in key else self._current_ip_for(key)
            if not ip:
                continue
            for cmd in commands.lan_nat_cmds(ip, local_subnet):
                run(cmd, dry=self.dry, check=False)
            for cmd in commands.tc_limit_cmds(self.wifi, ip, int(down), int(up), IFB):
                run(cmd, dry=self.dry)

    def lan_cap(self, ip: str, down: int, up: int) -> str:
        """Cap a cabled PC: down/up in kbit/s (100 KB/s = 800 kbit)."""
        if not ip:
            raise RunError("type the PC's address in the Cable-PC box first")
        if self.dry:
            return (f"(dry run) would cap {ip} at {speeds.human_speed(down, up)} "
                    f"and share the laptop's connection with it")
        caps = self._lan_caps_load()
        caps[ip] = [down, up]
        self._lan_caps_save(caps)
        self.lan_reapply()
        return (f"capped {ip} at {speeds.human_speed(down, up)}. Both directions "
                "are metered here — as soon as the PC points its gateway "
                f"at this laptop (see the note printed when Cable mode was turned on).")

    def lan_uncap(self, ip: str) -> str:
        if self.dry:
            return f"(dry run) would remove the LAN cap for {ip}"
        caps = self._lan_caps_load()
        if ip not in caps:
            return f"{ip} had no LAN cap"
        del caps[ip]
        self._lan_caps_save(caps)
        # drop every meter filter, this PC's buckets, then rebuild the
        # remaining rules — deleting the class alone would leave this
        # PC's filter pointing at nothing (which means: no internet)
        for iface in (self.wifi, IFB):
            run(["tc", "filter", "del", "dev", iface, "pref", "1"],
                dry=self.dry, check=False)
        for cmd in commands.tc_unlimit_cmds(self.wifi, ip, IFB):
            run(cmd, dry=self.dry, check=False)
        self.lan_reapply()
        if self.is_up():
            self.reapply_caps(force=True)     # ifb0 filters are shared
        # the address-sharing rule for it can safely stay; it only acts
        # when the PC actually sends traffic through us
        return f"LAN speed cap removed for {ip}"

    def lan_down(self) -> str:
        """Stop LAN metering.  PCs fall back to the router on their own
        (their script notices the laptop is gone and switches back)."""
        alias = self.cfg.get("lan_alias_ip") or ""
        if alias:
            for cmd in commands.lan_alias_del_cmds(self.wifi, alias):
                run(cmd, dry=self.dry, check=False)
        for cmd in (["tc", "qdisc", "del", "dev", self.wifi, "root"],
                    ["tc", "qdisc", "del", "dev", self.wifi, "ingress"]):
            run(cmd, dry=self.dry, check=False)
        if not self.dry and alias:
            cfg = settings.load()
            cfg["lan_alias_ip"] = ""
            settings.save(cfg)
            self.cfg["lan_alias_ip"] = ""
        # ifb0 is shared with the Wi-Fi booth: put its caps back if any
        if self.is_up():
            self.reapply_caps(force=True)
        return ("LAN toll booth off. Meters removed; PCs will drift back "
                "to the router (their script does it automatically when "
                "this laptop stops answering).")

    def block(self, ip: str) -> str:
        run_many(commands.nft_block_cmds(ip), self.dry)
        return (f"blocked {ip} on this hotspot — its internet is cut until "
                "you press Unblock. (A device can still leave this Wi-Fi and "
                "rejoin the router's; blocking there needs the router's own "
                "parental control.)")

    def unblock(self, ip: str) -> str:
        run_many(commands.nft_unblock_cmds(ip), self.dry)
        return f"unblocked {ip} on this hotspot"
