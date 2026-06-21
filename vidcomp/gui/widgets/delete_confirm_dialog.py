"""Confirmation dialog shown before any deletion."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from ...config import DELETE_PERMANENT, DELETE_QUARANTINE, DELETE_RECYCLE
from ._helpers import format_bytes


_MODE_LABELS = {
    DELETE_RECYCLE: "Send to Recycle Bin (reversible)",
    DELETE_QUARANTINE: "Move to quarantine folder",
    DELETE_PERMANENT: "PERMANENTLY delete (cannot be undone)",
}


class DeleteConfirmDialog(QDialog):
    """Modal confirmation before a deletion batch.

    For :data:`DELETE_PERMANENT` the user must additionally type ``DELETE`` to
    enable the OK button.
    """

    def __init__(
        self,
        count: int,
        bytes_to_free: int,
        mode: str,
        quarantine_path: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm deletion")
        self.setMinimumWidth(420)
        self._mode = mode

        layout = QVBoxLayout(self)
        msg = QLabel(
            f"<b>{count}</b> file(s) selected for deletion.<br>"
            f"This will free approximately <b>{format_bytes(bytes_to_free)}</b>.<br><br>"
            f"<b>Mode:</b> {_MODE_LABELS.get(mode, mode)}"
        )
        msg.setWordWrap(True)
        layout.addWidget(msg)

        if mode == DELETE_QUARANTINE and quarantine_path:
            layout.addWidget(QLabel(f"<i>Quarantine folder:</i> {quarantine_path}"))

        if mode == DELETE_PERMANENT:
            warning = QLabel(
                "<b style='color:#c62828'>This action cannot be undone.</b><br>"
                "Type <code>DELETE</code> below to confirm:"
            )
            warning.setWordWrap(True)
            layout.addWidget(warning)
            self.confirm_edit = QLineEdit()
            self.confirm_edit.textChanged.connect(self._on_confirm_text)
            layout.addWidget(self.confirm_edit)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._ok_btn = btns.button(QDialogButtonBox.Ok)
        if mode == DELETE_PERMANENT:
            self._ok_btn.setEnabled(False)
            self._ok_btn.setText("Delete permanently")
        else:
            self._ok_btn.setText("Delete")
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _on_confirm_text(self, txt: str) -> None:
        self._ok_btn.setEnabled(txt.strip() == "DELETE")
