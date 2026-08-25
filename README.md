# Network Data Monitor — Desktop GUI

A local, offline, per-application bandwidth tracker for Linux. Two pieces:

- **netmonitor-gui** — the window you open. Runs as your normal user. Reads
  stats from a local SQLite database and displays them.
- **netmonitor-collector** — runs as root (NetHogs needs raw socket access
  to attribute traffic to processes). You never run this by hand — the GUI
  launches it for you with a graphical password prompt (`pkexec`) when you
  click **Start Monitoring**.

Everything is stored locally at `~/.local/share/netmonitor/netmonitor.db`.
No cloud, no account.

## 1. Install build/runtime dependencies

```bash
sudo apt update
sudo apt install nethogs python3-tk policykit-1
pip install pyinstaller --break-system-packages
```

- `nethogs` — does the actual per-process traffic attribution.
- `python3-tk` — GUI toolkit (only needed to *build*; not needed once compiled).
- `policykit-1` — provides `pkexec`, the graphical "enter your password" prompt.
  This is normally already installed on Pop!_OS.

## 2. Compile both pieces

From this folder:

```bash
pyinstaller --onefile --name netmonitor-gui gui.py
pyinstaller --onefile --name netmonitor-collector monitor.py
```

Each command produces one standalone binary in `dist/`. They must end up
**in the same folder** — the GUI looks for `netmonitor-collector` right next
to its own executable.

## 3. Install it

```bash
sudo mkdir -p /opt/netmonitor
sudo cp dist/netmonitor-gui dist/netmonitor-collector /opt/netmonitor/
sudo ln -sf /opt/netmonitor/netmonitor-gui /usr/local/bin/netmonitor
```

Now you can launch it from anywhere with:

```bash
netmonitor
```

(Or just double-click `netmonitor-gui` in a file manager — it's a normal
executable.)

## 4. Using it

1. The **Interface** box auto-fills with a guess at your active network
   interface. Check it's right (`ip -o link show` to see your options) —
   Wi-Fi is usually `wlp3s0` or `wlan0`, Ethernet is usually `enp0s3` or `eth0`.
2. Click **Start Monitoring** — you'll get a graphical password prompt
   (that's `pkexec` asking permission to run the collector as root).
3. Traffic starts accumulating. The window auto-refreshes every 5 seconds.
4. **Stop Monitoring** cleanly stops the collector (also via a password
   prompt — stopping a root process needs root too).
5. **Export CSV** and **Reset Stats** work on whatever period is selected
   in the dropdown.

One real limitation worth knowing: monitoring only records traffic **from
the moment you click Start**. Linux doesn't keep a historical per-app
traffic log, so there's no way to recover usage from before you started.

## 5. (Optional) Start monitoring automatically at login

If you don't want to click Start Monitoring every time, you can add a
systemd service so the collector starts at boot instead of via the GUI
button — ask and we can set that up next.

## What's not built yet

- A system tray icon with a live running total (rather than only the window)
- Kernel-level traffic accounting as an alternative to NetHogs (more
  accurate, no external dependency) — this is the "Option B" approach from
  earlier in our conversation
- Per-connection / live "active connections" view

Say the word if you want any of those next.
