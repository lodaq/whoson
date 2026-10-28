# whoson — who's on my Wi-Fi, and how fast are they allowed to go?

A small program for your home network. It shows every device that is
online — phones, TVs, laptops, mystery gadgets — in one simple window,
live. And for devices that join **your laptop's own Wi-Fi**, it can
slow them down to an exact speed, or cut their internet off entirely.

Works on **Linux** (built and tested on Arch Linux). A Windows PC
joins in with one small script — see *The Windows PC* below.

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
| The **table** | everyone online, updating live: name, address, serial number, maker, *where* they are (my Wi-Fi 📶 / router / scan), their cap, and whether they're cut off |
| **Speed box** | how fast a device may go, written like `100kb/20kb` (kilobytes per second, down/up — same numbers a download shows). Also understands `5/1` for megabits |
| **Cap speed** | slows the picked device, both directions, exactly |
| **Remove cap** | back to full speed |
| **Cut internet / undo** | blocks the picked device completely, then lets it back |
| **Cap everyone** | caps every device on my Wi-Fi at the speed in the box (the laptop and router are always skipped) |
| **Cap everyone else** | same, but spares the device picked in the table |
| **Turn cable mode on / off** | for PCs *plugged into the router by cable* — see below; the label beside it says whether it's on right now and, when on, the laptop address to give the PC's script |
| The **log** | every result in plain words: who joined, who left, what worked |
| Help → **Router password…** | tell whoson the router's admin password and it lists router-side devices too (kept only on this laptop, reused automatically next time you open the window; the dialog says whether the password is saved and working, and has its own **Close** button); without it, listing still works by door-knocking |

Caps remember the *device*, not its address — a phone that
reconnects and gets a new address stays capped.

## The Windows PC

A PC plugged into the router by cable can't join your Wi-Fi. Instead,
its traffic is *pointed at* the laptop (once, one command):

1. In the app, press **Turn cable mode on**. The log prints the laptop's
   address, something like `192.168.1.253`.
2. Copy `windows/point-to-laptop.ps1` to the PC, open PowerShell as
   administrator, and run:

   ```powershell
   powershell -ExecutionPolicy Bypass -File point-to-laptop.ps1 -Action install -Gateway 192.168.1.253
   ```

3. In the app, type the PC's address in the Cable-PC box and press
   **Cap PC**.

The script quietly checks every 30 seconds: laptop on → go through
the laptop; laptop off → go straight to the router, full speed. Undo
any time with `-Action remove`. The PC never loses internet because
the laptop is off — it just isn't capped then.

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

## Checks

```sh
cd ~/repos/whoson
python3 -m unittest discover -s tests
```

80 checks that everything still works — no admin rights needed.

## The files, in one breath

`main.py` the window · `helpers.py` safety guards + doctor checks ·
`tollbooth.py` the toll booth (caps, cuts, cable mode) · `commands.py`
every system command, built as data · `watch.py` who is online ·
`router.py` asking the router for its list · `scanner.py`
door-knocking · `makers.py` serial number → brand · `speeds.py` what
`100kb/20kb` means · `settings.py` the small settings file ·
`windows/point-to-laptop.ps1` the Windows side.
