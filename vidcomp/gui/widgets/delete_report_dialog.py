"""Modal report after a deletion batch — what succeeded, what failed, why."""

from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPlainTextEdit,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.models import DeletionReport
from ._helpers import format_bytes


class DeleteReportDialog(QDialog):
    """Shows successes and failures with their reasons."""

    def __init__(self, report: DeletionReport, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Deletion complete")
        self.setMinimumSize(640, 420)

        layout = QVBoxLayout(self)
        ok = len(report.succeeded)
        bad = len(report.failed)
        summary = QLabel(
            f"<b>{ok}</b> file(s) deleted · "
            f"<b>{bad}</b> failed · "
            f"<b>{format_bytes(report.bytes_reclaimed)}</b> reclaimed."
        )
        layout.addWidget(summary)

        tabs = QTabWidget()
        layout.addWidget(tabs, 1)

        ok_text = QPlainTextEdit()
        ok_text.setReadOnly(True)
        ok_text.setPlainText(
            "\n".join(
                f"{r.path}    →  {r.target or 'deleted'}"
                for r in report.succeeded
            ) or "(none)"
        )
        tabs.addTab(ok_text, f"Succeeded ({ok})")

        bad_text = QPlainTextEdit()
        bad_text.setReadOnly(True)
        bad_text.setPlainText(
            "\n".join(
                f"{r.path}\n    ERROR: {r.error}"
                for r in report.failed
            ) or "(none)"
        )
        tabs.addTab(bad_text, f"Failed ({bad})")

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(btns)
