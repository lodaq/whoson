"""whoson — who's on my network?

Commands, in everyday words:

  whoson                 live table of everyone online (Ctrl-C to exit)
  whoson once            one snapshot, then exit
  whoson --json          one snapshot as JSON (for scripts)
  whoson start           turn on the toll-booth Wi-Fi (needs admin rights)
  whoson stop            turn it off (safe any time)
  whoson limit PHONE 5/1 cap a hotspot device at 5 Mbps down / 1 up
  whoson unlimit PHONE   remove the cap
  whoson block PHONE     cut a hotspot device's internet
  whoson unblock PHONE   restore it
  whoson doctor          check everything this tool relies on
  whoson forget-password remove the stored router password

PHONE above can be an IP (10.42.0.123), a MAC (aa:bb:cc:...), or the
start of a device name ("pho" for "phone-of-seba").
"""

import argparse
import getpass
import json
import sys

from . import config, gateway as gwmod, live, router as routermod, scanner, vendor
from .gateway import Gateway, RunError


# ---------------------------------------------------------------------------
# speed arguments: "5" or "5/1" (Mbps) — but also everyday units:
# "100kb/20kb" (kilobytes per second, as download speeds display),
# "0.8/0.16" (fractional Mbps), "10mb/2mb" (megabytes), "500k/100k" (kilobits)
# ---------------------------------------------------------------------------

import re as _re


def parse_speed(speed: str):
    """'down/up' or a single value -> (down_kbit, up_kbit).

    Units (case-insensitive): none or m = megabits; mb = megabytes;
    k = kilobits; kb = kilobytes.  There are 8 bits in a byte.
    """
    def to_kbit(side: str) -> int:
        m = _re.fullmatch(r"\s*([0-9.]+)\s*([a-zA-Z]*)\s*", side)
        if not m:
            raise ValueError(side)
        value, unit = float(m.group(1)), m.group(2).lower()
        table = {"": 1000, "m": 1000, "mbit": 1000,          # megabits
                 "mb": 8000, "mbyte": 8000, "mbytes": 8000,  # megabytes
                 "k": 1, "kbit": 1,                          # kilobits
                 "kb": 8, "kbyte": 8, "kbytes": 8}           # kilobytes
        if unit not in table:
            raise ValueError(unit)
        return int(value * table[unit])

    if "/" in speed:
        down_s, up_s = speed.split("/", 1)
    else:
        down_s = up_s = speed

    try:
        down, up = to_kbit(down_s), to_kbit(up_s)
    except ValueError as e:
        _fail(f"couldn't understand the speed '{speed}' ({e}) — examples: "
              f"5/1 (Mbps), 0.8/0.16, 100kb/20kb (kilobytes/s), 500k/100k (kilobits/s)")
    if down <= 0 or up <= 0:
        _fail("speeds must be positive — examples: 5/1, 100kb/20kb")
    return down, up


def _fail(msg: str) -> "None":
    print(f"whoson: {msg}", file=sys.stderr)
    raise SystemExit(1)


# ---------------------------------------------------------------------------
# resolving "which device did you mean"
# ---------------------------------------------------------------------------

def _candidates(gateway: Gateway):
    """Everything we can currently see, for name matching."""
    items = list(gateway.clients())
    return items


def resolve_target(gateway: Gateway, text: str) -> dict:
    """Turn '10.42.0.5' / 'aa:bb:cc:..' / 'name-prefix' into a client."""
    text_l = text.strip().lower()
    items = _candidates(gateway)
    if not items:
        _fail("no devices are on the hotspot right now — have them join the "
              f"'{gateway.cfg.get('hotspot_ssid', 'whoson')}' Wi-Fi first "
              "(whoson start), or use the device's address once it's online")
    for c in items:                                   # exact IP
        if c["ip"] == text_l:
            return c
    for c in items:                                   # exact MAC
        if c["mac"].lower() == text_l:
            return c
    matches = [c for c in items
               if c.get("name", "").lower().startswith(text_l)
               or vendor.vendor_of(c["mac"]).lower().startswith(text_l)]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        listing = "\n".join(f"  {c['ip']:<15} {c['mac']}  {c.get('name') or '-'}" for c in matches)
        _fail(f"'{text}' matches more than one device — be more specific:\n{listing}")
    listing = "\n".join(f"  {c['ip']:<15} {c['mac']}  {c.get('name') or '-'}" for c in items)
    _fail(f"no device matches '{text}'. Current hotspot devices:\n{listing}")


def _guard_protected(gateway: Gateway, ip: str) -> None:
    """Refuse to shoot ourselves in the foot."""
    cfg = gateway.cfg
    if ip == cfg.get("router_ip"):
        _fail("that's your router — blocking it would cut the whole house "
              "off, so whoson refuses")
    if ip == gateway.ap_ip() or ip.startswith("127."):
        _fail("that's this laptop (the toll booth itself) — refusing")
    import subprocess
    addr = subprocess.run(["ip", "-4", "-j", "addr"], capture_output=True, text=True).stdout
    try:
        for entry in json.loads(addr):
            for info in entry.get("addr_info", []):
                if info.get("local") == ip:
                    _fail("that's one of this laptop's own addresses — refusing")
    except json.JSONDecodeError:
        pass


# ---------------------------------------------------------------------------
# router session handling
# ---------------------------------------------------------------------------

def _router_client(args, cfg, interactive=True):
    """Build a logged-in router client, or None if we shouldn't/can't."""
    if getattr(args, "scan_only", False):
        return None
    saved = bool(cfg.get("router_pass"))
    password = cfg.get("router_pass") or getattr(args, "router_pass", None)
    if not password:
        if not sys.stdin.isatty():
            return None  # non-interactive (scripts): just skip the router
        if not interactive:
            return None
        print(f"Asking the router ({cfg['router_ip']}) for its device list.")
        print(f"Username [{cfg['router_user']}]: ", end="", flush=True)
        user = input().strip() or cfg["router_user"]
        password = getpass.getpass("Router password (typing hidden): ")
        cfg["router_user"], cfg["router_pass"] = user, password
        try:
            print("Save for next time? [Y/n]: ", end="", flush=True)
            if input().strip().lower() in ("", "y", "yes"):
                config.save(cfg)
                print(f"saved to {config.CONFIG_PATH} (owner-only permissions)")
        except EOFError:
            pass
    try:
        client = routermod.RouterClient(cfg["router_ip"],
                                        cfg["router_user"], password)
        client.login()
        return client
    except routermod.RouterError as e:
        if saved:
            # a stored password that no longer works: forget it, so the
            # next run asks instead of silently failing forever
            config.forget_password()
        print(f"whoson: {e} — continuing without the router "
              "(door-knocking scanner takes over)", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# commands
# ---------------------------------------------------------------------------

def cmd_start(args):
    cfg = config.load()
    if args.password:
        if len(args.password) < 8:
            _fail("the hotspot password must be at least 8 characters")
        cfg["hotspot_psk"] = args.password
        cfg["hotspot_ssid"] = args.ssid or cfg["hotspot_ssid"]
        config.save(cfg)
    elif not cfg.get("hotspot_psk") and not args.dry_run:
        import secrets
        psk = secrets.token_urlsafe(12)
        cfg["hotspot_psk"] = psk
        cfg["hotspot_ssid"] = args.ssid or cfg["hotspot_ssid"]
        config.save(cfg)
        print(f"Generated a hotspot password (saved in {config.CONFIG_PATH}): {psk}")
        print("Change it any time with: whoson start --password <new>\n")
    g = Gateway(cfg, dry=args.dry_run)
    print(g.start())


def cmd_stop(args):
    g = Gateway(config.load(), dry=args.dry_run)
    print(g.stop())


def cmd_limit(args):
    g = Gateway(config.load(), dry=args.dry_run)
    down, up = parse_speed(args.speed)
    if not g.is_up() and not args.dry_run:
        _fail("the hotspot isn't running — start it with `whoson start` first")

    if args.device.lower() == "all":
        return _limit_all(g, args, down, up)

    target = resolve_target(g, args.device) if not args.dry_run else {"ip": args.device, "mac": "", "name": ""}
    if not args.dry_run:
        _guard_protected(g, target["ip"])
    print(g.limit(target["ip"], down, up, mac=target.get("mac", "")))


def _limit_all(g, args, down, up):
    """Cap every device on the hotspot, minus any --except ones.

    The laptop and the router are always skipped — capping them would
    strangle everyone including you.
    """
    # listing is read-only, so even a dry run matches against the real,
    # current device list (g itself is dry and would see nothing)
    reader = Gateway(config.load()) if g.dry else g
    clients = reader.clients()
    if not clients and not args.dry_run:
        _fail("no devices are on the hotspot right now — nothing to cap")
    except_keys = set()
    for token in (getattr(args, "except_", "") or "").split(","):
        token = token.strip().lower()
        if not token:
            continue
        matches = [c for c in clients
                   if c["ip"].lower() == token or c["mac"].lower() == token
                   or c.get("name", "").lower().startswith(token)
                   or vendor.vendor_of(c["mac"]).lower().startswith(token)]
        if not matches:
            _fail(f"--except '{token}': no matching device — the hotspot has: "
                  + ", ".join(c.get("name") or c["ip"] for c in clients))
        except_keys.update(m["mac"] for m in matches)

    skipped, capped = [], []
    for c in clients:
        if not c["ip"]:
            skipped.append(f"{c.get('name') or c['mac']} (no address yet)")
            continue
        if c["mac"] in except_keys:
            continue
        try:
            _guard_protected(g, c["ip"])
        except SystemExit:
            skipped.append(f"{c['ip']} (this laptop or the router — never capped)")
            continue
        g.limit(c["ip"], down, up, mac=c["mac"])
        capped.append(f"{c.get('name') or c['ip']} ({c['ip']})")
    if args.dry_run:
        print("(dry run) would cap every hotspot device at "
              f"{down / 8:.0f} KB/s down / {up / 8:.0f} KB/s up")
        return
    for line in capped:
        print(f"  capped {line}")
    for line in skipped:
        print(f"  skipped {line}")
    print(f"{len(capped)} device(s) capped; the cap follows each device even "
          "if its address changes.")


def cmd_unlimit(args):
    g = Gateway(config.load(), dry=args.dry_run)
    if args.device.lower() == "all":
        limits = g.limits()
        if not limits:
            print("no devices are capped")
            return
        for key in list(limits):
            print(g.unlimit(key, mac=key if ":" in key else ""))
        return
    target = resolve_target(g, args.device) if not args.dry_run else {"ip": args.device}
    print(g.unlimit(target["ip"], mac=target.get("mac", "")))


def cmd_block(args):
    g = Gateway(config.load(), dry=args.dry_run)
    if not g.is_up() and not args.dry_run:
        _fail("the hotspot isn't running — start it with `whoson start` first")
    target = resolve_target(g, args.device) if not args.dry_run else {"ip": args.device}
    if not args.dry_run:
        _guard_protected(g, target["ip"])
    print(g.block(target["ip"]))


def cmd_unblock(args):
    g = Gateway(config.load(), dry=args.dry_run)
    target = resolve_target(g, args.device) if not args.dry_run else {"ip": args.device}
    print(g.unblock(target["ip"]))


def cmd_doctor(args):
    import subprocess
    print("Checking what whoson depends on…\n")
    ok = True
    for tool, why in [("nmcli", "network settings (kept away from our hotspot)"),
                      ("hostapd", "runs the hotspot Wi-Fi itself"),
                      ("dnsmasq", "hands out addresses to hotspot devices"),
                      ("tc", "the speed-limit meter"),
                      ("nft", "the firewall (blocking)"),
                      ("iw", "talks to the Wi-Fi chip")]:
        have = subprocess.run(["sh", "-c", f"command -v {tool}"],
                              capture_output=True).returncode == 0
        print(f"  [{'ok' if have else 'MISSING'}] {tool:<8} — {why}")
        ok &= have
    sudo_ok = gwmod.sudo_available()
    print(f"  [{'ok' if sudo_ok else 'NO '}] sudo     — admin rights for the above "
          + ("(passwordless on this machine)" if sudo_ok else "(needs a password: run `sudo -v` first)"))
    iw = subprocess.run(["iw", "list"], capture_output=True, text=True).stdout
    combos = iw[iw.find("valid interface combinations"):
                iw.find("valid interface combinations") + 260] if "valid interface combinations" in iw else ""
    ap_ok = "AP" in combos and "managed" in combos
    print(f"  [{'ok' if ap_ok else 'NO '}] wifi     — chip can do hotspot + "
          f"router connection at once{' (one shared channel)' if ap_ok else ''}")
    print()
    cfg = config.load()
    import urllib.request
    router_ok = False
    try:
        req = urllib.request.Request(f"https://{cfg['router_ip']}/")
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=routermod.legacy_ssl_context()))
        with opener.open(req, timeout=5) as resp:
            router_ok = resp.status == 200
    except Exception:
        router_ok = False
    print(f"  [{'ok' if router_ok else 'NO '}] router   — {cfg['router_ip']} answered "
          "(the old-encryption workaround is applied)")
    print("\nEverything looks good." if ok and ap_ok and router_ok
          else "\nSome pieces are missing — see the lines marked MISSING above.")


def cmd_forget_password(args):
    config.forget_password()
    print(f"router password removed from {config.CONFIG_PATH}")


def cmd_list(args):
    cfg = config.load()
    g = Gateway(cfg)
    router_client = _router_client(args, cfg, interactive=not args.json)
    poller = live.RouterPoller(router_client) if router_client else None
    try:
        live.watch(g, poller, once=args.once or bool(args.json),
                   json_mode=bool(args.json))
    except KeyboardInterrupt:
        print("\nbye")


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="whoson",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--json", action="store_true",
                   help="one snapshot as JSON (for scripts)")
    p.add_argument("--once", action="store_true",
                   help="one snapshot, then exit (instead of live view)")
    p.add_argument("--scan", dest="scan_only", action="store_true",
                   help="skip the router; use the door-knocking scanner only")
    p.add_argument("--dry-run", action="store_true",
                   help="print the exact system commands instead of running them")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--dry-run", action="store_true",
                        help="print the exact system commands instead of running them")
    sub = p.add_subparsers(dest="cmd")

    sp = sub.add_parser("start", parents=[common],
                        help="turn on the toll-booth Wi-Fi hotspot")
    sp.add_argument("--password", help="Wi-Fi password for the hotspot (8+ characters)")
    sp.add_argument("--ssid", help="network name for the hotspot (default: whoson)")
    sp.set_defaults(func=cmd_start)

    sp = sub.add_parser("stop", parents=[common], help="turn the hotspot off (safe any time)")
    sp.set_defaults(func=cmd_stop)

    sp = sub.add_parser("limit", parents=[common], help="cap a hotspot device: whoson limit PHONE 5/1")
    sp.add_argument("device", help="IP, MAC, or name prefix of the device")
    sp.add_argument("speed",
                    help="5/1 (Mbps down/up), 0.8/0.16, 100kb/20kb (kilobytes/s, "
                         "as downloads display), or 500k/100k (kilobits/s)")
    sp.add_argument("--except", dest="except_", metavar="DEVICES",
                    help="with 'all': skip these devices (comma-separated "
                         "names/addresses), e.g. --except opp,laptop")
    sp.set_defaults(func=cmd_limit)

    sp = sub.add_parser("unlimit", parents=[common], help="remove a device's speed cap")
    sp.add_argument("device")
    sp.set_defaults(func=cmd_unlimit)

    sp = sub.add_parser("block", parents=[common], help="cut a hotspot device's internet")
    sp.add_argument("device")
    sp.set_defaults(func=cmd_block)

    sp = sub.add_parser("unblock", parents=[common], help="restore a blocked device's internet")
    sp.add_argument("device")
    sp.set_defaults(func=cmd_unblock)

    sp = sub.add_parser("doctor", parents=[common], help="check everything whoson depends on")
    sp.set_defaults(func=cmd_doctor)

    sp = sub.add_parser("forget-password", parents=[common], help="remove the stored router password")
    sp.set_defaults(func=cmd_forget_password)

    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None):
        args.func(args)
        return
    cmd_list(args)


if __name__ == "__main__":
    main()
