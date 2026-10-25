"""Settings storage — one small file, readable only by you.

Kept at ~/.config/whoson/config.json with permissions 600 (owner
read/write only).  It may contain your router's admin username and
password; those are only ever sent to the router itself, on your own
network — never anywhere else.
"""

import json
import os
import stat

CONFIG_DIR = os.path.expanduser("~/.config/whoson")
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "router_ip": "192.168.1.1",
    "router_user": "admin",
    "router_pass": None,      # asked on first run, then stored
    "hotspot_ssid": "whoson",
    "hotspot_psk": None,      # generated on first `start` if missing
}


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as f:
            cfg.update(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save(cfg: dict) -> None:
    os.makedirs(CONFIG_DIR, exist_ok=True)
    # create (or rewrite) with owner-only permissions before writing
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w") as f:
        json.dump(cfg, f, indent=2)
        f.write("\n")
    os.chmod(CONFIG_PATH, stat.S_IRUSR | stat.S_IWUSR)  # also fixes pre-existing files


def forget_password() -> None:
    cfg = load()
    cfg["router_pass"] = None
    save(cfg)
