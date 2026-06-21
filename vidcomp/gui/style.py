"""Light/dark-aware Qt styling helpers."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QPalette


def is_dark_theme() -> bool:
    """Detect whether the current Qt palette is a dark theme."""
    app = QGuiApplication.instance()
    if app is None:
        return False
    pal = app.palette()
    base = pal.color(QPalette.Window)
    # Standard luminance heuristic.
    luminance = 0.299 * base.red() + 0.587 * base.green() + 0.114 * base.blue()
    return luminance < 128


def app_qss() -> str:
    """Return a stylesheet string that adapts mildly to light/dark.

    We intentionally keep this minimal so Qt's native style still shows through.
    """
    dark = is_dark_theme()
    if dark:
        card_bg = "#2b2b2b"
        card_border = "#3c3c3c"
        keeper_bg = "#1e3a1e"
        keeper_border = "#3e7e3e"
    else:
        card_bg = "#ffffff"
        card_border = "#d0d0d0"
        keeper_bg = "#e8f6e8"
        keeper_border = "#4caf50"

    return f"""
    QTreeWidget {{
        alternate-background-color: rgba(127,127,127,32);
    }}
    QTreeWidget::item {{
        padding: 4px;
    }}
    QLabel[role="title"] {{
        font-size: 14px;
        font-weight: bold;
    }}
    QLabel[role="subtle"] {{
        color: #888888;
    }}
    QFrame[role="keeper"] {{
        background-color: {keeper_bg};
        border: 1px solid {keeper_border};
        border-radius: 4px;
    }}
    QFrame[role="card"] {{
        background-color: {card_bg};
        border: 1px solid {card_border};
        border-radius: 4px;
    }}
    QGroupBox {{
        margin-top: 8px;
        font-weight: bold;
    }}
    QGroupBox::title {{
        subcontrol-origin: margin;
        left: 8px;
        padding: 0 4px;
    }}
    QPushButton#primary {{
        font-weight: bold;
        padding: 6px 18px;
    }}
    """
