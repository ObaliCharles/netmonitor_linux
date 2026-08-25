"""
nethogs_parser.py — turns raw `nethogs -t` output into structured samples.

Key lesson learned from testing against real NetHogs output: the "program"
field is NOT a clean file path — for processes like Chrome it's the full
command line, including OTHER paths embedded in flags (e.g.
--render-node-override=/dev/dri/renderD128). So we can't just split on the
last "/". Instead we split on the first SPACE to isolate the executable
path from its flags, then take that path's last segment.
"""

import re
from dataclasses import dataclass

LINE_RE = re.compile(r"^(.+)/(\d+)/(\d+)\s+([\d.]+)\s+([\d.]+)\s*$")
KB_TO_BYTES = 1024


@dataclass
class ProcSample:
    process: str
    pid: str
    down_bytes: int   # received, this interval
    up_bytes: int      # sent, this interval


def short_name(cmd_field: str) -> str:
    """Turn NetHogs' raw process field into a short display name."""
    if cmd_field.strip().lower().startswith("unknown"):
        return "unknown"
    executable_path = cmd_field.split(" ")[0]  # drop flags, keep just the path
    parts = executable_path.rstrip("/").split("/")
    return parts[-1] if parts and parts[-1] else executable_path


def parse_line(line: str) -> ProcSample | None:
    line = line.rstrip("\n")
    if not line or line.startswith("Refreshing") or line.startswith("Unknown connection"):
        return None
    m = LINE_RE.match(line)
    if not m:
        return None
    cmd_field, pid, _uid, sent_kbps, recv_kbps = m.groups()
    return ProcSample(
        process=short_name(cmd_field),
        pid=pid,
        down_bytes=round(float(recv_kbps) * KB_TO_BYTES),
        up_bytes=round(float(sent_kbps) * KB_TO_BYTES),
    )


def parse_batch(lines: list[str]) -> list[ProcSample]:
    out = []
    for line in lines:
        s = parse_line(line)
        if s is not None:
            out.append(s)
    return out
