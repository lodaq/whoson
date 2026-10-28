"""Small helpers the window uses: refusing dangerous targets and
checking that the computer has everything it needs.

No windows and no screens in here — just plain functions, so they are
easy to test.
"""

import json
import shutil
import subprocess

import router as router_mod
import settings
import tollbooth
from tollbooth import TollBooth


def validate_wifi(name: str, psk: str) -> tuple:
    """Check the shared Wi-Fi's name and password, returning them cleaned.

    Raises ValueError with a friendly message when something wouldn't
    work — or would break the hotspot's configuration file.
    """
    name = name.strip()
    if not name:
        raise ValueError("give your Wi-Fi a name first")
    if len(name.encode("utf-8")) > 32:
        raise ValueError("Wi-Fi names can be at most 32 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in name):
        raise ValueError("the Wi-Fi name can't contain line breaks or "
                         "control characters")
    if not psk:
        raise ValueError("type a Wi-Fi password first")
    if len(psk) < 8:
        raise ValueError("the Wi-Fi password needs at least 8 characters")
    if len(psk) > 63:
        raise ValueError("the Wi-Fi password can be at most 63 characters")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in psk):
        raise ValueError("the Wi-Fi password can't contain line breaks or "
                         "control characters")
    return name, psk


def guard_protected(booth: TollBooth, ip: str) -> None:
    """Refuse to cap or cut the laptop itself or the router."""
    if ip == booth.cfg.get("router_ip"):
        raise ValueError("that's the router — cutting it would cut the whole "
                         "house off, so whoson refuses")
    if ip == booth.ap_ip() or ip.startswith("127."):
        raise ValueError("that's this laptop — refusing")
    try:
        addr = subprocess.run(["ip", "-4", "-j", "addr"],
                              capture_output=True, text=True, timeout=5).stdout
        for entry in json.loads(addr):
            for info in entry.get("addr_info", []):
                if info.get("local") == ip:
                    raise ValueError("that's one of this laptop's own "
                                     "addresses — refusing")
    except (json.JSONDecodeError, FileNotFoundError):
        pass


def doctor_checks() -> list:
    """Everything the toll booth needs, as rows: (name, ok?, note)."""
    rows = []
    tools = [("nmcli", "network settings (kept away from our hotspot)"),
             ("hostapd", "runs the hotspot Wi-Fi itself"),
             ("dnsmasq", "hands out addresses to devices that join"),
             ("tc", "the speed-limit meter"),
             ("nft", "the on/off switch for the internet (firewall)"),
             ("iw", "talks to the Wi-Fi chip")]
    for tool, why in tools:
        have = shutil.which(tool) is not None
        rows.append((tool, have, why))
    sudo_ok = tollbooth.sudo_available()
    rows.append(("sudo", sudo_ok,
                 "admin rights (run `sudo -v` in a terminal if missing)"))
    try:
        iw = subprocess.run(["iw", "list"], capture_output=True, text=True,
                            timeout=5).stdout
        combo_at = iw.find("valid interface combinations")
        combos = iw[combo_at:combo_at + 260] if combo_at >= 0 else ""
        ap_ok = "AP" in combos and "managed" in combos
    except (FileNotFoundError, subprocess.TimeoutExpired):
        ap_ok = False
    rows.append(("wifi", ap_ok, "chip can do my Wi-Fi + router Wi-Fi at once"))
    cfg = settings.load()
    try:
        import urllib.request
        req = urllib.request.Request(f"https://{cfg['router_ip']}/")
        opener = urllib.request.build_opener(urllib.request.HTTPSHandler(
            context=router_mod.legacy_ssl_context()))
        with opener.open(req, timeout=5) as resp:
            router_ok = resp.status == 200
    except Exception:
        router_ok = False
    rows.append(("router", router_ok,
                 f"{cfg['router_ip']} answered (router listing may still work "
                 "via door-knocking)"))
    return rows
