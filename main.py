"""whoson — one simple window: who's on my network, and how fast?

Run it:  python3 main.py

The window shows every device on your network, live.  Devices that
join the laptop's own Wi-Fi (the "toll booth") can be speed-capped or
cut off; everything else is just listed.  A second pane handles PCs
that are plugged into the router by cable.

Everything slow (network asks, starting the hotspot) happens in
background threads; the window never freezes, and every result lands
in the log pane in plain words.
"""

import queue
import secrets
import sys
import threading
import time
import tkinter as tk
from tkinter import messagebox, ttk

import makers
import router as router_mod
import settings
import speeds
import tollbooth
import watch
from helpers import doctor_checks, guard_protected, validate_wifi
from tollbooth import RunError, TollBooth

REFRESH_MS = 150          # how often the window checks for fresh data
BUTTON_BUSY_OFF = "disabled"


def _address_key(ip: str):
    """Sort addresses by number (192.168.1.9 before .10), not by text."""
    try:
        return tuple(int(part) for part in ip.split("."))
    except (ValueError, AttributeError):
        return (999, 999, 999, 999)


# ---------------------------------------------------------------------------
# background data collector
# ---------------------------------------------------------------------------

class Snapshotter(threading.Thread):
    """The quiet worker: checks who's online every ~2 seconds, forever,
    and drops a fresh snapshot into a queue for the window to show."""

    def __init__(self, booth: TollBooth, out: queue.Queue):
        super().__init__(daemon=True)
        self.booth = booth
        self.out = out
        self.poller = None          # set later when a router password works
        self._prev = []
        self._last_scan = 0.0
        self._scan_cache = []
        self._stop = threading.Event()
        self._first_round = True
        self._last_using_scan = None

    def stop(self):
        self._stop.set()

    def set_router(self, client):
        """Give me a logged-in router client (or None to go scan-only)."""
        self.poller = watch.RouterPoller(client) if client else None

    def run(self):
        while not self._stop.is_set():
            try:
                self._one_round()
            except Exception as e:  # never die; tell the window once
                self.out.put(("error", f"background check hiccuped: {e}"))
                self._stop.wait(5.0)

    def _one_round(self):
        now = time.time()
        devices = list(watch.booth_devices(self.booth))
        # keep asking the router (it rate-limits itself, and backs off
        # when moody) so it recovers on its own
        router_rows = self.poller.poll(now) if self.poller else []
        using_scan = self.poller is None or self.poller.failures > 0
        if not using_scan:
            devices += router_rows
        else:
            if now - self._last_scan >= watch.SCAN_INTERVAL:
                try:
                    self._scan_cache = watch.scan_devices()
                except Exception:
                    self._scan_cache = []
                self._last_scan = now
            devices += self._scan_cache
        joined, left = watch.diff(self._prev, devices)
        events = [("+ " + watch.describe(d)) for d in joined]
        events += [("- " + watch.describe(d)) for d in left]
        if self._first_round:
            events = []          # the window just opened: nobody "joined"
        elif using_scan != self._last_using_scan:
            # the list came from somewhere else this round (router answered,
            # or fell back to door-knocking): gadgets missing from the new
            # source aren't really gone, so don't announce them as left
            events = [("+ " + watch.describe(d)) for d in joined]
        self._first_round = False
        self._last_using_scan = using_scan
        self._prev = devices
        status = self.poller.status if self.poller else \
            "listing by door-knocking (add the router password in the menu " \
            "to see router-side devices too)"
        self.out.put(("snapshot", devices, events, status,
                      self.booth.is_up(), self.booth.lan_alias()))
        self._stop.wait(watch.BOOTH_INTERVAL)


# ---------------------------------------------------------------------------
# the window itself
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("whoson — who's on my network?")
        root.geometry("940x700")
        root.minsize(860, 560)

        self.cfg = settings.load()
        self.booth = TollBooth(self.cfg)
        self.updates = queue.Queue()
        self._busy = False
        self._selected_key = None
        self._last_devices = []
        self._login_win = None
        self._login_status = None
        self._login_try = None
        self._router_ok = False
        self._router_saved = bool(self.cfg.get("router_pass"))
        self._snap = Snapshotter(self.booth, self.updates)

        self._build_menu()
        self._build_widgets()
        self._wire_keys()

        self.root.after(REFRESH_MS, self._drain)
        self._log("Welcome! Press 'Start my Wi-Fi' to open the toll booth, "
                  "then have a device join its Wi-Fi to cap or cut it.")
        self._snap.start()
        self._restore_router()

    # -- building blocks -----------------------------------------------------

    def _build_menu(self):
        menu = tk.Menu(self.root)
        help_menu = tk.Menu(menu, tearoff=0)
        help_menu.add_command(label="Check my computer (doctor)",
                              command=self.show_doctor)
        help_menu.add_command(label="Router password…",
                              command=self.ask_router_password)
        help_menu.add_command(label="Forget router password",
                              command=self.forget_router_password)
        help_menu.add_separator()
        help_menu.add_command(label="About", command=self.show_about)
        menu.add_cascade(label="Help", menu=help_menu)
        self.root.config(menu=menu)

    def _build_widgets(self):
        pad = dict(padx=6, pady=4)

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        self.start_btn = ttk.Button(top, text="Start my Wi-Fi",
                                    command=self.toggle_booth)
        self.start_btn.pack(side="left")
        self.booth_status = ttk.Label(top, text="my Wi-Fi is off")
        self.booth_status.pack(side="left", padx=10)
        self.wifi_btn = ttk.Button(top, text="Wi-Fi name & password…",
                                   command=self.ask_wifi_settings)
        self.wifi_btn.pack(side="left")

        self.router_status = ttk.Label(
            self.root, anchor="w", text="router: not asked yet")
        self.router_status.pack(fill="x", padx=8)

        columns = ("name", "ip", "mac", "maker", "where", "cap", "cut")
        self.tree = ttk.Treeview(self.root, columns=columns, show="headings",
                                 height=9)
        heads = [("name", "Name", 130), ("ip", "Address", 110),
                 ("mac", "Serial number", 140), ("maker", "Maker", 110),
                 ("where", "Where", 90), ("cap", "Speed cap", 110),
                 ("cut", "Cut off", 50)]
        for key, title, width in heads:
            self.tree.heading(key, text=title)
            self.tree.column(key, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True, **pad)
        self.tree.bind("<<TreeviewSelect>>", self._remember_selection)

        act = ttk.LabelFrame(self.root, text="Picked device")
        act.pack(fill="x", **pad)
        picked_row = ttk.Frame(act)
        picked_row.pack(fill="x")
        ttk.Label(picked_row,
                  text="Speed (like 100kb/20kb):").pack(side="left", **pad)
        self.speed_box = ttk.Entry(picked_row, width=14)
        self.speed_box.insert(0, "100kb/20kb")
        self.speed_box.pack(side="left", **pad)
        self.cap_btn = ttk.Button(picked_row, text="Cap speed",
                                  command=self.cap_picked)
        self.cap_btn.pack(side="left", **pad)
        self.uncap_btn = ttk.Button(picked_row, text="Remove cap",
                                    command=self.uncap_picked)
        self.uncap_btn.pack(side="left", **pad)
        self.cut_btn = ttk.Button(picked_row, text="Cut internet",
                                  command=self.cut_picked)
        self.cut_btn.pack(side="left", **pad)

        all_row = ttk.Frame(act)
        all_row.pack(fill="x")
        ttk.Label(all_row, text="Everyone on my Wi-Fi:").pack(side="left",
                                                             **pad)
        self.cap_all_btn = ttk.Button(all_row, text="Cap everyone",
                                      command=self.cap_everyone)
        self.cap_all_btn.pack(side="left", **pad)
        self.cap_rest_btn = ttk.Button(
            all_row, text="Cap everyone else (skip the picked one)",
            command=self.cap_everyone_else)
        self.cap_rest_btn.pack(side="left", **pad)

        cable = ttk.LabelFrame(
            self.root, text="PCs plugged into the router by cable "
                            "(their traffic must pass through this laptop)")
        cable.pack(fill="x", **pad)
        self.lan_btn = ttk.Button(cable, text="Turn cable mode on",
                                  command=self.toggle_cable)
        self.lan_btn.pack(side="left", **pad)
        self.cable_status = ttk.Label(cable, text="off")
        self.cable_status.pack(side="left", **pad)
        ttk.Label(cable, text="PC address:").pack(side="left", **pad)
        self.pc_box = ttk.Entry(cable, width=15)
        self.pc_box.pack(side="left", **pad)
        self.cap_pc_btn = ttk.Button(cable, text="Cap PC",
                                     command=self.cap_pc)
        self.cap_pc_btn.pack(side="left", **pad)
        self.uncap_pc_btn = ttk.Button(cable, text="Uncap PC",
                                       command=self.uncap_pc)
        self.uncap_pc_btn.pack(side="left", **pad)

        log_frame = ttk.LabelFrame(self.root, text="What happened")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log_text = tk.Text(log_frame, height=7, state="disabled",
                                wrap="word")
        self.log_text.pack(fill="both", expand=True)

    def _wire_keys(self):
        self.root.bind("<Return>", lambda e: self.cap_picked())

    # -- log and table -----------------------------------------------------

    def _log(self, message: str):
        stamp = time.strftime("%H:%M:%S")
        self.log_text.config(state="normal")
        self.log_text.insert("end", f"[{stamp}] {message}\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def _remember_selection(self, _event=None):
        self._selected_key = self._current_selection()
        self._refresh_cut_label()

    def _refresh_cut_label(self):
        """Say what the button will do for the picked device."""
        cut = False
        if self._selected_key:
            key_ip, key_mac = self._selected_key
            for d in self._last_devices:
                if d.blocked and (not key_mac or d.mac == key_mac) and \
                   (key_ip in ("-", d.ip) or not key_ip):
                    cut = True
                    break
        self.cut_btn.config(text="Let it back" if cut else "Cut internet")

    def _current_selection(self):
        """What is picked right now, read on the window's own thread."""
        picked = self.tree.selection()
        if not picked:
            return None
        values = self.tree.item(picked[0], "values")
        return (values[1], values[2])            # (address, serial number)

    def _picked_device(self, key=None) -> dict:
        """The picked row as a plain device dict.

        Uses the last snapshot (no window access), so this is safe to
        call from a worker thread.
        """
        key = key if key is not None else self._selected_key
        if not key:
            raise LookupError("click a device in the table first")
        key_ip, key_mac = key
        key_ip = "" if key_ip == "-" else key_ip
        key_mac = "" if key_mac == "-" else key_mac
        for d in self._last_devices:
            if (not key_ip or d.ip == key_ip) and \
               (not key_mac or d.mac == key_mac):
                if d.source != "booth":
                    where = "the router's side" if d.source == "router" \
                        else "the scan list"
                    raise LookupError(
                        f"{d.name or d.ip} is on {where}, not my Wi-Fi — only "
                        "devices that joined my Wi-Fi can be capped or cut. "
                        "Have it join the toll-booth Wi-Fi first.")
                if not d.ip:
                    raise LookupError("that device has no address yet — give "
                                      "it a second, then try again")
                return {"ip": d.ip, "mac": d.mac, "name": d.name}
        raise LookupError("that device left — pick another in the table")

    def _show_table(self, devices: list):
        """Draw the table without rebuilding it: rows update in place, so
        the list doesn't flicker and your scroll position stays put."""
        rows = {}                                # iid -> (rank, values)
        for d in devices:
            where = {"booth": "my Wi-Fi 📶", "router": "router",
                     "scan": "scan"}[d.source]
            cap = ""
            if d.cap:
                down, up = d.cap
                fmt = lambda k: (f"{k // 1000}M" if k >= 1000 and k % 1000 == 0
                                 else f"{k // 8}KB/s")
                cap = f"{fmt(down)}↓/{fmt(up)}↑"
            iid = d.mac or d.ip or f"row-{len(rows)}"
            rank = {"booth": 0, "router": 1, "scan": 2}[d.source]
            values = (d.name or "-", d.ip or "-", d.mac or "-",
                      makers.maker_of(d.mac), where, cap,
                      "⛔ yes" if d.blocked else "")
            # the same gadget can show up in two lists; keep the best row
            if iid not in rows or rank < rows[iid][0]:
                rows[iid] = (rank, values)
        ordered = dict(sorted(
            ((iid, values) for iid, (_, values) in rows.items()),
            key=lambda item: (_address_key(item[1][1]), item[1][2])))
        existing = set(self.tree.get_children())
        for iid, values in ordered.items():
            if iid in existing:
                self.tree.item(iid, values=values)
            else:
                self.tree.insert("", "end", iid=iid, values=values)
        for iid in existing - ordered.keys():
            self.tree.delete(iid)
        for index, iid in enumerate(ordered):     # keep address order
            if self.tree.index(iid) != index:
                self.tree.move(iid, "", index)
        self._last_devices = devices
        if self._selected_key:
            if any(item in ordered for item in self.tree.selection()):
                self._remember_selection()       # row may have new values
                return                           # selection still valid
            for iid in self.tree.get_children():
                values = self.tree.item(iid, "values")
                if (values[1], values[2]) == self._selected_key:
                    self.tree.selection_set(iid)
                    break

    # -- incoming background data --------------------------------------------

    def _drain(self):
        try:
            while True:
                msg = self.updates.get_nowait()
                if msg[0] == "snapshot":
                    _, devices, events, status, up, lan = msg
                    self._show_table(devices)
                    for line in events:
                        self._log(line)
                    self.booth_status.config(
                        text=("my Wi-Fi is ON — devices can join it"
                              if up else "my Wi-Fi is off"))
                    self.start_btn.config(
                        text="Stop my Wi-Fi" if up else "Start my Wi-Fi")
                    suffix = ""
                    if self._router_ok and self._router_saved:
                        suffix = "  ·  password saved ✓"
                    elif self._router_ok:
                        suffix = "  ·  password works (not saved)"
                    elif self._router_saved:
                        suffix = ("  ·  saved password isn't working — "
                                  "Help → Router password…")
                    self.router_status.config(text=f"router: {status}{suffix}")
                    self.lan_btn.config(
                        text="Turn cable mode off" if lan
                        else "Turn cable mode on")
                    self.cable_status.config(
                        text=f"currently on — laptop address: {lan}" if lan
                        else "currently off")
                elif msg[0] == "error":
                    self._log(msg[1])
                elif msg[0] == "done":
                    self._busy = False
                    self._set_busy_buttons("normal")
                    self._log(msg[1])
                elif msg[0] == "failed":
                    self._busy = False
                    self._set_busy_buttons("normal")
                    self._log(f"✗ {msg[1]}")
                elif msg[0] == "router_bad":
                    self._router_ok = False
                    self._login_result(f"✗ {msg[1]}", "#b00020")
                    self._log(f"✗ router said no: {msg[1]}")
                elif msg[0] == "router_ok":
                    _, client, user, password, remember, origin = msg
                    self._router_ok = True
                    self._snap.set_router(client)
                    if origin == "restore":
                        self._router_saved = bool(self.cfg.get("router_pass"))
                        self._log("router password works — router-side "
                                  "devices will appear in the table")
                    else:
                        self._remember_router(user, password, remember)
                elif msg[0] == "doctor":
                    self._show_doctor_window(msg[1])
        except queue.Empty:
            pass
        self.root.after(REFRESH_MS, self._drain)

    # -- actions (run in a worker thread; results via the queue) -------------

    def _set_busy_buttons(self, state):
        for btn in (self.start_btn, self.wifi_btn, self.cap_btn,
                    self.uncap_btn, self.cut_btn, self.cap_all_btn,
                    self.cap_rest_btn, self.lan_btn, self.cap_pc_btn,
                    self.uncap_pc_btn):
            btn.config(state=state)

    def _run(self, fn, ok_message=None):
        """Do fn in the background so the window never freezes."""
        if self._busy:
            self._log("one moment — still busy with the last request…")
            return
        self._busy = True
        self._set_busy_buttons(BUTTON_BUSY_OFF)

        def worker():
            try:
                result = fn()
                self.updates.put(("done", ok_message or result))
            except (RunError, LookupError, ValueError) as e:
                self.updates.put(("failed", str(e)))
            except Exception as e:  # noqa: BLE001 — show, never crash
                self.updates.put(("failed", f"unexpected problem: {e}"))
        threading.Thread(target=worker, daemon=True).start()

    def _read_speed(self) -> tuple:
        """Only ever called on the window's thread (Tk isn't thread-safe)."""
        try:
            return speeds.parse_speed(self.speed_box.get())
        except ValueError as e:
            raise ValueError(f"that speed didn't make sense: {e}")

    def _speed_or_complain(self):
        try:
            return self._read_speed()
        except ValueError as e:
            self._log(f"✗ {e}")
            return None

    def toggle_booth(self):
        if self.booth.is_up():
            self._run(self.booth.stop, "my Wi-Fi is off")
        else:
            cfg = self.cfg
            if not cfg.get("hotspot_psk"):
                cfg["hotspot_psk"] = secrets.token_urlsafe(12)
                settings.save(cfg)
            self._run(self.booth.start)

    def ask_wifi_settings(self):
        """Dialog: the name and password devices type to join my Wi-Fi."""
        win = tk.Toplevel(self.root)
        win.title("My Wi-Fi name & password")
        win.transient(self.root)
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=12)
        ttk.Label(
            frm, wraplength=340, justify="left",
            text="This is the Wi-Fi this laptop shares with other devices. "
                 "Changing it while it's on restarts the Wi-Fi, so anyone "
                 "connected has to join again.").grid(row=0, column=0,
                                                       columnspan=3,
                                                       sticky="w")

        ttk.Label(frm, text="Name:").grid(row=1, column=0, sticky="w",
                                          pady=(10, 0))
        name_box = ttk.Entry(frm, width=28)
        name_box.insert(0, self.cfg.get("hotspot_ssid") or "whoson")
        name_box.grid(row=1, column=1, columnspan=2, sticky="w", pady=(10, 0))

        ttk.Label(frm, text="Password:").grid(row=2, column=0, sticky="w")
        pass_box = ttk.Entry(frm, width=28, show="•")
        if self.cfg.get("hotspot_psk"):
            pass_box.insert(0, self.cfg["hotspot_psk"])
        pass_box.grid(row=2, column=1, sticky="w")
        show = tk.BooleanVar(value=False)

        def make_password():
            pass_box.delete(0, "end")
            pass_box.insert(0, secrets.token_urlsafe(12))
            show.set(True)
            pass_box.config(show="")

        ttk.Button(frm, text="Make one", command=make_password).grid(
            row=2, column=2, sticky="w", padx=(6, 0))

        def toggle_show():
            pass_box.config(show="" if show.get() else "•")

        ttk.Checkbutton(frm, text="Show password", variable=show,
                        command=toggle_show).grid(row=3, column=1,
                                                  columnspan=2, sticky="w")
        ttk.Label(frm, text="At least 8 characters; up to 32 in the name.",
                  foreground="#555").grid(row=4, column=0, columnspan=3,
                                          sticky="w", pady=(4, 0))

        def save():
            try:
                name, psk = validate_wifi(name_box.get(), pass_box.get())
            except ValueError as e:
                messagebox.showerror("My Wi-Fi", str(e), parent=win)
                return
            changed = (name != self.cfg.get("hotspot_ssid")
                       or psk != self.cfg.get("hotspot_psk"))
            if not changed:
                win.destroy()
                self._log("my Wi-Fi name and password are unchanged")
                return
            self.cfg["hotspot_ssid"] = name
            self.cfg["hotspot_psk"] = psk
            settings.save(self.cfg)
            win.destroy()
            if not self.booth.is_up():
                self._log(f"saved — my Wi-Fi will be called '{name}' the next "
                          "time you start it")
                return
            if self._busy:
                self._log("saved — I'm busy with another request; the new "
                          "name and password take effect the next time you "
                          "start my Wi-Fi")
                return
            if messagebox.askyesno(
                    "My Wi-Fi",
                    "Saved. My Wi-Fi is on right now. Restart it now so the "
                    "new name and password take effect?\n\n"
                    "Anyone connected will have to join again.",
                    parent=self.root):
                self._run(self._restart_booth)
            else:
                self._log("saved — the new name and password take effect the "
                          "next time you start my Wi-Fi")

        ttk.Button(frm, text="Save", command=save).grid(
            row=5, column=0, columnspan=3, pady=(10, 0))

    def _restart_booth(self):
        """Stop and start the hotspot so a new name/password take effect."""
        self.booth.stop()
        return self.booth.start()

    def cap_picked(self):
        speed = self._speed_or_complain()
        if speed is None:
            return
        down, up = speed
        key = self._current_selection()

        def action():
            if not self.booth.is_up():
                raise RunError("my Wi-Fi isn't on — press 'Start my Wi-Fi' first")
            target = self._picked_device(key)
            guard_protected(self.booth, target["ip"])
            return self.booth.cap(target["ip"], down, up,
                                  mac=target.get("mac", ""))
        self._run(action)

    def uncap_picked(self):
        key = self._current_selection()

        def action():
            target = self._picked_device(key)
            return self.booth.uncap(target["ip"], mac=target.get("mac", ""))
        self._run(action)

    def cut_picked(self):
        key = self._current_selection()

        def action():
            target = self._picked_device(key)
            guard_protected(self.booth, target["ip"])
            if not self.booth.is_up():
                raise RunError("my Wi-Fi isn't on — press 'Start my Wi-Fi' first")
            blocked = target["ip"] in set(self.booth.blocked())
            if blocked:
                return self.booth.unblock(target["ip"])
            return self.booth.block(target["ip"])
        self._run(action)

    def cap_everyone(self):
        self._cap_booth_devices(set())

    def cap_everyone_else(self):
        picked = self._current_selection()
        spare_macs = ({picked[1]} if picked and picked[1] not in ("", "-")
                      else set())
        self._cap_booth_devices(spare_macs)

    def _cap_booth_devices(self, spare_macs):
        speed = self._speed_or_complain()
        if speed is None:
            return
        down, up = speed

        def action():
            devices = self.booth.devices()
            if not devices:
                raise LookupError("no devices are on my Wi-Fi right now")
            lines = []
            for c in devices:
                if not c["ip"]:
                    continue
                if c["mac"] in spare_macs:
                    lines.append(f"  spared {c.get('name') or c['ip']} "
                                 "(your pick)")
                    continue
                try:
                    guard_protected(self.booth, c["ip"])
                except ValueError:
                    lines.append(f"  skipped {c.get('name') or c['ip']} "
                                 "(this laptop or the router — never capped)")
                    continue
                self.booth.cap(c["ip"], down, up, mac=c.get("mac", ""))
                lines.append(f"  capped {c.get('name') or c['ip']} ({c['ip']})")
            return ("capped at "
                    f"{speeds.human_speed(down, up)}:\n" + "\n".join(lines))
        self._run(action)

    def toggle_cable(self):
        def action():
            if self.booth.lan_alias():
                return self.booth.lan_down()
            return self.booth.lan_up("")
        self._run(action)

    def cap_pc(self):
        speed = self._speed_or_complain()
        if speed is None:
            return
        down, up = speed
        ip = self.pc_box.get().strip()

        def action():
            return self.booth.lan_cap(ip, down, up)
        self._run(action)

    def uncap_pc(self):
        ip = self.pc_box.get().strip()

        def action():
            return self.booth.lan_uncap(ip)
        self._run(action)

    # -- menu actions ----------------------------------------------------------

    def _remember_router(self, user: str, password: str, remember: bool):
        """Save the router password and show whether it really stuck."""
        if remember:
            self.cfg["router_user"] = user
            self.cfg["router_pass"] = password
            try:
                settings.save(self.cfg)
                saved = settings.load().get("router_pass") == password
                problem = "" if saved else "the saved file didn't read back"
            except OSError as e:
                saved, problem = False, str(e)
            self._router_saved = saved
            if saved:
                self._login_result("✓ Working — saved on this computer",
                                   "#0a7a0a")
                self._log("router password works — saved on this computer; "
                          "router-side devices will appear in the table")
            else:
                self._login_result(f"✓ Working, but couldn't save: {problem}",
                                   "#b00020")
                self._log("✗ router password works, but it couldn't be "
                          f"saved: {problem}")
            return

        # Remember is off: don't leave an older password lying around.
        if self.cfg.get("router_pass") is not None:
            self.cfg["router_pass"] = None
            try:
                settings.save(self.cfg)
            except OSError as e:
                self._log(f"✗ couldn't remove the saved router password: {e}")
        self._router_saved = False
        self._login_result("✓ Working — not saved (tick Remember)",
                           "#8a5a00")
        self._log("router password works for this session — nothing is "
                  "saved on this computer")

    def _restore_router(self):
        """Use the remembered router password, if there is one."""
        if not self.cfg.get("router_pass"):
            return

        def worker():
            try:
                client = router_mod.RouterClient(
                    self.cfg["router_ip"], self.cfg.get("router_user", "admin"),
                    self.cfg["router_pass"])
                client.login()
            except Exception as e:  # noqa: BLE001 — just tell the window
                self.updates.put(("failed", "the saved router password didn't "
                                           f"work ({e}) — Help → Router "
                                           "password… to try again"))
                return
            self.updates.put(("router_ok", client,
                              self.cfg.get("router_user", "admin"),
                              self.cfg["router_pass"], False, "restore"))
        threading.Thread(target=worker, daemon=True).start()

    def show_doctor(self):
        """Run the checks in the background — the router probe can take a
        few seconds and the window must stay responsive."""
        self._log("checking this computer…")

        def worker():
            try:
                rows = doctor_checks()
            except Exception as e:  # noqa: BLE001
                self.updates.put(("failed", f"the check itself broke: {e}"))
                return
            self.updates.put(("doctor", rows))
        threading.Thread(target=worker, daemon=True).start()

    def _show_doctor_window(self, rows):
        win = tk.Toplevel(self.root)
        win.title("Check my computer")
        win.transient(self.root)
        text = tk.Text(win, width=70, height=12, wrap="word")
        text.pack(padx=10, pady=10)
        text.insert("end", "Everything the toll booth needs:\n\n")
        for name, ok, note in rows:
            mark = "✓" if ok else "✗"
            text.insert("end", f"  [{mark}] {name:<8} — {note}\n")
        good = all(ok for _, ok, _ in rows)
        text.insert("end", "\n" + ("Everything looks good!"
                                   if good else
                                   "Some pieces are missing — see the ✗ rows."))
        text.config(state="disabled")

    def ask_router_password(self):
        """Small dialog: router username + password, remembered if wanted."""
        if self._login_win is not None:
            try:
                self._login_win.lift()
                return
            except tk.TclError:
                self._login_win = None

        win = tk.Toplevel(self.root)
        win.title("Router password")
        win.transient(self.root)
        self._login_win = win
        frm = ttk.Frame(win)
        frm.pack(padx=12, pady=12)
        ttk.Label(frm, text=f"Router address: {self.cfg['router_ip']}").grid(
            row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(frm, text="Username:").grid(row=1, column=0, sticky="w")
        user_box = ttk.Entry(frm, width=24)
        user_box.insert(0, self.cfg.get("router_user", "admin"))
        user_box.grid(row=1, column=1, pady=2)
        ttk.Label(frm, text="Password:").grid(row=2, column=0, sticky="w")
        pass_box = ttk.Entry(frm, width=24, show="•")
        if self.cfg.get("router_pass"):
            pass_box.insert(0, self.cfg["router_pass"])
        pass_box.grid(row=2, column=1, pady=2)
        remember = tk.BooleanVar(value=True)
        ttk.Checkbutton(frm, text="Remember (saved only on this computer)",
                        variable=remember).grid(row=3, column=0,
                                                columnspan=2, sticky="w")

        if self.cfg.get("router_pass"):
            status_text = ("A password is saved on this computer. "
                           "Press Try it to check it.")
            status_color = "#0a7a0a"
        else:
            status_text = "Not tried yet."
            status_color = "#555"
        status = ttk.Label(frm, text=status_text, foreground=status_color,
                           wraplength=320, justify="left")
        status.grid(row=4, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self._login_status = status

        def try_login():
            user, password = user_box.get().strip(), pass_box.get()
            if not password:
                messagebox.showerror("Router password",
                                     "Type the router's password first.",
                                     parent=win)
                return
            keep = remember.get()
            win.config(cursor="watch")
            status.config(text="Checking…", foreground="#555")
            if self._login_try is not None:
                self._login_try.config(state="disabled")

            def worker():
                try:
                    client = router_mod.RouterClient(self.cfg["router_ip"],
                                                     user, password)
                    client.login()
                except Exception as e:  # noqa: BLE001 — offline router too
                    self.updates.put(("router_bad", str(e)))
                    return
                self.updates.put(("router_ok", client, user, password, keep,
                                  "dialog"))
            threading.Thread(target=worker, daemon=True).start()

        buttons = ttk.Frame(frm)
        buttons.grid(row=5, column=0, columnspan=2, pady=(8, 0))
        self._login_try = ttk.Button(buttons, text="Try it",
                                     command=try_login)
        self._login_try.pack(side="left", padx=(0, 6))
        ttk.Button(buttons, text="Close",
                   command=self._close_login).pack(side="left")

        win.bind("<Escape>", lambda _e: self._close_login())
        win.protocol("WM_DELETE_WINDOW", self._close_login)

    def _login_result(self, text: str, color: str):
        """Show how the last login went in the dialog, if it's still open."""
        if self._login_win is None:
            return
        self._login_win.config(cursor="")
        if self._login_try is not None:
            self._login_try.config(state="normal")
        if self._login_status is not None:
            self._login_status.config(text=text, foreground=color)

    def _close_login(self):
        """Close the password dialog (button, Escape, or window close)."""
        win, self._login_win = self._login_win, None
        self._login_status = None
        self._login_try = None
        if win is not None:
            try:
                win.config(cursor="")
                win.destroy()
            except tk.TclError:
                pass

    def forget_router_password(self):
        settings.forget_password()
        self._router_ok = False
        self._router_saved = False
        self._snap.set_router(None)
        self._log("router password removed from this computer — "
                  "listing falls back to door-knocking")

    def show_about(self):
        messagebox.showinfo(
            "About whoson",
            "whoson — who's on my network?\n\n"
            "Shows every device on your network, live.  Devices that join "
            "this laptop's own Wi-Fi can be speed-capped or cut off, "
            "because their traffic passes through this laptop.\n\n"
            "Capped things ride on a device's serial number (MAC), so they "
            "survive address changes and reconnects.")

    # -- shutdown ---------------------------------------------------------------

    def on_close(self):
        self._snap.stop()
        self.root.destroy()


def main():
    if sys.platform == "win32":
        root = tk.Tk()
        root.withdraw()
        messagebox.showinfo(
            "whoson",
            "This window works on Linux.  On Windows, use the script in the "
            "windows folder: point-to-laptop.ps1 — it sends this PC's "
            "internet through your laptop, and the laptop's window does "
            "the limiting.")
        return
    root = tk.Tk()
    app = App(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
