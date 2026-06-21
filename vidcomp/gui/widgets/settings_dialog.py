"""Settings dialog: delete mode, paths, worker count, etc."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    AppConfig,
    DELETE_PERMANENT,
    DELETE_QUARANTINE,
    DELETE_RECYCLE,
    KEEP_HIGHEST_RES,
    KEEP_LARGEST,
    KEEP_LONGEST,
    KEEP_MANUAL,
    KEEP_NEWEST,
    KEEP_OLDEST,
)


class SettingsDialog(QDialog):
    """Modal settings dialog backed by :class:`AppConfig`."""

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VidComp settings")
        self.setMinimumWidth(560)
        self._config = config

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)

        self.delete_combo = QComboBox()
        self.delete_combo.addItem("Send to Recycle Bin (reversible)", DELETE_RECYCLE)
        self.delete_combo.addItem("Move to quarantine folder", DELETE_QUARANTINE)
        self.delete_combo.addItem("Permanent delete (DESTRUCTIVE)", DELETE_PERMANENT)
        idx = self.delete_combo.findData(config.delete_mode)
        self.delete_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Default delete mode:", self.delete_combo)

        self.quarantine_edit = QLineEdit(config.quarantine_path)
        q_browse = QPushButton("Browse…")
        q_browse.clicked.connect(self._pick_quarantine)
        q_row = QHBoxLayout()
        q_row.addWidget(self.quarantine_edit, 1)
        q_row.addWidget(q_browse)
        q_box = QWidget()
        q_box.setLayout(q_row)
        form.addRow("Quarantine folder:", q_box)

        self.keep_combo = QComboBox()
        for rid, label in (
            (KEEP_HIGHEST_RES, "Highest resolution"),
            (KEEP_LARGEST, "Largest file size"),
            (KEEP_LONGEST, "Longest duration"),
            (KEEP_NEWEST, "Newest"),
            (KEEP_OLDEST, "Oldest"),
            (KEEP_MANUAL, "Manual selection"),
        ):
            self.keep_combo.addItem(label, rid)
        idx = self.keep_combo.findData(config.keep_rule)
        self.keep_combo.setCurrentIndex(idx if idx >= 0 else 0)
        form.addRow("Default keep-rule:", self.keep_combo)

        self.thumb_edit = QLineEdit(config.thumbnail_cache_path)
        t_browse = QPushButton("Browse…")
        t_browse.clicked.connect(self._pick_thumb)
        t_row = QHBoxLayout()
        t_row.addWidget(self.thumb_edit, 1)
        t_row.addWidget(t_browse)
        t_box = QWidget()
        t_box.setLayout(t_row)
        form.addRow("Thumbnail cache:", t_box)

        self.thumb_max_mb = QSpinBox()
        self.thumb_max_mb.setRange(1, 100_000)
        self.thumb_max_mb.setValue(max(1, config.thumbnail_cache_max_bytes // (1024 * 1024)))
        self.thumb_max_mb.setSuffix(" MB")
        form.addRow("Thumbnail cache max:", self.thumb_max_mb)

        self.cache_edit = QLineEdit(config.cache_path)
        c_browse = QPushButton("Browse…")
        c_browse.clicked.connect(self._pick_cache)
        c_row = QHBoxLayout()
        c_row.addWidget(self.cache_edit, 1)
        c_row.addWidget(c_browse)
        c_box = QWidget()
        c_box.setLayout(c_row)
        form.addRow("Cache database:", c_box)

        self.log_edit = QLineEdit(config.log_path)
        form.addRow("Log file:", self.log_edit)

        self.workers = QSpinBox()
        self.workers.setRange(1, 64)
        self.workers.setValue(config.worker_count)
        form.addRow("Worker threads:", self.workers)

        self.pair_cap = QSpinBox()
        self.pair_cap.setRange(10, 1_000_000)
        self.pair_cap.setValue(config.max_pairs_per_bucket)
        form.addRow("Max pairs per bucket:", self.pair_cap)

        layout.addLayout(form)

        # Buttons
        btns = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    # ------------------------------------------------------------------
    def _pick_quarantine(self) -> None:
        start = self.quarantine_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Quarantine folder", start)
        if chosen:
            self.quarantine_edit.setText(chosen)

    def _pick_thumb(self) -> None:
        start = self.thumb_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Thumbnail cache folder", start)
        if chosen:
            self.thumb_edit.setText(chosen)

    def _pick_cache(self) -> None:
        start = self.cache_edit.text().strip() or str(Path.home())
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Cache file", start, "SQLite (*.sqlite *.db);;All files (*.*)"
        )
        if chosen:
            self.cache_edit.setText(chosen)

    # ------------------------------------------------------------------
    def commit_to_config(self) -> None:
        """Write the dialog values back into the bound :class:`AppConfig`."""
        self._config.delete_mode = self.delete_combo.currentData()
        self._config.quarantine_path = self.quarantine_edit.text().strip()
        self._config.keep_rule = self.keep_combo.currentData()
        self._config.thumbnail_cache_path = self.thumb_edit.text().strip()
        self._config.thumbnail_cache_max_bytes = int(self.thumb_max_mb.value()) * 1024 * 1024
        self._config.cache_path = self.cache_edit.text().strip()
        self._config.log_path = self.log_edit.text().strip()
        self._config.worker_count = int(self.workers.value())
        self._config.max_pairs_per_bucket = int(self.pair_cap.value())
