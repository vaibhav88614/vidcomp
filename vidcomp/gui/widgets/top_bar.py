"""Top bar: folder picker, scan-mode selector, Advanced toggle, Scan/Cancel."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QToolButton,
    QWidget,
)

from ...config import PRESET_EASY, PRESET_MEDIUM, PRESET_ROBUST


class TopBar(QWidget):
    """Compact horizontal bar with folder pickers and primary actions."""

    scan_requested = Signal()
    cancel_requested = Signal()
    mode_changed = Signal(str)
    advanced_toggled = Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setSpacing(8)

        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Choose a folder to scan…")
        self.folder_edit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.browse_btn = QPushButton("Browse…")

        self.easy_btn = QRadioButton("Easy")
        self.easy_btn.setToolTip(
            "Fast scan: size, partial hash, full SHA-256, and ffprobe metadata."
        )
        self.medium_btn = QRadioButton("Medium")
        self.medium_btn.setToolTip(
            "Easy + perceptual hash (catches re-encoded / resized copies)."
        )
        self.medium_btn.setChecked(True)
        self.robust_btn = QRadioButton("Robust")
        self.robust_btn.setToolTip(
            "Medium + SSIM / PSNR / VMAF / audio fingerprint (slow but thorough)."
        )

        self._mode_group = QButtonGroup(self)
        self._mode_group.addButton(self.easy_btn)
        self._mode_group.addButton(self.medium_btn)
        self._mode_group.addButton(self.robust_btn)
        self._mode_group.setExclusive(True)

        self.advanced_btn = QToolButton()
        self.advanced_btn.setText("Advanced ▾")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.setToolTip("Show per-method toggles and thresholds.")

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.setDefault(True)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)

        layout.addWidget(self.folder_edit, 1)
        layout.addWidget(self.browse_btn)
        layout.addSpacing(8)
        layout.addWidget(self.easy_btn)
        layout.addWidget(self.medium_btn)
        layout.addWidget(self.robust_btn)
        layout.addSpacing(8)
        layout.addWidget(self.advanced_btn)
        layout.addSpacing(8)
        layout.addWidget(self.scan_btn)
        layout.addWidget(self.cancel_btn)

        # Wiring
        self.browse_btn.clicked.connect(self._on_browse)
        self.scan_btn.clicked.connect(self.scan_requested.emit)
        self.cancel_btn.clicked.connect(self.cancel_requested.emit)
        self.advanced_btn.toggled.connect(
            lambda checked: (
                self.advanced_btn.setText("Advanced ▴" if checked else "Advanced ▾"),
                self.advanced_toggled.emit(checked),
            )
        )
        self.easy_btn.toggled.connect(
            lambda checked: checked and self.mode_changed.emit(PRESET_EASY)
        )
        self.medium_btn.toggled.connect(
            lambda checked: checked and self.mode_changed.emit(PRESET_MEDIUM)
        )
        self.robust_btn.toggled.connect(
            lambda checked: checked and self.mode_changed.emit(PRESET_ROBUST)
        )

    # ------------------------------------------------------------------
    def folder(self) -> str:
        return self.folder_edit.text().strip()

    def set_folder(self, path: str) -> None:
        self.folder_edit.setText(path)

    def set_mode(self, preset: str) -> None:
        if preset == PRESET_EASY:
            self.easy_btn.setChecked(True)
        elif preset == PRESET_MEDIUM:
            self.medium_btn.setChecked(True)
        elif preset == PRESET_ROBUST:
            self.robust_btn.setChecked(True)

    def set_scanning(self, scanning: bool) -> None:
        self.scan_btn.setEnabled(not scanning)
        self.cancel_btn.setEnabled(scanning)
        self.browse_btn.setEnabled(not scanning)
        self.folder_edit.setEnabled(not scanning)
        for btn in (self.easy_btn, self.medium_btn, self.robust_btn):
            btn.setEnabled(not scanning)

    def set_advanced_open(self, open_: bool) -> None:
        self.advanced_btn.setChecked(open_)

    # ------------------------------------------------------------------
    def _on_browse(self) -> None:
        start = self.folder_edit.text().strip() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose folder to scan", start)
        if chosen:
            self.folder_edit.setText(chosen)
