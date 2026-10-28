# Kid-simple restructure + Linux GUI + Windows point-to-laptop script

## The new shape — flat, no folder repeating the repo name

All Python files sit at the top of `~/repos/whoson/`, each named for what a kid would call it:

```
whoson/                          ← the whole project
├── README.md                    ← start here, in kid words
├── GLOSSARY.md                  ← every technical word, explained simply
├── main.py                      ← THE APP — `python3 main.py` opens the window
├── tollbooth.py                 ← your own Wi-Fi: speed caps + internet cuts
├── commands.py                  ← the system commands we build (as data, testable)
├── watch.py                     ← who is online right now (merges all sources)
├── router.py                    ← asking the router for its device list
├── scanner.py                   ← door-knocking when the router won't talk
├── makers.py                    ← a gadget's serial number → its brand
├── settings.py                  ← the small settings file (passwords etc.)
├── speeds.py                    ← what "100kb/20kb" means
├── windows/
│   └── point-to-laptop.ps1      ← run this ON the Windows PC (one file)
└── tests/                       ← checks that everything still works
```

No package folder, no `whoson/whoson`, no relative imports — modules just say `import tollbooth`.

## Renames — old jargon → kid words (mechanical, behavior unchanged)

| Old | New |
|---|---|
| `whoson/cli.py` | deleted — replaced by the GUI in `main.py` |
| `whoson/gateway.py` | `tollbooth.py`; class `Gateway` → `TollBooth`; `clients()` → `devices()`, `limit()` → `cap()`, `unlimit()` → `uncap()` |
| `whoson/cmdgen.py` | `commands.py` |
| `whoson/live.py` | `watch.py` (drop terminal `render()`/`watch()` — the window draws its own table) |
| `whoson/vendor.py` | `makers.py`; `vendor_of()` → `maker_of()` |
| `whoson/config.py` | `settings.py` |
| new `speeds.py` | `parse_speed()` moved out of the dying CLI |
| new `main.py` | the whole GUI (~400 lines) |

LAN-mode code stays inside `tollbooth.py` (it's how cabled PCs get capped). Junk deleted: `selfish/` snapshot tree, `build/`, `whoson.egg-info/`, empty `docs/`+`tools/`, the broken `.git/` (verified zero objects — nothing recoverable), all `__pycache__/`. Then `git init` for a clean start (no commit).

## The app (`main.py`, Tkinter) — one simple window

- **Toolbar**: Start/Stop toll booth + status label; password auto-generated if none (shown in the log).
- **Device table**: Name, IP, MAC ("serial number"), Brand, Where (my Wi-Fi 📶 / router / scan), Cap, Blocked — auto-refresh ~2 s, selection kept.
- **Action row on the selected device**: speed box (`100kb/20kb`) + Cap / Uncap / Block-Unblock, plus "Cap everyone else".
- **Cabled-PC row**: LAN on/off, PC address box + Cap PC / Uncap PC; after "LAN on" the log shows the exact line to run on the Windows PC.
- **Log**: plain-language results + "phone joined / left" events.
- **Menu**: Check my computer (doctor), Forget router password, About.
- Background thread refreshes; actions run in a worker thread so the window never freezes; errors like "run `sudo -v` first" appear in the log. Router password asked in a small dialog (with save checkbox), falling back to door-knocking on failure.

## `windows/point-to-laptop.ps1` (~120 lines)

Replaces `limit-internet.ps1` (self-limiter; its `-BoothGateway` flag never existed). One job — send this PC's internet through the laptop so the laptop's app enforces caps exactly:
- `-Action install -Gateway 192.168.1.253`: persistent route through the laptop + hidden background check every 30 s: laptop reachable → go through it; laptop off → fall back to the router (the PC never loses internet). Asks for admin via the normal UAC prompt.
- `-Action status` / `-Action remove` (full undo).
- `tollbooth.py`'s "LAN on" instructions updated to name this script; all "type `whoson …`" wording replaced with window-speak.

## README + GLOSSARY

- README rewritten kid-first: what it does, 3-step setup, what each button does, honest limits — no command lines except `python3 main.py` and the one Windows line.
- GLOSSARY.md: Wi-Fi, IP address ("a gadget's room number"), MAC address ("its serial number"), router, toll booth, cap, block, hotspot, sudo, dry-run… every word the code or window uses.

## Tests & verification

Test files renamed to match modules (`test_tollbooth.py`, `test_watch.py`, `test_makers.py`, `test_commands.py`, `test_speeds.py`, …) with imports updated; dead `TestRender` removed; new tests for `resolve_target`. `python3 -m unittest discover -s tests` green; GUI launched on this machine to confirm window/table/log work without root; toll-booth paths exercised via the dry-run mode; PowerShell script verified by inspection (no Windows machine here — stated honestly). `pyproject.toml` switches to flat `py-modules` with `whoson = "main:main"` so `pipx install .` still gives the `whoson` command.