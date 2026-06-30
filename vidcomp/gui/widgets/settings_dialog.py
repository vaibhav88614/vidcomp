"""Application settings dialog: delete mode, paths, keep rule, workers."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import AppConfig
from ...core.models import DeleteMode, KeepRule

_KEEP_LABELS = {
    KeepRule.HIGHEST_RESOLUTION: "Keep highest resolution",
    KeepRule.LARGEST_SIZE: "Keep largest file size",
    KeepRule.LONGEST_DURATION: "Keep longest duration",
    KeepRule.NEWEST: "Keep newest file",
    KeepRule.OLDEST: "Keep oldest file",
    KeepRule.MANUAL: "Manual selection only",
}

_DELETE_LABELS = {
    DeleteMode.RECYCLE_BIN: "Send to Recycle Bin (reversible)",
    DeleteMode.QUARANTINE: "Move to quarantine folder",
    DeleteMode.PERMANENT: "Permanent delete (extra confirmation)",
}


class SettingsDialog(QDialog):
    """Edits the persistent :class:`AppConfig`."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VidComp Settings")
        self.setMinimumWidth(560)
        self._config = config
        self._build()
        self._load()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        form = QFormLayout()

        self.delete_combo = QComboBox()
        for mode, label in _DELETE_LABELS.items():
            self.delete_combo.addItem(label, mode.value)
        form.addRow("Delete mode:", self.delete_combo)

        self.keep_combo = QComboBox()
        for rule, label in _KEEP_LABELS.items():
            self.keep_combo.addItem(label, rule.value)
        form.addRow("Keep rule:", self.keep_combo)

        self.quarantine_edit, q_row = self._path_picker(directory=True)
        form.addRow("Quarantine folder:", q_row)

        self.cache_edit, c_row = self._path_picker(directory=True)
        form.addRow("Cache folder:", c_row)

        self.thumb_edit, t_row = self._path_picker(directory=True)
        form.addRow("Thumbnail cache folder:", t_row)

        self.thumb_budget = QSpinBox()
        self.thumb_budget.setRange(16, 100000)
        self.thumb_budget.setSuffix(" MB")
        form.addRow("Thumbnail cache budget:", self.thumb_budget)

        self.workers_spin = QSpinBox()
        self.workers_spin.setRange(1, 64)
        form.addRow("Worker threads:", self.workers_spin)

        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", True)
        self.theme_combo.addItem("Light", False)
        form.addRow("Theme:", self.theme_combo)

        root.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _path_picker(self, directory: bool) -> tuple[QLineEdit, QWidget]:
        edit = QLineEdit()
        btn = QPushButton("Browse...")

        def browse() -> None:
            if directory:
                p = QFileDialog.getExistingDirectory(self, "Choose folder", edit.text() or os.path.expanduser("~"))
            else:
                p, _ = QFileDialog.getOpenFileName(self, "Choose file", edit.text())
            if p:
                edit.setText(p)

        btn.clicked.connect(browse)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        h.addWidget(edit, 1)
        h.addWidget(btn)
        return edit, row

    def _load(self) -> None:
        c = self._config
        self.delete_combo.setCurrentIndex(max(0, self.delete_combo.findData(c.delete_mode.value)))
        self.keep_combo.setCurrentIndex(max(0, self.keep_combo.findData(c.keep_rule.value)))
        self.quarantine_edit.setText(c.quarantine_folder)
        self.cache_edit.setText(c.cache_dir)
        self.thumb_edit.setText(c.thumbnail_dir)
        self.thumb_budget.setValue(int(c.thumbnail_cache_mb))
        self.workers_spin.setValue(int(c.worker_count))
        self.theme_combo.setCurrentIndex(0 if c.dark_mode else 1)

    def apply_to_config(self) -> None:
        c = self._config
        c.delete_mode = DeleteMode(self.delete_combo.currentData())
        c.keep_rule = KeepRule(self.keep_combo.currentData())
        c.quarantine_folder = self.quarantine_edit.text().strip() or c.quarantine_folder
        c.cache_dir = self.cache_edit.text().strip() or c.cache_dir
        c.thumbnail_dir = self.thumb_edit.text().strip() or c.thumbnail_dir
        c.thumbnail_cache_mb = self.thumb_budget.value()
        c.worker_count = self.workers_spin.value()
        c.scan_options.worker_count = self.workers_spin.value()
        c.dark_mode = bool(self.theme_combo.currentData())
