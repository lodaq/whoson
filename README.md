# whoson — who's on my Wi-Fi, and how fast are they allowed to go?

A small program for your home network. It shows every device that is
online — phones, TVs, laptops, mystery gadgets — in one simple window,
live. And for devices that join **your laptop's own Wi-Fi**, it can
slow them down to an exact speed, or cut their internet off entirely.

Works on **Linux** (built and tested on Arch Linux). A Windows PC
joins in with a one-time setup — see *The Windows PC* below.

```
      the devices you want to control          everything else
      (capped, cut off, listed instantly)      (listed only)
                  │                                  │
   phone ──▶ ┌────▼──────────────────────────────────▼─────┐
             │  your laptop (the "toll booth")             │──▶ router ──▶ internet
             └─────────────────────────────────────────────┘
```

**The one big idea:** you can only slow internet traffic that passes
through *you*. So the laptop shares its own Wi-Fi (the toll booth).
Devices that join it send everything through the laptop first — and
the laptop decides how fast they may go. Devices that stay on the
router's Wi-Fi can be *listed*, but not slowed; no program on Earth
can slow traffic it never sees.

---

## Setup (Linux laptop) — 3 steps

1. Install the tools whoson borrows (once):

   ```sh
   sudo pacman -S --noconfirm tk networkmanager iproute2 nftables iw dnsmasq hostapd
   ```
   *(Debian/Ubuntu: `sudo apt install python3-tk network-manager iproute2 nftables iw dnsmasq hostapd`)*

2. Run the app:

   ```sh
   python3 main.py
   ```

3. Press **Start my Wi-Fi**. The app invents a name and password for
   the toll-booth Wi-Fi and shows them in the log. Have a device join
   that Wi-Fi — it now appears in the table as *my Wi-Fi 📶*, ready to
   cap. You can change both any time with **Wi-Fi name & password…**.

Not sure your laptop can do this? Help → **Check my computer** ticks
every piece the toll booth needs. Speed caps and cutting need admin
rights; if the app says so, run `sudo -v` in a terminal once and try
again.

## The window, button by button

| Piece | What it does |
|---|---|
| **Start my Wi-Fi / Stop** | opens and closes the toll-booth Wi-Fi |
| **Wi-Fi name & password…** | changes the name and password devices type to join my Wi-Fi; if it's on, the app offers to restart it so the change takes effect |
| The **router line** | whether the router is answering and where the list comes from (*router* or door-knocking *scan*) |
| The **table** | everyone online, updating live: name, address, MAC address, maker, connection type (Ethernet / Wi-Fi / Unknown), *where* they are (my Wi-Fi 📶 / router / scan), their cap, and whether they're cut off |
| **Speed box** | how fast a device may go, written like `100kb/20kb` (kilobytes per second, down/up — same numbers a download shows). Also understands `5/1` for megabits |
| **Cap speed** | slows the picked device, both directions, exactly |
| **Remove cap** | back to full speed |
| **Download now / Upload now** | current average internet rates for devices routed through the laptop |
| **Used today** | today’s total data, with download/upload breakdown |
| **Set daily allowance** | limits the selected device to the entered GB per day (default 2 GB combined download + upload) |
| **Remove daily allowance** | removes the quota without clearing today’s usage |
| **Cut internet / undo** | blocks the picked device completely, then lets it back |
| **Cap everyone** | caps every device on my Wi-Fi at the speed in the box (the laptop and router are always skipped) |
| **Cap everyone else** | same, but spares the device picked in the table |
| **Turn cable mode on / off** | lets paired Windows PCs route through the laptop; the label shows whether it is on |
| **Save Windows installer…** | creates one file to carry on a flash drive and double-click on Windows |
| The **log** | every result in plain words: who joined, who left, what worked |
| Help → **Router password…** | tell whoson the router's admin password and it lists router-side devices too (kept only on this laptop, reused automatically next time you open the window; the dialog says whether the password is saved and working, and has its own **Close** button); without it, listing still works by door-knocking |

Connection type comes from the router’s interface information or a direct
connection to my Wi-Fi. Scanned devices show **Unknown**: scanning alone
cannot tell Ethernet from Wi-Fi. Add a working router password under
Help → **Router password…** to get router-side connection information.
Ethernet identifies the connection, not whether a device is a computer.

The speed box starts at **50kb/10kb** (50 KB/s down, 10 KB/s up).
It remembers your last valid edit when you use it, leave the box, or
close the window, and restores it when you open whoson again.

Caps remember the *device*, not its address — a phone that
reconnects and gets a new address stays capped.

## Daily usage and allowances

For a device on **my Wi-Fi** or a **paired PC**, select its row, enter
an allowance in **Daily GB**, and click **Set daily allowance**. The default
is **2 GB/day**, and accepts decimals such as `0.5`. Other devices remain
unlimited. The last allowance value you use is remembered.

Downloads and uploads share one allowance: 1.8 GB down + 0.2 GB up reaches
2 GB. A GB means 1,000,000,000 bytes. The firewall blocks further forwarded
IPv4 internet traffic when the allowance is reached; changing the speed
cap does not change the allowance. Increase or remove the daily allowance
to restore access early. A manual internet block remains independent.

Totals, selected allowances and device identities are saved in
`~/.config/whoson/usage.json`. Reconnecting, changing IP, or restarting the
app does not give a device a fresh allowance. Daily totals reset at the
first refresh after **midnight in Africa/Cairo**; the allowance stays set.
Live rates are averages between refreshes (normally about two seconds).
Usage starts when the app starts monitoring a device, not retroactively.
A crash/power failure can lose the last unsaved refresh of usage.

Only **IPv4 internet traffic passing through this laptop** is counted and
limited. Local-network transfers are excluded. Devices listed only by the
router or scan show **—**, because the laptop cannot measure their traffic.
The laptop and app must remain on for monitoring, midnight resets and cable
mode enforcement. A Windows helper falls back to the router when the app
is off, and its direct-router or IPv6 traffic is outside this allowance.

## The Windows PC

Windows PCs connected by Ethernet can discover this laptop and register
in the table automatically. Set up each PC once:

1. On the laptop, turn **cable mode on**, then click **Save Windows installer…**
   and save `whoson-install.cmd` to your flash drive.
2. Copy that one file onto the Windows PC, double-click it, and accept
   the administrator prompt once. No terminal commands, ZIP or IP addresses.
   After setup finishes, the flash drive and installer are no longer needed.
3. In whoson, select the row marked **paired PC** and press **Cap speed**.
   No PC address needs to be entered.

The helper runs as SYSTEM at startup, before login, and checks for the
paired laptop about every 10 seconds. A repeating task also restarts it
if it exits. Windows restarts need no setup; if either computer's IPv4
address changes, discovery and registration update it automatically.
Caps follow the saved PC identity, including across address changes and
reboots. Reinstalling the helper preserves that identity.

The laptop advertises readiness only while the app is open, cable mode
is ready, and forwarding rules for that PC have been installed. Without
an authenticated readiness reply, the helper removes its temporary
routes and uses Windows' original router routes. Allow roughly 10–15
seconds for fallback on a typical single-adapter PC; active downloads
or connections may need to reconnect. Closing whoson also stops readiness
replies. Reopening it restores cable mode if it was previously enabled.

Keep the installer file private: it contains a random pairing key, shared
only with your own PCs. This single file carries the complete helper,
installs it on the PC, and removes its temporary copy; no download is needed. Messages use HMAC-SHA256, timestamps and fresh nonces;
the helper does not trust an arbitrary laptop that answers a ping.
Local-network discovery uses UDP 47831 on the laptop and 47832 on Windows
(the installer creates a scoped Windows firewall rule). A Linux firewall
must allow UDP 47831 from your LAN. Both machines need working clocks and
the same local network without client isolation.

For optional maintenance, run the installed helper from an administrator
PowerShell window:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\whoson\point-to-laptop.ps1" -Action status
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$env:ProgramData\whoson\point-to-laptop.ps1" -Action remove
```

Use `status` to inspect it or `remove` to uninstall it. Original default
routes are left intact. This helper routes **IPv4 only**; IPv6 traffic is not capped by it. VPN route policies
can also take precedence. Windows startup, UAC and real traffic shaping
still need validation on an actual Windows PC; automated checks cover
protocol exchange and simulated route handling.

---

## Honest limits

* The laptop must stay on while the toll booth is up.
* Devices can escape caps by leaving the toll-booth Wi-Fi — the table
  always shows *where* each device is. For real enforcement, make the
  toll booth the only door (change the router's Wi-Fi password).
* Router-side lists can lag a few seconds; deeply-asleep devices may
  not answer the door-knocking scanner.
* Phones hiding behind "private addresses" (their choice, for
  privacy) show no maker name — that's honesty, not a bug.
* One radio playing two roles: toll-booth top speed is roughly
  halved. Caps of 5–100 KB/s are rock solid regardless.

## What the words mean

Every technical word — *IP address, MAC address, toll booth, cap,
sudo, door-knocking…* — is explained in one or two kid-simple
sentences in [GLOSSARY.md](GLOSSARY.md).

## To do later

- [ ] Port the gateway features to Windows so a Windows PC can host
  whoson: Wi-Fi sharing, forwarding/NAT, per-device download/upload
  speed caps, and internet blocking.
  - Reuse the interface and shared logic behind a Windows networking backend.
  - Investigate Mobile Hotspot / Internet Connection Sharing for sharing
    and NAT, plus a Windows equivalent of cable mode.
  - Investigate Windows Filtering Platform for forwarded-traffic blocking.
  - Prototype a driver-backed packet shaper for both directions before
    committing to an implementation; built-in outbound QoS alone does
    not establish support for capping forwarded hotspot clients.
  - Verify with real clients, including IP changes and cleanup on stop.
    Traffic must pass through the Windows PC for caps and blocking to work.

## Checks

```sh
cd ~/repos/whoson
python3 -m unittest discover -s tests
```

The Python checks need no admin rights. PowerShell route checks use mocked
network commands and can also run without admin rights:

```sh
pwsh -NoProfile -File tests/windows-helper.tests.ps1
```

Real usage/quota checks run inside an isolated Linux network namespace:

```sh
unshare -Urn python3 -m tests.check_usage_kernel
```

## The files, in one breath

`main.py` the window · `helpers.py` safety guards + doctor checks ·
`tollbooth.py` the toll booth (caps, cuts, cable mode) · `commands.py`
every system command, built as data · `watch.py` who is online ·
`router.py` asking the router for its list · `scanner.py`
door-knocking · `makers.py` serial number → brand · `speeds.py` what
`100kb/20kb` means · `settings.py` the small settings file ·
`usage.py` internet counters + daily allowances ·
`companion.py` authenticated Windows discovery + setup export ·
`windows/point-to-laptop.ps1` the Windows side.
