#!/usr/bin/env python3
"""
monitor.py — the collector daemon.

Runs `nethogs -t <interface>` as a subprocess, reads its streaming output,
groups lines into refresh batches, and writes each batch to SQLite as a
set of samples.

Must be run as root (NetHogs needs raw socket access to attribute traffic
to processes). Typically launched via the systemd unit in netmonitor.service,
but you can also just run it directly with sudo for testing:

    sudo python3 monitor.py --interface wlp3s0

Run `ip link` if you're not sure of your interface name (common ones:
wlp3s0 / wlan0 for Wi-Fi, enp0s3 / eth0 for Ethernet).
"""

import argparse
import shutil
import subprocess
import sys
import time

import db
from nethogs_parser import parse_batch


def check_nethogs_installed():
    if shutil.which("nethogs") is None:
        sys.exit(
            "nethogs is not installed. Install it with:\n"
            "  sudo apt install nethogs"
        )


def stream_nethogs(interface: str | None):
    """
    Launch `nethogs -t` and yield it line by line. If `interface` is given,
    NetHogs is restricted to that device; otherwise it watches all devices
    it can find.
    """
    cmd = ["nethogs", "-t"]
    if interface:
        cmd.append(interface)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )
    return proc


def run(interface: str | None, verbose: bool):
    check_nethogs_installed()
    proc = stream_nethogs(interface)

    batch_lines: list[str] = []
    written = 0

    try:
        with db.connect() as conn:
            db.set_meta(conn, "monitoring_started_hint", str(int(time.time())))

        for raw_line in proc.stdout:
            line = raw_line.rstrip("\n")
            if line.startswith("Refreshing:"):
                if batch_lines:
                    samples = parse_batch(batch_lines)
                    if samples:
                        with db.connect() as conn:
                            for s in samples:
                                db.insert_sample(
                                    conn,
                                    process=s.process,
                                    interface=interface,
                                    down_bytes=s.down_bytes,
                                    up_bytes=s.up_bytes,
                                )
                        written += len(samples)
                        if verbose:
                            print(f"[{time.strftime('%H:%M:%S')}] wrote {len(samples)} samples "
                                  f"(total written: {written})")
                batch_lines = []
            else:
                batch_lines.append(line)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()


def main():
    ap = argparse.ArgumentParser(description="Collect per-process bandwidth usage via NetHogs into SQLite.")
    ap.add_argument("--interface", "-i", default=None,
                     help="Network interface to monitor (e.g. wlp3s0). Default: all interfaces NetHogs finds.")
    ap.add_argument("--verbose", "-v", action="store_true", help="Print each batch as it's written.")
    args = ap.parse_args()

    if __import__("os").geteuid() != 0:
        sys.exit("monitor.py must be run as root (NetHogs needs raw socket access). Try: sudo python3 monitor.py")

    run(args.interface, args.verbose)


if __name__ == "__main__":
    main()
