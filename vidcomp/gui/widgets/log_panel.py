"""In-app log panel — receives lines from a logging.Handler."""

from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QPlainTextEdit, QWidget


class _QtLogBridge(QObject):
    """Bridge from logging.Handler (any thread) to a Qt signal (thread-safe)."""

    line = Signal(str)


class QtLogHandler(logging.Handler):
    """A logging.Handler that emits each line through a Qt signal."""

    def __init__(self) -> None:
        super().__init__()
        self.bridge = _QtLogBridge()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self.bridge.line.emit(msg)
        except Exception:  # noqa: BLE001
            self.handleError(record)


class LogPanel(QPlainTextEdit):
    """Read-only log panel that auto-scrolls."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(5000)
        self.setPlaceholderText("Log output appears here.")

    def append_line(self, line: str) -> None:
        self.appendPlainText(line)

    def attach_handler(self, handler: QtLogHandler) -> None:
        """Connect the bridge so log lines flow into the panel."""
        handler.bridge.line.connect(self.append_line, Qt.QueuedConnection)
