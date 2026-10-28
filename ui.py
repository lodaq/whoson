"""Cross-platform desktop presentation; networking actions live in main.App."""
import tkinter as tk
import ttkbootstrap as ttk
import tkinter.font as tkfont

import ttkbootstrap

import settings


def configure_theme(root):
    """Use Tk's portable widgets, with one shared theme for all windows."""
    style = ttkbootstrap.Style(theme="litera")
    style.colors.set("secondary", "#526477")
    style.colors.set("primary", "#275dad")
    style.colors.set("danger", "#b42338")
    families = set(tkfont.families(root))
    family = "Segoe UI" if "Segoe UI" in families else "Noto Sans" if "Noto Sans" in families else "DejaVu Sans"
    for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(name).configure(family=family, size=10)
    style.configure("Title.TLabel", font=(family, 24, "bold"))
    style.configure("Section.TLabel", font=(family, 14, "bold"))
    style.configure("Muted.TLabel", foreground="#596777")
    style.configure("Treeview", rowheight=36, font=(family, 10))
    style.configure("Treeview.Heading", font=(family, 10, "bold"), padding=(10, 12))
    style.configure("TNotebook.Tab", padding=(20, 12))
    return style


def _heading(parent, title, description):
    ttk.Label(parent, text=title, style="Section.TLabel").pack(anchor="w")
    ttk.Label(parent, text=description, style="Muted.TLabel",
              wraplength=650).pack(anchor="w", pady=(4, 12))


def _card(parent, title, description):
    frame = ttk.LabelFrame(parent, text=title, padding=12)
    frame.pack(fill="x", pady=(0, 8))
    ttk.Label(frame, text=description, wraplength=650,
              style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
    return frame


def build_workspace(app):
    root = app.root
    app.style = configure_theme(root)
    shell = ttk.Frame(root, padding=(24, 18))
    shell.pack(fill="both", expand=True)
    shell.columnconfigure(0, weight=1)
    shell.rowconfigure(1, weight=1)
    header = ttk.Frame(shell)
    header.grid(row=0, column=0, sticky="ew", pady=(0, 18))
    ttk.Label(header, text="whoson", style="Title.TLabel").pack(side="left")
    ttk.Label(header, text="Your network, under control", style="Muted.TLabel").pack(
        side="left", padx=18)
    ttk.Button(header, text="About", command=app.show_about,
               bootstyle="secondary-link").pack(side="right", padx=(12, 0))
    ttk.Button(header, text="Check my computer", command=app.show_doctor,
               bootstyle="secondary-outline").pack(side="right")

    app.workspace = ttk.Notebook(shell)
    app.workspace.grid(row=1, column=0, sticky="nsew")
    devices = ttk.Frame(app.workspace, padding=(18, 20))
    network = ttk.Frame(app.workspace, padding=(20, 20))
    activity = ttk.Frame(app.workspace, padding=(18, 20))
    discovery = ttk.Frame(app.workspace, padding=(20, 20))
    for frame, title in ((devices, "Devices"), (network, "Network setup"),
                         (activity, "Activity"), (discovery, "Discovery")):
        app.workspace.add(frame, text=title)

    # A flexible table and a fixed-width inspector keep actions near selection.
    devices.columnconfigure(0, weight=1)
    devices.columnconfigure(1, minsize=310)
    devices.rowconfigure(1, weight=1)
    intro = ttk.Frame(devices)
    intro.grid(row=0, column=0, sticky="ew")
    _heading(intro, "Devices on your network",
             "Select a device to manage its speed and daily allowance.")
    table = ttk.Frame(devices)
    table.grid(row=1, column=0, sticky="nsew")
    table.rowconfigure(0, weight=1)
    table.columnconfigure(0, weight=1)
    columns = ("name", "ip", "mac", "maker", "where", "connection", "cap",
               "cut", "download", "upload", "used", "quota")
    app.tree = ttk.Treeview(table, columns=columns, show="headings", selectmode="browse",
                           displaycolumns=("name", "ip", "download", "upload", "used",
                                           "quota", "cap", "connection", "where", "mac", "maker", "cut"))
    heads = (("name", "Device", 165), ("ip", "Address", 125),
             ("download", "Download", 105), ("upload", "Upload", 100),
             ("used", "Used today (down / up)", 270), ("quota", "Daily allowance", 155),
             ("cap", "Speed cap", 150), ("connection", "Connection", 110),
             ("where", "Source", 110), ("mac", "MAC address", 160),
             ("maker", "Maker", 130), ("cut", "Cut off", 80))
    for key, title, width in heads:
        app.tree.heading(key, text=title)
        app.tree.column(key, width=width, minwidth=80, stretch=False, anchor="w")
    horizontal = ttk.Scrollbar(table, orient="horizontal", command=app.tree.xview)
    vertical = ttk.Scrollbar(table, orient="vertical", command=app.tree.yview)
    app.tree.configure(xscrollcommand=horizontal.set, yscrollcommand=vertical.set)
    app.tree.grid(row=0, column=0, sticky="nsew")
    horizontal.grid(row=1, column=0, sticky="ew")
    vertical.grid(row=0, column=1, sticky="ns")
    app.tree.bind("<<TreeviewSelect>>", app._remember_selection)
    app.style.map("Treeview", background=[("selected", "#275dad")],
                  foreground=[("selected", "#ffffff")])
    ttk.Label(devices, text="More device details are available by scrolling the table horizontally.",
              style="Muted.TLabel", wraplength=550).grid(row=2, column=0, sticky="w", pady=(12, 0))

    inspector = ttk.Frame(devices, padding=(22, 0, 0, 0))
    inspector.grid(row=0, column=1, rowspan=3, sticky="nsew")
    ttk.Label(inspector, text="Device controls", style="Section.TLabel").pack(anchor="w")
    app.selection_label = ttk.Label(inspector, text="Select a device in the table",
                                    wraplength=285, style="Muted.TLabel")
    app.selection_label.pack(anchor="w", pady=(6, 18))
    ttk.Label(inspector, text="Speed limit").pack(anchor="w")
    app.speed_box = ttk.Entry(inspector)
    app.speed_box.insert(0, app.cfg.get("default_speed", settings.DEFAULTS["default_speed"]))
    app.speed_box.pack(fill="x", pady=(6, 4))
    app.speed_box.bind("<FocusOut>", app._remember_speed)
    ttk.Label(inspector, text="50kb/10kb = download / upload in KB/s",
              style="Muted.TLabel").pack(anchor="w", pady=(0, 6))
    actions = ttk.Frame(inspector)
    actions.pack(fill="x")
    app.cap_btn = ttk.Button(actions, text="Cap speed", command=app.cap_picked, bootstyle="primary")
    app.cap_btn.pack(side="left", fill="x", expand=True)
    app.uncap_btn = ttk.Button(actions, text="Remove cap", command=app.uncap_picked,
                               bootstyle="secondary-outline")
    app.uncap_btn.pack(side="left", padx=(8, 0))
    ttk.Separator(inspector).pack(fill="x", pady=12)
    ttk.Label(inspector, text="Daily allowance (GB)").pack(anchor="w")
    app.quota_box = ttk.Entry(inspector)
    app.quota_box.insert(0, app.cfg.get("default_daily_gb", "2"))
    app.quota_box.pack(fill="x", pady=(6, 8))
    app.quota_btn = ttk.Button(inspector, text="Set daily allowance", command=app.set_daily_allowance, bootstyle="primary")
    app.quota_btn.pack(fill="x")
    app.no_quota_btn = ttk.Button(inspector, text="Remove daily allowance",
                                  command=app.remove_daily_allowance, bootstyle="secondary-link")
    app.no_quota_btn.pack(fill="x", pady=(4, 0))
    ttk.Label(inspector, text="Download + upload combined. Resets at\nmidnight (" +
              app.cfg.get("usage_timezone", "Africa/Cairo") + ").",
              style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
    ttk.Separator(inspector).pack(fill="x", pady=12)
    app.cut_btn = ttk.Button(inspector, text="Cut internet", command=app.cut_picked,
                             bootstyle="danger-outline")
    app.cut_btn.pack(fill="x")
    ttk.Label(inspector, text="Controls apply to devices on your Wi-Fi\nor paired through cable mode.",
              style="Muted.TLabel").pack(anchor="w", pady=(10, 0))

    _heading(network, "Network setup", "Choose how devices connect through this laptop.")
    wifi = _card(network, "My Wi-Fi", "Devices that join this Wi-Fi can be speed-capped or cut off.")
    app.booth_status = ttk.Label(wifi, text="my Wi-Fi is off")
    app.booth_status.pack(anchor="w", pady=(0, 6))
    row = ttk.Frame(wifi)
    row.pack(fill="x")
    app.start_btn = ttk.Button(row, text="Start my Wi-Fi", command=app.toggle_booth, bootstyle="primary")
    app.start_btn.pack(side="left")
    app.wifi_btn = ttk.Button(row, text="Wi-Fi name & password…", command=app.ask_wifi_settings,
                              bootstyle="secondary-outline")
    app.wifi_btn.pack(side="left", padx=10)
    bulk = ttk.Frame(wifi)
    bulk.pack(fill="x", pady=(8, 0))
    ttk.Label(bulk, text="Use the speed limit from Device controls:").pack(side="left", padx=(0, 12))
    app.cap_all_btn = ttk.Button(bulk, text="Cap everyone", command=app.cap_everyone,
                                 bootstyle="secondary-outline")
    app.cap_all_btn.pack(side="left")
    app.cap_rest_btn = ttk.Button(bulk, text="Cap everyone except selected",
                                  command=app.cap_everyone_else, bootstyle="secondary-outline")
    app.cap_rest_btn.pack(side="left", padx=8)
    cable = _card(network, "Cable mode & Windows PCs",
                  "Pair PCs connected to your router. Their traffic must pass through this laptop.")
    app.cable_status = ttk.Label(cable, text="currently off")
    app.cable_status.pack(anchor="w", pady=(0, 6))
    row = ttk.Frame(cable)
    row.pack(fill="x")
    app.lan_btn = ttk.Button(row, text="Turn cable mode on", command=app.toggle_cable, bootstyle="primary")
    app.lan_btn.pack(side="left")
    app.windows_btn = ttk.Button(row, text="Save Windows installer…", command=app.save_windows_installer,
                                 bootstyle="secondary-outline")
    app.windows_btn.pack(side="left", padx=10)
    router = _card(network, "Router access", "Add your router password to also list router-side devices.")
    ttk.Button(router, text="Router password…", command=app.ask_router_password,
               bootstyle="secondary-outline").pack(side="left")
    ttk.Button(router, text="Forget saved password", command=app.forget_router_password,
               bootstyle="secondary-link").pack(side="left", padx=10)

    _heading(discovery, "Discovery controls", "Isolate connection problems by changing one setting at a time.")
    ttk.Label(discovery, text="First test: keep active scanning off and router polling on. "
              "If internet still drops, switch router polling off too. Restart whoson after each change.",
              wraplength=700, style="Muted.TLabel").pack(anchor="w", pady=(0, 20))
    app.active_scan_var = tk.BooleanVar(root, value=app.cfg.get("active_scan", False))
    app.router_polling_var = tk.BooleanVar(root, value=app.cfg.get("router_polling", True))
    ttk.Checkbutton(discovery, text="Active network scanning", variable=app.active_scan_var).pack(anchor="w")
    ttk.Label(discovery, text="Off by default. When enabled, probes local addresses to find devices "
              "when router discovery is unavailable.", wraplength=700,
              style="Muted.TLabel").pack(anchor="w", padx=24, pady=(6, 20))
    ttk.Checkbutton(discovery, text="Automatic router polling", variable=app.router_polling_var).pack(anchor="w")
    ttk.Label(discovery, text="Uses your saved router login and regularly requests its device list. "
              "Turning this off skips automatic login and device-list requests.", wraplength=700,
              style="Muted.TLabel").pack(anchor="w", padx=24, pady=(6, 20))
    ttk.Label(discovery, text="Devices on this laptop’s hotspot and paired PCs remain visible. "
              "With both options off, other router-side devices are not discovered. "
              "These switches do not change hotspot or cable-mode settings.", wraplength=700,
              style="Muted.TLabel").pack(anchor="w", pady=(0, 20))
    app.discovery_save_btn = ttk.Button(discovery, text="Save discovery settings", command=app.save_discovery_options, bootstyle="primary")
    app.discovery_save_btn.pack(anchor="w")
    app.discovery_status = ttk.Label(discovery, text="Changes apply after closing and reopening whoson.",
                                     style="Muted.TLabel", wraplength=700)
    app.discovery_status.pack(anchor="w", pady=(12, 0))

    _heading(activity, "Activity", "Connection changes, completed actions, and anything that needs attention.")
    log = ttk.Frame(activity)
    log.pack(fill="both", expand=True)
    app.log_text = tk.Text(log, height=8, state="disabled", wrap="word", borderwidth=0,
                           padx=14, pady=12, font="TkFixedFont")
    log_scroll = ttk.Scrollbar(log, command=app.log_text.yview)
    app.log_text.configure(yscrollcommand=log_scroll.set)
    log_scroll.pack(side="right", fill="y")
    app.log_text.pack(fill="both", expand=True)
    footer = ttk.Frame(shell)
    footer.grid(row=2, column=0, sticky="ew")
    ttk.Separator(footer).pack(fill="x", pady=(10, 6))
    app.router_status = ttk.Label(footer, text="router: not asked yet", style="Muted.TLabel",
                                  wraplength=1000)
    app.router_status.pack(fill="x")
    app.activity_status = ttk.Label(footer, text="", style="Muted.TLabel", wraplength=1000)
    app.activity_status.pack(fill="x", pady=(4, 0))
    def resize_status(event):
        if event.widget == root:
            width = max(300, root.winfo_width() - 60)
            app.router_status.configure(wraplength=width)
            app.activity_status.configure(wraplength=width)
    root.bind("<Configure>", resize_status, add="+")


def show_computer_check(app, rows):
    """Present diagnostic results in a scrollable, keyboard-accessible modal."""
    previous = getattr(app, "_doctor_win", None)
    if previous is not None and previous.winfo_exists():
        previous.destroy()
    win = tk.Toplevel(app.root)
    app._doctor_win = win
    win.title("Check my computer")
    win.transient(app.root)
    win.resizable(False, False)
    content = ttk.Frame(win, padding=24)
    content.pack(fill="both", expand=True)
    ready = sum(bool(ok) for _, ok, _ in rows)
    good = bool(rows) and ready == len(rows)
    pending = len(rows) - ready
    title = ("Your computer is ready" if good else
             "No check results available" if not rows else
             "1 check needs attention" if pending == 1 else f"{pending} checks need attention")
    ttk.Label(content, text=title, style="Section.TLabel").pack(anchor="w")
    ttk.Label(content, text=f"{ready} of {len(rows)} checks passed" if rows else "No check results available",
              style="Muted.TLabel").pack(anchor="w", pady=(6, 16))
    ttk.Label(content, text="These checks cover Wi-Fi sharing, internet controls, and router access.",
              wraplength=660, style="Muted.TLabel").pack(anchor="w", pady=(0, 18))

    results = ttk.Frame(content)
    results.pack(fill="both", expand=True)
    canvas = tk.Canvas(results, width=660, height=360, highlightthickness=0,
                       background=app.style.colors.bg, takefocus=True)
    scroll = ttk.Scrollbar(results, orient="vertical", command=canvas.yview)
    canvas.configure(yscrollcommand=scroll.set)
    scroll.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    checklist = ttk.Frame(canvas)
    window = canvas.create_window((0, 0), window=checklist, anchor="nw")
    canvas.bind("<Configure>", lambda event: canvas.itemconfigure(window, width=event.width))
    checklist.bind("<Configure>", lambda event: canvas.configure(scrollregion=canvas.bbox("all")))
    titles = {"nmcli": "Network settings", "hostapd": "Wi-Fi hotspot",
              "dnsmasq": "Device addresses", "tc": "Speed limits",
              "nft": "Internet blocking", "iw": "Wi-Fi adapter tools",
              "sudo": "Administrator access", "wifi": "Wi-Fi sharing support",
              "router": "Router access"}
    for name, ok, note in sorted(rows, key=lambda result: bool(result[1])):
        row = ttk.Frame(checklist, padding=(0, 12, 12, 12))
        row.pack(fill="x")
        row.columnconfigure(0, weight=1)
        ttk.Label(row, text=titles.get(name, name)).grid(row=0, column=0, sticky="w")
        ttk.Label(row, text="Ready" if ok else "Needs attention",
                  foreground="#22643a" if ok else "#925400").grid(row=0, column=1, sticky="e", padx=(14, 0))
        ttk.Label(row, text=f"{name} — {note}", wraplength=615,
                  style="Muted.TLabel").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 0))
        ttk.Separator(checklist).pack(fill="x")
    if not rows:
        ttk.Label(checklist, text="Run the check again to get fresh results.").pack(anchor="w", pady=12)

    # Scope wheel handling to this modal; avoid global bindings that outlive it.
    def wheel(event):
        step = (-1 if event.num == 4 else 1) if event.num in (4, 5) else (-1 if event.delta > 0 else 1)
        canvas.yview_scroll(step, "units")
        return "break"
    def scroll_key(amount, units):
        canvas.yview_scroll(amount, units)
        return "break"

    for sequence, amount, units in (("<Down>", 1, "units"), ("<Up>", -1, "units"),
                                    ("<Next>", 1, "pages"), ("<Prior>", -1, "pages")):
        canvas.bind(sequence, lambda event, amount=amount, units=units: scroll_key(amount, units))
    for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        win.bind(sequence, wheel)
    ttk.Label(content, text="Router access is optional. Devices can still be discovered by scanning.",
              wraplength=660, style="Muted.TLabel").pack(anchor="w", pady=(18, 16))
    ttk.Separator(content).pack(fill="x", pady=(0, 16))
    actions = ttk.Frame(content)
    actions.pack(fill="x")

    def close(event=None):
        win.destroy()
        return "break"

    def recheck():
        close()
        app.show_doctor()

    ttk.Button(actions, text="Run again", command=recheck,
               bootstyle="secondary-outline").pack(side="left")
    done = ttk.Button(actions, text="Done", command=close, width=10, bootstyle="primary")
    done.pack(side="right")
    win.protocol("WM_DELETE_WINDOW", close)
    win.bind("<Escape>", close)
    win.bind("<Return>", close)
    win.update_idletasks()
    x = app.root.winfo_rootx() + (app.root.winfo_width() - win.winfo_reqwidth()) // 2
    y = app.root.winfo_rooty() + (app.root.winfo_height() - win.winfo_reqheight()) // 2
    win.geometry(f"+{max(0, x)}+{max(0, y)}")
    win.grab_set()
    done.focus_set()
    return win
