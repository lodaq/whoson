# whoson — who's on my network, and how fast are they allowed to go?

A small toolbox for home-network visibility and control:

* **`whoson`** (Linux laptop — the main tool): shows every device on
  your network **live**, and — for devices you route through the
  laptop's own Wi-Fi — enforces **exact per-device speed caps** and
  **internet blocking**.
* **`limit-internet.ps1`** (Windows 10/11 — companion script): lets a
  Windows PC cap **its own** internet speed, in the background, from
  boot.

Built and battle-tested on **Arch Linux** against a **Huawei HG630 V2**
router (WE / Telecom Egypt firmware) and an **Intel AX200** Wi-Fi chip;
the Windows script targets stock Windows 10 and 11 with nothing
installed.

---

## What can I do with this? (use cases)

* **"Who is on my Wi-Fi right now?"** — run `whoson` and watch the
  live table: family phones, TVs, laptops, mystery gadgets — with
  maker names where known, appearing and disappearing in real time.
* **"That phone is eating all the bandwidth."** — point it once at the
  toll-booth Wi-Fi, then `whoson limit phone 100kb/20kb`. Exact caps,
  both directions, verified against the kernel's own counters.
* **"Bedtime means no internet."** — `whoson block tablet` cuts a
  device off; `whoson unblock tablet` restores it.
* **"Slow down every device on the toll booth except mine."** —
  `whoson limit all 50kb/10kb --except mine`.
* **"The cabled PC in the other room hogs everything."** — run the
  Windows script on that PC (self-limits), or route the PC through
  the laptop with a ~$10 USB ethernet adapter (exact caps, same as
  the phone gets).
* **"Is a stranger freeloading on my router?"** — the live table
  shows every device, flagged by which network it's on; the
  door-knocking scanner works on *any* router, no password needed.
* **"I want real enforcement, not suggestions."** — change the
  router's Wi-Fi password so the toll booth is the only door, or
  cable the laptop to the router and switch the router's Wi-Fi off.

---

## Installation

### `whoson` — Linux (main tool)

Needs Python 3.10+ and standard system tools. Per-distro commands:

**Arch Linux (tested here):**
```sh
sudo pacman -S --noconfirm python-pipx networkmanager iproute2 nftables iw dnsmasq hostapd
```

**Debian / Ubuntu (same tools, different package names — untested):**
```sh
sudo apt install python3 pipx network-manager iproute2 nftables iw dnsmasq hostapd
```

**Fedora (untested):**
```sh
sudo dnf install python3-pipx NetworkManager iproute nftables iw dnsmasq hostapd
```

Then install the command (into its own tidy spot, no venv fiddling):
```sh
pipx install /path/to/selfish        # gives you the `whoson` command
```
or run straight from the repo with no install at all:
```sh
python3 -m whoson.cli --help
```

Two requirements worth checking first — the `whoson doctor` command
checks both for you:
* **admin rights via sudo** — speed limits and blocking change how
  the laptop routes traffic; Linux only lets the admin do that.
* **a Wi-Fi chip that can run a hotspot while connected to your
  router** — most Intel laptop chips can; `iw list` shows it.

### `limit-internet.ps1` — Windows 10/11 (companion script)

No installation: copy the one file (`windows/limit-internet.ps1`)
onto the PC (e.g. `C:\whoson\`), open an **admin** terminal
(right-click Start → *Terminal (Admin)* on Windows 11 /
*Windows PowerShell (Admin)* on Windows 10) and run:

```powershell
powershell -ExecutionPolicy Bypass -File C:\whoson\limit-internet.ps1 -Action install
```

If you run it without admin rights, the script offers to relaunch
itself with a UAC prompt — just click Yes. The other actions
(`status`, `remove`) and the honest accuracy notes are in the
*Usage — Windows* section below.

### Not supported (honestly)

* **macOS** — the tool leans on Linux's traffic meter and firewall
  (tc / nftables), which macOS doesn't have. No port planned.
* **Speed-limiting devices that stay on your router's own Wi-Fi** —
  no software on any computer can do that, on any OS; only the path a
  device's traffic takes can be throttled (that's what the toll booth
  is). Your HG630 V2's firmware has no per-device QoS.
* **Router-login integration beyond this router family** — the login
  protocol was reverse-engineered from the HG630 V2's own code. On
  any other router, `whoson` simply uses the scanner instead
  (listing works everywhere; no credentials needed).

---

## Usage — Linux (`whoson`)

### Seeing who's online

```
whoson                 # live table (Ctrl-C to exit)
whoson once            # one snapshot
whoson --json          # one snapshot as JSON (for scripts)
whoson --scan          # listing only, door-knocking (any router, no login)
whoson doctor          # check every dependency
```

### The toll booth (speed limits + blocking)

```
whoson start                       # turn on the toll-booth Wi-Fi (password shown)
whoson limit PHONE 100kb/20kb      # cap a device: 100 KB/s down, 20 KB/s up
whoson limit all 50kb/10kb --except mine    # cap everyone else
whoson unlimit PHONE               # ...or: whoson unlimit all
whoson block PHONE                 # cut a device's internet
whoson unblock PHONE
whoson stop                        # toll booth off (safe any time)
```

`PHONE` can be an address (`10.42.0.123`), a hardware address
(`aa:bb:cc:dd:ee:ff`), or the start of a device's name (`opp` for
"OPPO-A5-2020"). Caps ride on the **hardware address**, so they
survive address changes and reconnects. Speed units: `5/1` (Mbps),
`0.8/0.16` (fractional Mbps), `100kb/20kb` (kilobytes/s — how
downloads display), `10mb/2mb` (megabytes/s).

### The live table

```
NAME           IP               MAC                MAKER            FLAGS
------------------------------------------------------------------------------
OPPO-A5-2020   10.42.0.176      52:90:b3:96:8a:29  Private address  📶 100KB/s↓/20KB/s↑
living-room-tv 192.168.1.30     60:6b:bd:11:22:33  LG
```

* 📶 = on the toll booth (cappable, blockable) · no flag = on the router
* `100KB/s↓/20KB/s↑` = active cap · ⛔ = internet cut
* "Private address" = a phone hiding behind a randomized hardware
  address (its choice, by design)
* toll-booth devices update within seconds; router-side devices
  refresh every ~12 s and may lag a little

### How it all fits together

```
        devices on the TOLL-BOOTH Wi-Fi              everything else
        (capped, blockable, instant list)            (listed only)
                    │                                      │
   phone ──▶ ┌──────▼──────────────────────────────────────▼─────┐
             │  your laptop: speed meter (tc) + firewall (nft)    │──▶ router ──▶ internet
             └────────────────────────────────────────────────────┘
```

Only a device's traffic *path* can throttle it — that's why capped
devices must sit on the toll booth, and why the table always says
which side a device is on.

### Credentials & privacy

The router password (if you enable router-side listing) is stored in
`~/.config/whoson/config.json` with owner-only permissions and is
sent to your router only. `whoson forget-password` removes it. The
toll-booth Wi-Fi password lives in the same file. Honest status
today: the router login protocol is verified working, but the exact
device-list page in this firmware is still being discovered — until
then the scanner covers router-side listing automatically.

## Usage — Windows 10/11 (`limit-internet.ps1`)

Three actions, all run from an admin terminal (see Installation):

```powershell
powershell -ExecutionPolicy Bypass -File C:\whoson\limit-internet.ps1 -Action install
powershell -ExecutionPolicy Bypass -File C:\whoson\limit-internet.ps1 -Action status
powershell -ExecutionPolicy Bypass -File C:\whoson\limit-internet.ps1 -Action remove
```

* **install** (default) — caps this PC now and forever, invisibly:
  upload **exactly** at 5 KB/s, download **approximately** at ~50 KB/s.
  Change the numbers any time:
  `... -Action install -DownloadKB 30 -UploadKB 3`.
* **status** — shows every enforced piece and its current setting.
* **remove** — full undo; the PC returns to stock full speed.

### How the Windows cap works — three levers, plainly

1. **Upload cap (exact).** Windows' built-in traffic meter (a "QoS
   policy") holds everything the PC *sends* to the target rate.
2. **Download cap (approximate).** Windows has no built-in download
   throttle, so the script shrinks the PC's TCP "receive window" —
   the amount of data the machine agrees to accept at once. A small
   window physically slows every TCP download to roughly
   window-size ÷ round-trip-time, sized for your target at ~50 ms.
3. **Keeping browsers honest.** Chrome/Edge/Firefox can bypass lever
   2 using QUIC (a UDP shortcut), so the script blocks outbound QUIC
   and browsers fall back to the slowed TCP.

**Honest limits:** the download figure is a target, not a guarantee
(closer servers come in faster, farther ones slower); pure-UDP
traffic (some games, calls) is not slowed — Windows offers no lever
for that without extra software. If you need *exact* caps on both
directions for a PC, route it through the toll booth (join it to the
toll-booth Wi-Fi, or the ~$10 USB-ethernet pass-through).

### What the script changes on the PC (all reversible)

* QoS policy `whoson-limit` — the upload cap
* TCP settings: receive-window auto-tuning off, window pinned small
* Firewall rule `whoson-force-tcp` — blocks QUIC (UDP 443) outbound
* Scheduled task `whoson-limit` — re-applies everything at every
  boot, hidden, as the SYSTEM account

If something misbehaves: `-Action status` to inspect, then
`-Action remove` to return the PC to stock. The script uses only
documented Windows 10/11 interfaces — nothing downloaded, nothing
third-party.

---

## Platform support at a glance

| Capability | Linux (`whoson`) | Windows 10/11 (script) |
|---|---|---|
| Live list of network devices | ✅ | — |
| Exact per-device speed caps (down+up) | ✅ via toll booth | — |
| Exact self upload cap | — | ✅ |
| Approximate self download cap | — | ✅ |
| Block a device's internet | ✅ (toll booth) | — |
| Works with any router | ✅ listing · limits router-independent | ✅ |
| Background + autostart | ✅ (`whoson start` persists until `stop`) | ✅ |

## Plain-language glossary

* **IP address** — a device's number on the network (`192.168.1.24`).
  Your home is one **subnet**: `192.168.1.0–255` (router = `.1`);
  the toll booth runs its own little range `10.42.0.x`.
* **MAC address** — the fixed serial number of a gadget's network
  hardware. Its first half identifies the maker. Phones fake a new
  one per Wi-Fi network ("Private address").
* **Bandwidth / KB/s / Mbps** — how fast data moves. 8 bits = 1 byte;
  100 KB/s = 0.8 Mbps. Downloads display in bytes; network gear
  speaks bits.
* **Hotspot** — a Wi-Fi network created by your laptop.
* **tc** — Linux's traffic meter; enforces the caps.
* **nftables** — Linux's firewall; enforces blocks and keeps
  toll-booth devices away from the laptop's own files.
* **hostapd / dnsmasq** — the standard Linux programs that run a
  hotspot and hand out addresses to joiners.
* **QoS** — a router feature for per-device speed limits; your
  router's firmware lacks it, which is why this toolbox exists.
* **QUIC** — browsers' UDP shortcut around TCP; the Windows script
  blocks it so its slow-down can't be bypassed.
* **NAT** — one-to-many address sharing: through it, toll-booth
  devices appear to the router as your laptop.

## Honest limitations

* The laptop must stay on while the toll booth is up; `whoson stop`
  and it's gone (devices drift back to the router's Wi-Fi).
* One radio, two roles: toll-booth raw top speed is roughly halved;
  caps of 5–100 KB/s are rock solid regardless.
* A device can leave the toll booth and rejoin the router to escape
  caps — the table always shows which side it's on, and real
  enforcement means making the toll booth the only door.
* Router-side lists lag seconds; a phone walking out of range can
  linger "connected" for minutes; deeply-asleep devices may not
  answer the scanner.
* The Windows script's download cap is approximate and doesn't cover
  pure-UDP traffic (games, calls).

## Project layout

```
whoson/cli.py       commands and help text (Linux tool)
whoson/gateway.py   toll booth: hotspot, speed caps, blocks
whoson/cmdgen.py    every system command, generated as data (dry-run + tests)
whoson/router.py    HG630 V2 conversation (login formula verified
                    against the router's own JavaScript)
whoson/scanner.py   door-knocking scanner (works on any router)
whoson/vendor.py    hardware-address → maker table
whoson/live.py      live table and event log
windows/            the Windows 10/11 self-limit script (one file)
tests/              unit tests — no admin rights needed:
                    python3 -m unittest discover -s tests
```
