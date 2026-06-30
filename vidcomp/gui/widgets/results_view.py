"""Grouped results display: cards with thumbnails, info and selection."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ...core.keep_rules import auto_select_duplicates
from ...core.models import DuplicateGroup, KeepRule, METHOD_LABELS, VideoFile
from ...core.utils import (
    format_timestamp,
    human_bitrate,
    human_duration,
    human_size,
)

_THUMB_W = 160
_THUMB_H = 90


class FileRow(QFrame):
    """A single file inside a duplicate group."""

    selectionChanged = Signal()

    def __init__(self, vf: VideoFile, group: DuplicateGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.vf = vf
        self.group = group
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self._build()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.checkbox = QCheckBox()
        self.checkbox.toggled.connect(lambda _: self.selectionChanged.emit())
        layout.addWidget(self.checkbox, 0, Qt.AlignTop)

        self.thumb = QLabel("...")
        self.thumb.setFixedSize(_THUMB_W, _THUMB_H)
        self.thumb.setAlignment(Qt.AlignCenter)
        self.thumb.setStyleSheet("background:#11151c;border:1px solid #2a2f3a;border-radius:4px;")
        layout.addWidget(self.thumb, 0, Qt.AlignTop)

        info = QVBoxLayout()
        info.setSpacing(2)

        name_row = QHBoxLayout()
        self.name_label = QLabel(self.vf.name)
        self.name_label.setStyleSheet("font-weight:600;")
        self.name_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        name_row.addWidget(self.name_label)
        self.keep_badge = QLabel("KEEP")
        self.keep_badge.setObjectName("keepBadge")
        self.keep_badge.setVisible(False)
        name_row.addWidget(self.keep_badge)
        name_row.addStretch(1)
        info.addLayout(name_row)

        self.path_label = QLabel(self.vf.path)
        self.path_label.setStyleSheet("color:#8b94a3;")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        info.addWidget(self.path_label)

        self.meta_label = QLabel(self._meta_text())
        self.meta_label.setWordWrap(True)
        self.meta_label.setStyleSheet("color:#aab2c0;")
        info.addWidget(self.meta_label)

        self.match_label = QLabel(self._match_text())
        self.match_label.setStyleSheet("color:#7aa2f7;")
        self.match_label.setWordWrap(True)
        info.addWidget(self.match_label)

        layout.addLayout(info, 1)

        actions = QVBoxLayout()
        open_btn = QPushButton("Open folder")
        open_btn.clicked.connect(self.open_in_explorer)
        play_btn = QPushButton("Play")
        play_btn.clicked.connect(self.play)
        actions.addWidget(open_btn)
        actions.addWidget(play_btn)
        actions.addStretch(1)
        layout.addLayout(actions, 0)

        if self.vf.thumbnail_path and os.path.isfile(self.vf.thumbnail_path):
            self.set_thumbnail(self.vf.thumbnail_path)

    def _meta_text(self) -> str:
        info = self.vf.info
        parts = [f"{human_size(self.vf.size)} ({self.vf.size:,} bytes)"]
        if info:
            if info.resolution:
                parts.append(f"{info.width}x{info.height}")
            parts.append(human_duration(info.duration) if info.duration else "-")
            if info.video_codec:
                parts.append(info.video_codec)
            if info.fps:
                parts.append(f"{info.fps:.1f} fps")
            parts.append(human_bitrate(info.bitrate))
            if info.audio_channels:
                parts.append(f"{info.audio_channels}ch audio")
        parts.append("modified " + format_timestamp(self.vf.mtime))
        return "  |  ".join(parts)

    def _match_text(self) -> str:
        methods = self.group.methods_for(self.vf.path)
        if not methods:
            return ""
        labels = [METHOD_LABELS[m].split(" - ", 1)[-1] for m in methods]
        return "Matched by: " + ", ".join(labels)

    # --- public ----------------------------------------------------------
    def set_thumbnail(self, path: str) -> None:
        pm = QPixmap(path)
        if not pm.isNull():
            self.thumb.setPixmap(
                pm.scaled(_THUMB_W, _THUMB_H, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            self.thumb.setText("")

    def set_keep(self, is_keep: bool) -> None:
        self.keep_badge.setVisible(is_keep)
        if is_keep:
            self.setStyleSheet("FileRow { border-left: 3px solid #16a34a; }")
        else:
            self.setStyleSheet("")

    def is_checked(self) -> bool:
        return self.checkbox.isChecked()

    def set_checked(self, value: bool) -> None:
        self.checkbox.setChecked(value)

    # --- context actions --------------------------------------------------
    def _show_menu(self, pos) -> None:
        menu = QMenu(self)
        menu.addAction("Open containing folder", self.open_in_explorer)
        menu.addAction("Play in default player", self.play)
        menu.addAction("Copy full path", self._copy_path)
        menu.exec(self.mapToGlobal(pos))

    def open_in_explorer(self) -> None:
        path = self.vf.path
        if not os.path.exists(path):
            return
        try:
            if sys.platform == "win32":
                subprocess.run(["explorer", "/select,", os.path.normpath(path)])
            elif sys.platform == "darwin":
                subprocess.run(["open", "-R", path])
            else:
                subprocess.run(["xdg-open", os.path.dirname(path)])
        except Exception:
            pass

    def play(self) -> None:
        path = self.vf.path
        if not os.path.exists(path):
            return
        try:
            if sys.platform == "win32":
                os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.run(["open", path])
            else:
                subprocess.run(["xdg-open", path])
        except Exception:
            pass

    def _copy_path(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(self.vf.path)


class GroupCard(QFrame):
    """A duplicate group containing several :class:`FileRow` widgets."""

    selectionChanged = Signal()

    def __init__(self, index: int, group: DuplicateGroup, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("card")
        self.group = group
        self.rows: List[FileRow] = []
        self._build(index)

    def _build(self, index: int) -> None:
        layout = QVBoxLayout(self)
        header = QLabel(
            f"Group {index} - {len(self.group.files)} files - "
            f"reclaimable {human_size(self.group.reclaimable)}"
        )
        header.setStyleSheet("font-weight:700;font-size:11pt;")
        layout.addWidget(header)

        for vf in self.group.files:
            row = FileRow(vf, self.group)
            row.selectionChanged.connect(self.selectionChanged)
            row.set_keep(vf.path == self.group.keep_path)
            self.rows.append(row)
            layout.addWidget(row)

    def update_keep(self) -> None:
        for row in self.rows:
            row.set_keep(row.vf.path == self.group.keep_path)

    def selected_paths(self) -> List[str]:
        return [r.vf.path for r in self.rows if r.is_checked()]


class ResultsView(QWidget):
    """Scrollable container of all duplicate group cards."""

    selectionChanged = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.cards: List[GroupCard] = []
        self._rows_by_path: Dict[str, FileRow] = {}
        self._groups: List[DuplicateGroup] = []
        self._layout = QVBoxLayout(self)
        self._layout.setAlignment(Qt.AlignTop)
        self._placeholder = QLabel("No results yet. Pick a folder and click Scan.")
        self._placeholder.setAlignment(Qt.AlignCenter)
        self._placeholder.setStyleSheet("color:#7b8494;font-size:12pt;padding:40px;")
        self._layout.addWidget(self._placeholder)

    def set_groups(self, groups: List[DuplicateGroup]) -> None:
        self.clear()
        self._groups = groups
        if not groups:
            self._placeholder.setText("No duplicate groups found.")
            self._placeholder.setVisible(True)
            return
        self._placeholder.setVisible(False)
        for i, g in enumerate(groups, start=1):
            card = GroupCard(i, g)
            card.selectionChanged.connect(self.selectionChanged)
            self.cards.append(card)
            for row in card.rows:
                self._rows_by_path[row.vf.path] = row
            self._layout.addWidget(card)

    def clear(self) -> None:
        for card in self.cards:
            card.setParent(None)
            card.deleteLater()
        self.cards.clear()
        self._rows_by_path.clear()
        self._groups = []
        self._placeholder.setVisible(True)

    def groups(self) -> List[DuplicateGroup]:
        return self._groups

    def files(self) -> List[VideoFile]:
        return [row.vf for row in self._rows_by_path.values()]

    def update_thumbnail(self, video_path: str, thumb_path: str) -> None:
        row = self._rows_by_path.get(video_path)
        if row:
            row.set_thumbnail(thumb_path)

    def selected_paths(self) -> List[str]:
        out: List[str] = []
        for card in self.cards:
            out.extend(card.selected_paths())
        return out

    def select_duplicates(self, rule: KeepRule) -> None:
        """Auto-check every duplicate (all but the keeper) in every group."""
        for card in self.cards:
            to_select = set(auto_select_duplicates(card.group, rule))
            for row in card.rows:
                row.set_checked(row.vf.path in to_select)
        self.selectionChanged.emit()

    def clear_selection(self) -> None:
        for row in self._rows_by_path.values():
            row.set_checked(False)
        self.selectionChanged.emit()

    def apply_keep_rule_display(self) -> None:
        for card in self.cards:
            card.update_keep()
