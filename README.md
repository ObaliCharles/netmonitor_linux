# Network Data Monitor

Local, offline, per-process bandwidth tracker for Linux (built/tested for Pop!_OS).
No cloud, no account — everything lives in a SQLite DB at
`~/.local/share/netmonitor/netmonitor.db`.

## How it works

- `monitor.py` runs `nethogs -t` (trace mode) as root, parses its streaming
  per-process output, and writes each sample straight into SQLite.
- `cli.py` reads that database and prints summaries — no root needed for this part.
- Traffic is only recorded from the moment `monitor.py` starts running. Linux
  doesn't keep historical per-process traffic logs, so there's no way to
  backfill usage from before you started monitoring.

## 1. Install NetHogs

```bash
sudo apt update
sudo apt install nethogs
```

## 2. Find your interface name

```bash
ip link
```

Common names: `wlp3s0` / `wlan0` for Wi-Fi, `enp0s3` / `eth0` for Ethernet.

## 3. Try it manually first

Before trusting the numbers, run NetHogs itself for a few seconds and eyeball
the output format — column order can vary slightly by NetHogs version:

```bash
sudo nethogs -t wlp3s0
```

You should see lines like:

```
/usr/lib/firefox/firefox/4821/1000     12.340  340.120
```

That's `sent_KB/s` then `received_KB/s`. `nethogs_parser.py` assumes this
order — if your version prints them the other way round, swap `down_bytes`
and `up_bytes` in `nethogs_parser.py`'s `parse_line()`.

## 4. Run the collector

```bash
sudo python3 monitor.py --interface wlp3s0 --verbose
```

Leave it running in a terminal (or set it up as a service — see below) and
let it collect for a bit.

## 5. Check your stats

In a separate (non-root) terminal:

```bash
python3 cli.py summary
python3 cli.py apps --period today
python3 cli.py apps --period 7d --sort up
python3 cli.py export --period 30d --out usage.csv
python3 cli.py reset            # wipe stored stats, asks to confirm
python3 cli.py reset --yes      # wipe without asking
```

## 6. Autostart on boot (optional)

```bash
sudo mkdir -p /opt/netmonitor
sudo cp db.py monitor.py nethogs_parser.py /opt/netmonitor/
sudo nano /opt/netmonitor/netmonitor.service   # or just edit before copying
# edit the --interface value in netmonitor.service to match your machine
sudo cp netmonitor.service /etc/systemd/system/netmonitor.service
sudo systemctl daemon-reload
sudo systemctl enable --now netmonitor
sudo systemctl status netmonitor
```

Logs: `journalctl -u netmonitor -f`

## What's next (not built yet)

These are natural follow-ups once the CLI is solid:

- **GUI** — a small desktop app (e.g. with a Python GUI toolkit) or a
  local web UI on `localhost` showing the same data with charts.
- **Kernel-accounting backend (Option B)** — swap NetHogs for direct
  reads of Linux's own network accounting (e.g. via netlink / cgroup
  accounting) for better accuracy without depending on an external tool.
- **Live "active connections" view** and **automatic process
  start/stop detection** for a more real-time dashboard.

Say the word and we can tackle the GUI next, or harden the collector
(e.g. handle NetHogs restarting, interface changes) first — your call.
