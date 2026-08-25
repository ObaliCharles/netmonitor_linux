#!/usr/bin/env python3
"""
monitor.py — the collector. Must run as root (NetHogs needs raw socket access).

Normally launched by gui.py via `pkexec`, which shows a graphical password
prompt. Can also be run directly for testing:

    sudo python3 monitor.py --interface wlp3s0

Writes its own PID to ~/.local/share/netmonitor/monitor.pid on start and
removes it on clean exit, so the GUI can tell whether monitoring is active
and can stop it later.
"""

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import db
from nethogs_parser import parse_batch

PID_FILE = Path.home() / ".local" / "share" / "netmonitor" / "monitor.pid"
# Note: when launched via pkexec, Path.home() resolves to root's home unless
# SUDO_USER/PKEXEC env vars are used to redirect it back to the real user.
# We handle that below in resolve_real_home().


def resolve_real_home() -> Path:
    """
    pkexec runs us as root, so Path.home() would normally give /root — but we
    want the PID file and the database in the *actual user's* home directory
    so the unprivileged GUI (running as that user) can read them.
    """
    user = os.environ.get("PKEXEC_UID")
    if user:
        import pwd
        return Path(pwd.getpwuid(int(user)).pw_dir)
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user:
        import pwd
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


def check_nethogs_installed():
    if shutil.which("nethogs") is None:
        sys.exit("nethogs is not installed. Install it with:\n  sudo apt install nethogs")


def write_pid_file(real_home: Path):
    pid_file = real_home / ".local" / "share" / "netmonitor" / "monitor.pid"
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(os.getpid()))
    return pid_file


def run(interface: str | None, verbose: bool):
    check_nethogs_installed()
    real_home = resolve_real_home()

    # Make sure db.py writes to the real user's home, not root's.
    db.DB_PATH = real_home / ".local" / "share" / "netmonitor" / "netmonitor.db"

    pid_file = write_pid_file(real_home)

    cmd = ["nethogs", "-t"] + ([interface] if interface else [])
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

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
                                db.insert_sample(conn, s.process, interface, s.down_bytes, s.up_bytes)
                        written += len(samples)
                        if verbose:
                            print(f"[{time.strftime('%H:%M:%S')}] wrote {len(samples)} samples (total: {written})")
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
        if pid_file.exists():
            pid_file.unlink()


def main():
    ap = argparse.ArgumentParser(description="Collect per-process bandwidth via NetHogs into SQLite.")
    ap.add_argument("--interface", "-i", default=None)
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()

    if os.geteuid() != 0:
        sys.exit("monitor.py must run as root. Try: sudo python3 monitor.py")

    run(args.interface, args.verbose)


if __name__ == "__main__":
    main()
