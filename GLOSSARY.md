# GLOSSARY — every word whoson uses, in plain words

**Wi-Fi** — the invisible radio network your router (or laptop) sends
through the air.

**Hotspot** — a Wi-Fi network made by a computer instead of a router.
whoson makes one on your laptop; that's the toll booth's Wi-Fi.

**Toll booth** — the nickname for this laptop while it shares its own
Wi-Fi. Like a real toll booth on a road: whoever wants to pass
(get internet) goes through it, and the booth decides how fast they
may drive.

**Router** — the box your internet comes from. It gives every gadget
at home its connection.

**IP address** — a gadget's *room number* on the network, like
`192.168.1.24`. It can change when the gadget reconnects — like
getting a different hotel room tomorrow.

**MAC address** (called *serial number* in the app) — the fixed
serial number burned into a gadget's network chip, like
`aa:bb:cc:11:22:33`. It never changes (though phones secretly invent
a fresh one per Wi-Fi network, for privacy — see *private address*).

**Maker** — the company that built the gadget. The first half of a
serial number says who made it: Apple, Samsung, LG…

**Private address** — a serial number a phone made up randomly, to
hide who made it. whoson shows "Private address" instead of guessing.

**Cap** — a speed limit. `100kb/20kb` means: at most 100 kilobytes
per second coming *down* (to the device) and 20 going *up* (from it).
Kilobytes per second is the same unit downloads show. 8 bits make 1
byte, so 100 KB/s = 800 kilobits/s — network gear counts in bits.

**Cut off** — no internet at all for that device. It stays connected
to the Wi-Fi, but nothing gets through.

**Door-knocking** (the *scan* rows) — a way to list devices without
any passwords: whoson politely tries to open a connection to every
address on the street. Any answer — even "nobody's home, go away" —
proves a gadget lives there. Honest, but it misses gadgets in deep
sleep.

**sudo / admin rights** — the computer's way of asking "are you the
grown-up in charge?" Changing how traffic flows needs that
permission. `sudo -v` in a terminal is you showing your ID once.

**DHCP** — the "address hand-out": whoever joins the network asks
"which room number is mine?" and gets one. whoson reads the hand-out
list to learn devices' names and numbers.

**NAT (sharing one door)** — many gadgets sharing one public identity.
Through it, devices on the toll booth look to the router like they're
the laptop.

**tc** — Linux's built-in *speed meter*. This is the tool that makes
caps exact.

**nftables** — Linux's built-in *bouncer*. It cuts devices off and
keeps toll-booth guests away from the laptop's own files.

**hostapd / dnsmasq** — the two standard programs that run the
hotspot: hostapd is the radio's announcer, dnsmasq hands out room
numbers.

**QUIC** — a side-road browsers sometimes take to dodge slow
traffic. The old Windows script blocked it; the new one doesn't need
to — the laptop meters everything that passes through, side roads
included.
