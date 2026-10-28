"""Isolated UI smoke check: run with xvfb-run -a python -m tests.check_desktop_ui.

All services, configuration writes and privileged actions are replaced with fakes.
Screenshots are written to the optional WHOSON_UI_ARTIFACTS directory.
"""
import os
from pathlib import Path
import tkinter as tk
from unittest.mock import Mock, patch

from PIL import ImageGrab

import main
import settings
from watch import Device


def check():
    errors = []
    root = tk.Tk()
    root.report_callback_exception = lambda *args: errors.append(args)
    cfg = dict(settings.DEFAULTS, companion_key="test-only")
    booth = Mock()
    booth.wifi = "wlan-test"
    booth.is_up.return_value = True
    booth.lan_alias.return_value = ""
    with patch.object(main.settings, "load", return_value=cfg), \
         patch.object(main.settings, "save"), \
         patch.object(main.settings, "remember_speed", side_effect=lambda value: value), \
         patch.object(main, "TollBooth", return_value=booth), \
         patch.object(main, "Snapshotter"), \
         patch.object(main.companion, "Server"), \
         patch.object(main.usage, "Monitor"):
        app = main.App(root)
        assert not root.cget("menu")
        # Exercise the real UI callbacks while keeping all actions local.
        app._run = lambda action, *args: action()
        rows = [Device("10.42.0.136", "02:00:00:00:00:01", "Demo phone",
                       source="booth", connection="wireless", cap=(400, 80),
                       download_now=50000, upload_now=10000,
                       used_down=4200000, used_up=1000000, daily_limit=2000000000),
                Device("192.168.1.5", "aa:bb:cc:dd:ee:ff", "Demo Windows PC",
                       source="cable", connection="wired", client_id="12" * 16),
                Device("192.168.1.9", "02:00:00:00:00:03", "Demo router device")]
        app.updates.put(("snapshot", rows, [], "ok · active scanning off", False, ""))
        app._drain()
        root.update()
        app.tree.selection_set(rows[0].mac)
        root.update()
        assert "Demo phone" in app.selection_label.cget("text")
        with patch.object(main, "guard_protected"):
            app.cap_btn.invoke()
        booth.cap.assert_called_once()
        # Selection survives a background refresh and blocking changes its action label.
        rows[0].blocked = True
        app._show_table(rows)
        root.update()
        assert app.tree.selection() == (rows[0].mac,)
        assert app.cut_btn.cget("text") == "Let it back"
        app._set_busy_buttons("disabled")
        assert "disabled" in app.cap_btn.state()
        app._set_busy_buttons("normal")
        assert "disabled" not in app.cap_btn.state()
        rows[0].blocked = False
        app._show_table(rows)
        artifacts = os.environ.get("WHOSON_UI_ARTIFACTS")

        def capture(name):
            root.update()
            if artifacts:
                path = Path(artifacts)
                path.mkdir(parents=True, exist_ok=True)
                ImageGrab.grab(bbox=(root.winfo_rootx(), root.winfo_rooty(),
                                     root.winfo_rootx() + root.winfo_width(),
                                     root.winfo_rooty() + root.winfo_height()),
                               xdisplay=os.environ["DISPLAY"]).save(path / f"{name}.png")

        for size in ("1280x850", "1060x820"):
            root.geometry(size)
            root.update()
            for index, name in enumerate(("devices", "network", "activity", "discovery")):
                app.workspace.select(index)
                root.update()
                capture(f"{name}-{size}")
                def fits(parent):
                    for child in parent.winfo_children():
                        assert child.winfo_ismapped(), str(child)
                        assert child.winfo_y() + child.winfo_height() <= parent.winfo_height(), str(child)
                        assert child.winfo_height() >= child.winfo_reqheight(), str(child)
                        fits(child)
                if index in (1, 3):
                    fits(app.workspace.nametowidget(app.workspace.tabs()[index]))
                # Every control must fit inside its tab at the minimum size.
                controls = ((app.cut_btn,) if index == 0 else
                            (app.start_btn, app.cap_rest_btn, app.windows_btn, app.router_status,
                             app.activity_status) if index == 1 else
                            (app.log_text,) if index == 2 else (app.discovery_save_btn,))
                for widget in controls:
                    assert widget.winfo_rootx() + widget.winfo_width() <= root.winfo_rootx() + root.winfo_width()
                    assert widget.winfo_rooty() + widget.winfo_height() <= root.winfo_rooty() + root.winfo_height()
                    assert widget.winfo_ismapped()
                    assert widget.winfo_height() >= widget.winfo_reqheight()
        assert not app.active_scan_var.get()
        assert app.router_polling_var.get()
        app.router_polling_var.set(False)
        app.discovery_save_btn.invoke()
        root.update()
        assert "reopen" in app.discovery_status.cget("text")
        assert app.cfg["router_polling"] is False
        app.ask_wifi_settings()
        root.update()
        capture("wifi-dialog")
        for win in root.winfo_children():
            if isinstance(win, tk.Toplevel):
                win.destroy()
        app.ask_router_password()
        root.update()
        capture("router-dialog")
        app._close_login()
        diagnostic_rows = [(name, True, "Installed and available") for name in
                           ("nmcli", "hostapd", "dnsmasq", "tc", "nft", "iw", "sudo", "wifi")]
        diagnostic_rows.append(("router", False, "192.168.1.1 did not respond; scanning is still available."))
        app._show_doctor_window(diagnostic_rows)
        root.update()
        assert root.grab_current() == app._doctor_win
        capture("doctor-dialog")
        # Reopening replaces the old modal and keeps a single grab owner.
        previous = app._doctor_win
        app._show_doctor_window([("wifi", True, "Ready")])
        root.update()
        assert not previous.winfo_exists()
        assert root.grab_current() == app._doctor_win
        app._doctor_win.event_generate("<Escape>")
        root.update()
        assert not app._doctor_win.winfo_exists()
        assert root.grab_current() is None
        app.workspace.select(0)
        app._show_table([])
        root.update()
        assert not app.tree.get_children()
        assert app.selection_label.cget("text") == "Select a device in the table"
        assert not errors, errors
        app.on_close()
    print("Desktop smoke check passed: tabs, sizes, selection, actions, busy states, dialogs, empty list.")


if __name__ == "__main__":
    check()
