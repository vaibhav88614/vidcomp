"""Light/dark Qt stylesheets and palette helpers."""

from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

_DARK_QSS = """
QWidget { font-size: 10pt; }
QGroupBox {
    border: 1px solid #3a3f4b; border-radius: 6px; margin-top: 10px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #9aa4b2; }
QPushButton {
    background: #2d3340; border: 1px solid #3a3f4b; border-radius: 5px; padding: 6px 12px;
}
QPushButton:hover { background: #38404f; }
QPushButton:disabled { color: #6b7280; }
QPushButton#primary { background: #2563eb; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #b91c1c; border: none; color: white; font-weight: 600; }
QPushButton#danger:hover { background: #991b1b; }
QFrame#card { background: #232936; border: 1px solid #333a48; border-radius: 8px; }
QLabel#keepBadge { background: #166534; color: #dcfce7; border-radius: 4px; padding: 1px 6px; }
QProgressBar { border: 1px solid #3a3f4b; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 4px; }
QScrollArea { border: none; }
"""

_LIGHT_QSS = """
QWidget { font-size: 10pt; }
QGroupBox {
    border: 1px solid #d0d5dd; border-radius: 6px; margin-top: 10px; padding-top: 8px;
}
QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 4px; color: #475467; }
QPushButton {
    background: #f2f4f7; border: 1px solid #d0d5dd; border-radius: 5px; padding: 6px 12px;
}
QPushButton:hover { background: #e4e7ec; }
QPushButton:disabled { color: #98a2b3; }
QPushButton#primary { background: #2563eb; border: none; color: white; font-weight: 600; }
QPushButton#primary:hover { background: #1d4ed8; }
QPushButton#danger { background: #dc2626; border: none; color: white; font-weight: 600; }
QPushButton#danger:hover { background: #b91c1c; }
QFrame#card { background: #ffffff; border: 1px solid #e4e7ec; border-radius: 8px; }
QLabel#keepBadge { background: #dcfce7; color: #166534; border-radius: 4px; padding: 1px 6px; }
QProgressBar { border: 1px solid #d0d5dd; border-radius: 5px; text-align: center; }
QProgressBar::chunk { background: #2563eb; border-radius: 4px; }
QScrollArea { border: none; }
"""


def apply_theme(app: QApplication, dark: bool) -> None:
    """Apply a light or dark Fusion-based theme to the whole application."""
    app.setStyle("Fusion")
    palette = QPalette()
    if dark:
        palette.setColor(QPalette.Window, QColor(26, 30, 38))
        palette.setColor(QPalette.WindowText, QColor(226, 232, 240))
        palette.setColor(QPalette.Base, QColor(30, 35, 44))
        palette.setColor(QPalette.AlternateBase, QColor(36, 41, 54))
        palette.setColor(QPalette.Text, QColor(226, 232, 240))
        palette.setColor(QPalette.Button, QColor(45, 51, 64))
        palette.setColor(QPalette.ButtonText, QColor(226, 232, 240))
        palette.setColor(QPalette.Highlight, QColor(37, 99, 235))
        palette.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        palette.setColor(QPalette.ToolTipBase, QColor(36, 41, 54))
        palette.setColor(QPalette.ToolTipText, QColor(226, 232, 240))
        palette.setColor(QPalette.PlaceholderText, QColor(120, 130, 145))
        app.setPalette(palette)
        app.setStyleSheet(_DARK_QSS)
    else:
        app.setPalette(app.style().standardPalette())
        app.setStyleSheet(_LIGHT_QSS)
