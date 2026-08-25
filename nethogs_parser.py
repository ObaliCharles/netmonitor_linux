"""
nethogs_parser.py — turns raw `nethogs -t` output into structured samples.

`nethogs -t` (trace mode) prints a batch of lines every couple of seconds,
one line per process, formatted as:

    <program>/<pid>/<uid>\t<sent_KBps>\t<received_KBps>

separated by "Refreshing:" marker lines, e.g.:

    Refreshing:
    /usr/lib/firefox/firefox/4821/1000     12.340 340.120
    /usr/bin/code/9931/1000        0.410   2.003
    unknown TCP/0/0 0.000   0.000

Notes:
  - Values are KB/sec (kibibytes, 1024 bytes) *for that poll interval*,
    not cumulative — that's why we treat each parsed line as a delta and
    write it straight into the samples table rather than trying to diff
    against a previous reading ourselves.
  - "unknown TCP/0/0" shows up for traffic NetHogs can't attribute to a
    process (e.g. already-closed connections); we keep it but label it
    "unknown" so it doesn't get silently dropped from totals.
  - The program field is a full path plus /pid/uid. We strip the path
    down to a short display name (e.g. "/usr/lib/firefox/firefox" -> "firefox")
    so totals for the same app aggregate together instead of splitting by PID.
"""

import re
from dataclasses import dataclass

LINE_RE = re.compile(r"^(.+)/(\d+)/(\d+)\s+([\d.]+)\s+([\d.]+)\s*$")
KB_TO_BYTES = 1024


@dataclass
class ProcSample:
    process: str      # short display name, e.g. "firefox"
    pid: str
    down_bytes: int    # received, this interval
    up_bytes: int       # sent, this interval


def short_name(path_field: str) -> str:
    """'/usr/lib/firefox/firefox' -> 'firefox'; 'unknown TCP' -> 'unknown'."""
    if path_field.strip().lower().startswith("unknown"):
        return "unknown"
    # take the last path component; fall back to the raw field if there's no slash
    parts = path_field.rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else path_field


def parse_line(line: str) -> ProcSample | None:
    line = line.rstrip("\n")
    if not line or line.startswith("Refreshing"):
        return None
    m = LINE_RE.match(line)
    if not m:
        return None
    prog_path, pid, _uid, sent_kbps, recv_kbps = m.groups()
    return ProcSample(
        process=short_name(prog_path),
        pid=pid,
        down_bytes=round(float(recv_kbps) * KB_TO_BYTES),
        up_bytes=round(float(sent_kbps) * KB_TO_BYTES),
    )


def parse_batch(lines: list[str]) -> list[ProcSample]:
    """Parse one refresh batch (list of lines between 'Refreshing:' markers)."""
    out = []
    for line in lines:
        s = parse_line(line)
        if s is not None:
            out.append(s)
    return out
