"""Bottom summary bar: stats + Select/Delete buttons + keep-rule combo."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ...config import (
    AppConfig,
    KEEP_HIGHEST_RES,
    KEEP_LARGEST,
    KEEP_LONGEST,
    KEEP_MANUAL,
    KEEP_NEWEST,
    KEEP_OLDEST,
)
from ._helpers import format_bytes


class SummaryBar(QWidget):
    """Footer bar with reclaimable-space stats and primary actions."""

    select_duplicates = Signal()
    delete_selected = Signal()
    keep_rule_changed = Signal(str)

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 8)
        layout.setSpacing(8)

        self.stats_label = QLabel("No scan yet.")
        layout.addWidget(self.stats_label, 1)

        layout.addWidget(QLabel("Keep:"))
        self.keep_combo = QComboBox()
        for rule_id, label in (
            (KEEP_HIGHEST_RES, "Highest resolution"),
            (KEEP_LARGEST, "Largest file size"),
            (KEEP_LONGEST, "Longest duration"),
            (KEEP_NEWEST, "Newest"),
            (KEEP_OLDEST, "Oldest"),
            (KEEP_MANUAL, "Manual selection"),
        ):
            self.keep_combo.addItem(label, rule_id)
        idx = self.keep_combo.findData(self._config.keep_rule)
        if idx >= 0:
            self.keep_combo.setCurrentIndex(idx)
        self.keep_combo.currentIndexChanged.connect(self._on_keep_changed)
        layout.addWidget(self.keep_combo)

        self.select_btn = QPushButton("Select duplicates")
        self.delete_btn = QPushButton("Delete selected…")
        self.delete_btn.setEnabled(False)
        self.select_btn.setEnabled(False)

        self.select_btn.clicked.connect(self.select_duplicates.emit)
        self.delete_btn.clicked.connect(self.delete_selected.emit)
        layout.addWidget(self.select_btn)
        layout.addWidget(self.delete_btn)

    # ------------------------------------------------------------------
    def update_summary(
        self,
        group_count: int,
        duplicate_count: int,
        reclaimable_bytes: int,
        selected_count: int = 0,
        selected_bytes: int = 0,
    ) -> None:
        if group_count == 0:
            self.stats_label.setText("No duplicates found.")
            self.select_btn.setEnabled(False)
            self.delete_btn.setEnabled(False)
            return
        text = (
            f"<b>{group_count}</b> groups · <b>{duplicate_count}</b> duplicates · "
            f"<b>{format_bytes(reclaimable_bytes)}</b> reclaimable"
        )
        if selected_count:
            text += f"    |    Selected: <b>{selected_count}</b> file(s) · " \
                    f"<b>{format_bytes(selected_bytes)}</b>"
        self.stats_label.setText(text)
        self.select_btn.setEnabled(True)
        self.delete_btn.setEnabled(selected_count > 0)

    def selected_keep_rule(self) -> str:
        return self.keep_combo.currentData()

    def set_keep_rule(self, rule_id: str) -> None:
        idx = self.keep_combo.findData(rule_id)
        if idx >= 0:
            self.keep_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    def _on_keep_changed(self, _idx: int) -> None:
        rule = self.keep_combo.currentData()
        self._config.keep_rule = rule
        self.keep_rule_changed.emit(rule)
