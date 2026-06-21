"""Tiny helper functions shared by multiple widgets."""

from __future__ import annotations

from PySide6.QtWidgets import QFrame, QWidget


def h_separator(parent: QWidget | None = None) -> QFrame:
    """A horizontal divider line."""
    f = QFrame(parent)
    f.setFrameShape(QFrame.HLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def v_separator(parent: QWidget | None = None) -> QFrame:
    f = QFrame(parent)
    f.setFrameShape(QFrame.VLine)
    f.setFrameShadow(QFrame.Sunken)
    return f


def format_duration(seconds: float | None) -> str:
    """Format a duration in seconds as ``HH:MM:SS`` (or ``MM:SS`` if < 1h)."""
    if seconds is None or seconds <= 0:
        return "—"
    s = int(round(seconds))
    h, rem = divmod(s, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def format_bytes(n: int | float | None) -> str:
    """Humanise a byte count without requiring the ``humanize`` package."""
    if n is None:
        return "—"
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "—"
    if n < 0:
        return "—"
    units = ("B", "KB", "MB", "GB", "TB", "PB")
    for unit in units:
        if n < 1024 or unit == units[-1]:
            if unit == "B":
                return f"{int(n)} {unit}"
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def elide_path(path: str, max_len: int = 80) -> str:
    """Middle-elide a long path so the head and tail remain visible."""
    if len(path) <= max_len:
        return path
    keep = (max_len - 3) // 2
    return f"{path[:keep]}…{path[-keep:]}"
