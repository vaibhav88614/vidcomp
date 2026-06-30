"""Small formatting helpers shared across the engine and GUI."""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def human_size(num_bytes: Optional[int]) -> str:
    """Format a byte count as a human-readable string."""
    if num_bytes is None:
        return "-"
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB", "PB"):
        if size < 1024.0 or unit == "PB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.2f} {unit}"
        size /= 1024.0
    return f"{size:.2f} PB"


def human_duration(seconds: Optional[float]) -> str:
    """Format seconds as H:MM:SS / M:SS."""
    if seconds is None:
        return "-"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def human_bitrate(bps: Optional[int]) -> str:
    if not bps:
        return "-"
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.2f} Mbps"
    if bps >= 1000:
        return f"{bps / 1000:.0f} kbps"
    return f"{bps} bps"


def format_timestamp(ts: Optional[float]) -> str:
    if not ts:
        return "-"
    try:
        return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, OverflowError):
        return "-"


def format_eta(seconds: Optional[float]) -> str:
    if seconds is None or seconds < 0:
        return "--:--"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m:02d}:{sec:02d}"
