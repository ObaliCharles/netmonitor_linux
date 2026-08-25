#!/usr/bin/env python3
"""
gui.py — Network Data Monitor desktop app.

Runs unprivileged. Reads netmonitor.db directly for display. When you click
"Start Monitoring" it launches monitor.py as root via `pkexec` (a graphical
password prompt — the standard, safe way desktop apps request elevation on
Linux, instead of the whole GUI running as root).
"""

import csv
import os
import shutil
import subprocess
import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk, messagebox, filedialog

import db

if getattr(sys, "frozen", False):
    # Running as a compiled PyInstaller binary — the collector is a sibling
    # binary (netmonitor-collector) next to this executable, not a .py file.
    APP_DIR = Path(sys.executable).resolve().parent
    COLLECTOR_CMD = [str(APP_DIR / "netmonitor-collector")]
else:
    # Running as a plain script during development.
    APP_DIR = Path(__file__).resolve().parent
    COLLECTOR_CMD = [sys.executable, str(APP_DIR / "monitor.py")]

PID_FILE = Path.home() / ".local" / "share" / "netmonitor" / "monitor.pid"

PERIODS = {
    "Today": lambda: _start_of_today(),
    "7 Days": lambda: time.time() - 7 * 86400,
    "30 Days": lambda: time.time() - 30 * 86400,
    "Lifetime": lambda: None,
}


def _start_of_today() -> float:
    import datetime
    now = datetime.datetime.now()
    return datetime.datetime(now.year, now.month, now.day).timestamp()


def human_bytes(n) -> str:
    n = float(n)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if n < 1024:
            return f"{n:.2f} {unit}" if unit != "B" else f"{int(n)} B"
        n /= 1024
    return f"{n:.2f} PB"


def monitor_running() -> tuple[bool, int | None]:
    if not PID_FILE.exists():
        return False, None
    try:
        pid = int(PID_FILE.read_text().strip())
    except ValueError:
        return False, None
    try:
        os.kill(pid, 0)  # signal 0: just checks the process exists, doesn't kill it
        return True, pid
    except OSError:
        return False, None


class NetMonitorApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Network Data Monitor")
        self.geometry("640x560")
        self.minsize(560, 480)

        self._build_status_bar()
        self._build_summary()
        self._build_apps_table()
        self._build_buttons()

        self.refresh()
        self.after(5000, self._auto_refresh)  # refresh every 5s

    # ---------- UI construction ----------

    def _build_status_bar(self):
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="x")
        self.status_var = tk.StringVar(value="Checking monitor status…")
        ttk.Label(frame, textvariable=self.status_var, font=("Sans", 10, "bold")).pack(side="left")

        self.iface_var = tk.StringVar(value=self._default_interface())
        ttk.Label(frame, text="Interface:").pack(side="right", padx=(10, 2))
        ttk.Entry(frame, textvariable=self.iface_var, width=10).pack(side="right")

    def _build_summary(self):
        frame = ttk.LabelFrame(self, text="Usage Summary", padding=10)
        frame.pack(fill="x", padx=10, pady=5)
        self.summary_labels = {}
        cols = ttk.Frame(frame)
        cols.pack(fill="x")
        for i, label in enumerate(["Today", "7 Days", "30 Days", "Lifetime"]):
            col = ttk.Frame(cols, padding=8, relief="groove")
            col.grid(row=0, column=i, padx=5, sticky="nsew")
            cols.columnconfigure(i, weight=1)
            ttk.Label(col, text=label, font=("Sans", 9, "bold")).pack()
            down_lbl = ttk.Label(col, text="↓ 0 B")
            up_lbl = ttk.Label(col, text="↑ 0 B")
            down_lbl.pack()
            up_lbl.pack()
            self.summary_labels[label] = (down_lbl, up_lbl)

    def _build_apps_table(self):
        frame = ttk.LabelFrame(self, text="Application Usage", padding=10)
        frame.pack(fill="both", expand=True, padx=10, pady=5)

        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top, text="Period:").pack(side="left")
        self.period_var = tk.StringVar(value="Today")
        period_combo = ttk.Combobox(top, textvariable=self.period_var, values=list(PERIODS.keys()),
                                     state="readonly", width=14)
        period_combo.pack(side="left", padx=5)
        period_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh())

        columns = ("app", "down", "up", "total")
        self.tree = ttk.Treeview(frame, columns=columns, show="headings", height=12)
        for col, label, width in [("app", "Application", 200), ("down", "Download", 100),
                                   ("up", "Upload", 100), ("total", "Total", 100)]:
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w" if col == "app" else "e")
        self.tree.pack(fill="both", expand=True, pady=(8, 0))

    def _build_buttons(self):
        frame = ttk.Frame(self, padding=10)
        frame.pack(fill="x")
        self.start_btn = ttk.Button(frame, text="Start Monitoring", command=self.start_monitoring)
        self.start_btn.pack(side="left", padx=3)
        self.stop_btn = ttk.Button(frame, text="Stop Monitoring", command=self.stop_monitoring)
        self.stop_btn.pack(side="left", padx=3)
        ttk.Button(frame, text="Refresh", command=self.refresh).pack(side="left", padx=3)
        ttk.Button(frame, text="Export CSV", command=self.export_csv).pack(side="right", padx=3)
        ttk.Button(frame, text="Reset Stats", command=self.reset_stats).pack(side="right", padx=3)

    # ---------- helpers ----------

    def _default_interface(self) -> str:
        # Best-effort guess: pick the first non-loopback interface reported by `ip -o link`.
        try:
            out = subprocess.run(["ip", "-o", "link", "show"], capture_output=True, text=True, timeout=2).stdout
            for line in out.splitlines():
                name = line.split(":")[1].strip()
                if name != "lo" and "@" not in name:
                    return name
        except Exception:
            pass
        return ""

    # ---------- actions ----------

    def start_monitoring(self):
        running, _ = monitor_running()
        if running:
            messagebox.showinfo("Already running", "Monitoring is already active.")
            return
        if shutil.which("pkexec") is None:
            messagebox.showerror("pkexec not found",
                                  "pkexec is required to start the collector with elevated privileges.\n"
                                  "Install policykit-1 (usually preinstalled on Pop!_OS).")
            return
        iface = self.iface_var.get().strip()
        cmd = ["pkexec"] + COLLECTOR_CMD
        if iface:
            cmd += ["--interface", iface]
        subprocess.Popen(cmd)
        self.after(2000, self.refresh)  # give it a moment to write the PID file

    def stop_monitoring(self):
        running, pid = monitor_running()
        if not running:
            messagebox.showinfo("Not running", "Monitoring isn't currently active.")
            return
        if shutil.which("pkexec") is None:
            messagebox.showerror("pkexec not found", "Can't stop a root process without pkexec.")
            return
        subprocess.run(["pkexec", "kill", "-TERM", str(pid)])
        self.after(1000, self.refresh)

    def export_csv(self):
        path = filedialog.asksaveasfilename(defaultextension=".csv", initialfile="netmonitor_export.csv")
        if not path:
            return
        since = PERIODS[self.period_var.get()]()
        with db.connect() as conn:
            rows = db.all_rows_for_export(conn, since)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["timestamp_utc", "date", "process", "interface", "down_bytes", "up_bytes"])
            for row in rows:
                w.writerow(row)
        messagebox.showinfo("Exported", f"Exported {len(rows)} rows to {path}")

    def reset_stats(self):
        if not messagebox.askyesno("Reset stats", "This permanently deletes all recorded stats. Continue?"):
            return
        with db.connect() as conn:
            db.reset_stats(conn)
        self.refresh()

    def refresh(self):
        running, pid = monitor_running()
        self.status_var.set(f"● Monitoring active (pid {pid})" if running else "○ Monitoring stopped")

        with db.connect() as conn:
            for label, fn in PERIODS.items():
                since = fn()
                totals = db.totals_since(conn, since)
                down_lbl, up_lbl = self.summary_labels[label]
                down_lbl.config(text=f"↓ {human_bytes(totals['down'])}")
                up_lbl.config(text=f"↑ {human_bytes(totals['up'])}")

            since = PERIODS[self.period_var.get()]()
            rows = db.per_app_since(conn, since, limit=100)

        self.tree.delete(*self.tree.get_children())
        for r in rows:
            self.tree.insert("", "end", values=(
                r["process"], human_bytes(r["down"]), human_bytes(r["up"]), human_bytes(r["total"])
            ))

    def _auto_refresh(self):
        self.refresh()
        self.after(5000, self._auto_refresh)


if __name__ == "__main__":
    app = NetMonitorApp()
    app.mainloop()
