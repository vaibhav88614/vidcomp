"""Progress panel: stage label, file in flight, progress bar, ETA."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.models import ScanProgress
from ._helpers import elide_path, format_duration


class ProgressPanel(QWidget):
    """Compact two-row progress display."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        self.stage_label = QLabel("Idle")
        self.stage_label.setProperty("role", "subtle")

        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        self.counts_label = QLabel("0 / 0")
        self.counts_label.setMinimumWidth(120)
        self.counts_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.eta_label = QLabel("elapsed 0s · ETA —")
        self.eta_label.setMinimumWidth(220)
        self.eta_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        bar_row.addWidget(self.bar, 1)
        bar_row.addWidget(self.counts_label)
        bar_row.addWidget(self.eta_label)

        self.current_file_label = QLabel("")
        self.current_file_label.setProperty("role", "subtle")
        self.current_file_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        layout.addWidget(self.stage_label)
        layout.addLayout(bar_row)
        layout.addWidget(self.current_file_label)

    # ------------------------------------------------------------------
    def update_progress(self, p: ScanProgress) -> None:
        self.stage_label.setText(p.stage)
        if p.total > 0:
            self.bar.setRange(0, p.total)
            self.bar.setValue(min(p.current, p.total))
            pct = int(round(p.fraction * 100))
            self.bar.setFormat(f"{pct}%")
            self.counts_label.setText(f"{p.current:,} / {p.total:,}")
        else:
            self.bar.setRange(0, 0)  # indeterminate
            self.counts_label.setText("")

        elapsed = format_duration(p.elapsed_sec)
        eta = format_duration(p.eta_sec) if p.eta_sec else "—"
        skipped = f" · {p.skipped} skipped" if p.skipped else ""
        self.eta_label.setText(f"elapsed {elapsed} · ETA {eta}{skipped}")

        if p.current_file:
            self.current_file_label.setText(elide_path(p.current_file, 140))
        else:
            self.current_file_label.setText("")

    def reset(self) -> None:
        self.stage_label.setText("Idle")
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setFormat("%p%")
        self.counts_label.setText("0 / 0")
        self.eta_label.setText("elapsed 0s · ETA —")
        self.current_file_label.setText("")
