"""Grouped results tree with thumbnails, checkboxes and a context menu."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional, Set

from PySide6.QtCore import (
    QObject,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    Signal,
)
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QIcon, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QMenu,
    QTreeWidget,
    QTreeWidgetItem,
)

from ...core.cache import Cache
from ...core.models import DuplicateGroup, MediaMetadata, VideoFile
from ...core.thumbnails import ThumbnailCache
from ._helpers import format_bytes, format_duration

LOG = logging.getLogger(__name__)

# Column indices
COL_NAME = 0
COL_SIZE = 1
COL_DURATION = 2
COL_RESOLUTION = 3
COL_CODEC = 4
COL_FPS = 5
COL_MODIFIED = 6
COL_MATCHED_BY = 7
COL_PATH = 8

_THUMB_SIZE = QSize(160, 90)


# ---------------------------------------------------------------------------
class _ThumbSignals(QObject):
    ready = Signal(str, QPixmap)        # video_path, pixmap
    failed = Signal(str)                  # video_path


class _ThumbLoader(QRunnable):
    """Extracts a thumbnail off-thread; emits a signal back to the GUI thread."""

    def __init__(
        self,
        cache: ThumbnailCache,
        video: VideoFile,
        duration_sec: Optional[float],
        signals: _ThumbSignals,
        cancel_event: threading.Event,
    ) -> None:
        super().__init__()
        self._cache = cache
        self._video = video
        self._duration = duration_sec
        self._signals = signals
        self._cancel = cancel_event
        self.setAutoDelete(True)

    def run(self) -> None:  # type: ignore[override]
        if self._cancel.is_set():
            return
        try:
            path = self._cache.get_or_extract(
                self._video.path,
                self._video.size,
                self._video.mtime,
                self._duration,
                cancel_event=self._cancel,
            )
        except Exception as exc:  # noqa: BLE001
            LOG.debug("thumb extract crashed for %s: %s", self._video.path, exc)
            path = None
        if path is None or not path.exists():
            self._signals.failed.emit(self._video.path)
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            self._signals.failed.emit(self._video.path)
            return
        self._signals.ready.emit(self._video.path, pix)


# ---------------------------------------------------------------------------
class ResultTree(QTreeWidget):
    """Tree of duplicate groups → files, with thumbnails and context menu."""

    keeper_changed = Signal()             # emitted when user changes keeper selection

    def __init__(
        self,
        thumbnail_cache: ThumbnailCache,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._thumb_cache = thumbnail_cache
        self._thread_pool = QThreadPool(self)
        self._thread_pool.setMaxThreadCount(2)
        self._cancel_event = threading.Event()
        self._signals = _ThumbSignals()
        self._signals.ready.connect(self._on_thumb_ready)
        self._signals.failed.connect(self._on_thumb_failed)
        self._item_by_path: Dict[str, QTreeWidgetItem] = {}
        self._groups: List[DuplicateGroup] = []
        self._metadata: Dict[str, MediaMetadata] = {}

        self.setColumnCount(9)
        self.setHeaderLabels([
            "File", "Size", "Duration", "Resolution", "Codec",
            "FPS", "Modified", "Matched by", "Path",
        ])
        self.setIconSize(_THUMB_SIZE)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setRootIsDecorated(True)
        self.setUniformRowHeights(False)
        self.setSortingEnabled(False)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.itemChanged.connect(self._on_item_changed)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

        header = self.header()
        header.setSectionResizeMode(COL_NAME, QHeaderView.Stretch)
        for col in (COL_SIZE, COL_DURATION, COL_RESOLUTION, COL_CODEC,
                    COL_FPS, COL_MODIFIED, COL_MATCHED_BY):
            header.setSectionResizeMode(col, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(COL_PATH, QHeaderView.Interactive)
        self.setColumnWidth(COL_PATH, 240)
        self.hideColumn(COL_PATH)  # path shown via tooltip; toggle in context menu

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def cancel_pending_thumbnails(self) -> None:
        self._cancel_event.set()

    def clear_results(self) -> None:
        self.cancel_pending_thumbnails()
        self._thread_pool.waitForDone(50)
        self._cancel_event = threading.Event()
        self._item_by_path.clear()
        self._groups.clear()
        self._metadata.clear()
        self.clear()

    def set_groups(
        self,
        groups: List[DuplicateGroup],
        metadata_map: Dict[str, MediaMetadata],
    ) -> None:
        self.clear_results()
        self._groups = list(groups)
        self._metadata = dict(metadata_map)
        self.setUpdatesEnabled(False)
        try:
            for g in self._groups:
                self._add_group_item(g)
            self.expandAll()
        finally:
            self.setUpdatesEnabled(True)

    def update_keeper(self, group_id: int, keeper_path: Optional[str]) -> None:
        for i in range(self.topLevelItemCount()):
            grp_item = self.topLevelItem(i)
            data = grp_item.data(0, Qt.UserRole)
            if not isinstance(data, dict) or data.get("group_id") != group_id:
                continue
            for j in range(grp_item.childCount()):
                child = grp_item.child(j)
                cdata = child.data(0, Qt.UserRole) or {}
                self._style_keeper(child, cdata.get("path") == keeper_path)
            data["keeper_path"] = keeper_path
            grp_item.setData(0, Qt.UserRole, data)
            return

    def groups(self) -> List[DuplicateGroup]:
        return list(self._groups)

    def selected_for_deletion(self) -> List[str]:
        """Paths whose checkbox is checked."""
        paths: List[str] = []
        for i in range(self.topLevelItemCount()):
            grp = self.topLevelItem(i)
            for j in range(grp.childCount()):
                child = grp.child(j)
                if child.checkState(0) == Qt.Checked:
                    cdata = child.data(0, Qt.UserRole) or {}
                    p = cdata.get("path")
                    if p:
                        paths.append(p)
        return paths

    def protected_paths(self) -> Set[str]:
        out: Set[str] = set()
        for g in self._groups:
            if g.keeper_path:
                out.add(g.keeper_path)
        return out

    def auto_check_duplicates(self) -> int:
        """Check every non-keeper file in every group; return total checked count."""
        n = 0
        self.blockSignals(True)
        try:
            for i in range(self.topLevelItemCount()):
                grp = self.topLevelItem(i)
                gdata = grp.data(0, Qt.UserRole) or {}
                keeper = gdata.get("keeper_path")
                for j in range(grp.childCount()):
                    child = grp.child(j)
                    cdata = child.data(0, Qt.UserRole) or {}
                    is_keeper = cdata.get("path") == keeper
                    state = Qt.Unchecked if is_keeper else Qt.Checked
                    child.setCheckState(0, state)
                    if state == Qt.Checked:
                        n += 1
        finally:
            self.blockSignals(False)
        return n

    def clear_all_checks(self) -> None:
        self.blockSignals(True)
        try:
            for i in range(self.topLevelItemCount()):
                grp = self.topLevelItem(i)
                for j in range(grp.childCount()):
                    grp.child(j).setCheckState(0, Qt.Unchecked)
        finally:
            self.blockSignals(False)

    def selected_size_bytes(self) -> int:
        total = 0
        for i in range(self.topLevelItemCount()):
            grp = self.topLevelItem(i)
            for j in range(grp.childCount()):
                child = grp.child(j)
                if child.checkState(0) == Qt.Checked:
                    cdata = child.data(0, Qt.UserRole) or {}
                    total += int(cdata.get("size", 0) or 0)
        return total

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------
    def _add_group_item(self, group: DuplicateGroup) -> None:
        n_files = len(group.files)
        total_bytes = sum(f.size for f in group.files)
        reclaim = group.reclaimable_bytes() if group.keeper_path else 0
        title = (
            f"Group #{group.group_id} — {n_files} files · "
            f"{format_bytes(total_bytes)} total · {format_bytes(reclaim)} reclaimable"
        )
        grp_item = QTreeWidgetItem([title, "", "", "", "", "", "", "", ""])
        bold = QFont(grp_item.font(0))
        bold.setBold(True)
        grp_item.setFont(0, bold)
        grp_item.setFirstColumnSpanned(True)
        grp_item.setFlags(grp_item.flags() & ~Qt.ItemIsSelectable)
        grp_item.setData(0, Qt.UserRole, {
            "group_id": group.group_id,
            "keeper_path": group.keeper_path,
            "is_group": True,
        })
        self.addTopLevelItem(grp_item)

        for f in group.files:
            child = self._make_file_item(f, group)
            grp_item.addChild(child)
            self._item_by_path[f.path] = child
            # Kick off async thumb load.
            md = self._metadata.get(f.path)
            dur = md.duration_sec if md else None
            loader = _ThumbLoader(
                self._thumb_cache, f, dur, self._signals, self._cancel_event
            )
            self._thread_pool.start(loader)

    def _make_file_item(self, f: VideoFile, group: DuplicateGroup) -> QTreeWidgetItem:
        md = self._metadata.get(f.path)
        size_str = format_bytes(f.size)
        duration_str = format_duration(md.duration_sec if md else None)
        res_str = md.resolution_str if md else "?"
        codec_str = (md.video_codec or "?") if md else "?"
        fps_str = f"{md.fps:.2f}" if (md and md.fps) else "?"
        try:
            modified_str = datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            modified_str = "?"
        matched_str = ", ".join(group.matched_methods_for(f.path))
        path_str = f.path

        item = QTreeWidgetItem([
            f.name,
            size_str,
            duration_str,
            res_str,
            codec_str,
            fps_str,
            modified_str,
            matched_str,
            path_str,
        ])
        item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
        item.setCheckState(0, Qt.Unchecked)
        # Tooltip with full info.
        bytes_exact = f"{f.size:,} bytes"
        audio_str = ""
        if md and md.has_audio:
            audio_str = f"\nAudio: {md.audio_codec or '?'} · {md.audio_channels or '?'} ch"
        tooltip = (
            f"<b>{f.name}</b>\n"
            f"{f.path}\n"
            f"Size: {size_str} ({bytes_exact})\n"
            f"Duration: {duration_str}\n"
            f"Resolution: {res_str}\n"
            f"Codec: {codec_str} · FPS: {fps_str}{audio_str}\n"
            f"Modified: {modified_str}\n"
            f"Matched by: {matched_str or '—'}"
        ).replace("\n", "<br>")
        item.setToolTip(0, tooltip)
        item.setData(0, Qt.UserRole, {
            "path": f.path,
            "size": f.size,
            "is_group": False,
            "group_id": group.group_id,
        })
        is_keeper = group.keeper_path == f.path
        self._style_keeper(item, is_keeper)
        return item

    def _style_keeper(self, item: QTreeWidgetItem, is_keeper: bool) -> None:
        if is_keeper:
            item.setText(COL_NAME, "★ " + item.text(COL_NAME).lstrip("★ "))
            font = QFont(item.font(0))
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, QBrush(QColor("#2e7d32")))
            item.setToolTip(0, (item.toolTip(0) or "") +
                            "<br><b>This file is recommended as the keeper.</b>")
        else:
            txt = item.text(COL_NAME).lstrip("★ ")
            item.setText(COL_NAME, txt)
            font = QFont(item.font(0))
            font.setBold(False)
            item.setFont(0, font)
            item.setForeground(0, QBrush())

    # ------------------------------------------------------------------
    def _on_thumb_ready(self, path: str, pix: QPixmap) -> None:
        item = self._item_by_path.get(path)
        if item is None:
            return
        scaled = pix.scaled(
            _THUMB_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation
        )
        item.setIcon(0, QIcon(scaled))
        item.setSizeHint(0, QSize(0, _THUMB_SIZE.height() + 8))

    def _on_thumb_failed(self, path: str) -> None:
        item = self._item_by_path.get(path)
        if item is None:
            return
        # Set a small placeholder pixmap (gray rectangle) so layout stays consistent.
        ph = QPixmap(_THUMB_SIZE)
        ph.fill(QColor(64, 64, 64))
        item.setIcon(0, QIcon(ph))
        item.setSizeHint(0, QSize(0, _THUMB_SIZE.height() + 8))

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0:
            return
        # If the user checked the current keeper, warn by un-checking it back
        # and asking them to change the keeper via context menu instead.
        data = item.data(0, Qt.UserRole) or {}
        if data.get("is_group"):
            return
        path = data.get("path")
        if not path:
            return
        # Find the group's keeper.
        parent = item.parent()
        if parent is None:
            return
        gdata = parent.data(0, Qt.UserRole) or {}
        if gdata.get("keeper_path") == path and item.checkState(0) == Qt.Checked:
            # Veto: keepers can't be checked.
            self.blockSignals(True)
            item.setCheckState(0, Qt.Unchecked)
            self.blockSignals(False)

    def _on_item_double_clicked(
        self, item: QTreeWidgetItem, _column: int
    ) -> None:
        data = item.data(0, Qt.UserRole) or {}
        if data.get("is_group"):
            return
        path = data.get("path")
        if path:
            _open_with_default(path)

    # ------------------------------------------------------------------
    def _show_context_menu(self, pos) -> None:
        item = self.itemAt(pos)
        if item is None:
            return
        data = item.data(0, Qt.UserRole) or {}
        if data.get("is_group"):
            return
        path = data.get("path")
        if not path:
            return
        menu = QMenu(self)
        a_open_folder = QAction("Open containing folder", self)
        a_play = QAction("Open with default player", self)
        a_set_keeper = QAction("Set as keeper for this group", self)
        a_copy_path = QAction("Copy full path", self)
        a_toggle_path = QAction("Toggle 'Path' column", self)
        menu.addAction(a_open_folder)
        menu.addAction(a_play)
        menu.addSeparator()
        menu.addAction(a_set_keeper)
        menu.addSeparator()
        menu.addAction(a_copy_path)
        menu.addAction(a_toggle_path)

        a_open_folder.triggered.connect(lambda: _reveal_in_explorer(path))
        a_play.triggered.connect(lambda: _open_with_default(path))
        a_set_keeper.triggered.connect(lambda: self._set_keeper_from_item(item))
        a_copy_path.triggered.connect(lambda: _copy_to_clipboard(path))
        a_toggle_path.triggered.connect(
            lambda: self.setColumnHidden(COL_PATH, not self.isColumnHidden(COL_PATH))
        )
        menu.exec(self.viewport().mapToGlobal(pos))

    def _set_keeper_from_item(self, item: QTreeWidgetItem) -> None:
        data = item.data(0, Qt.UserRole) or {}
        path = data.get("path")
        gid = data.get("group_id")
        if not path or gid is None:
            return
        for g in self._groups:
            if g.group_id == gid:
                g.keeper_path = path
                self.update_keeper(gid, path)
                break
        self.keeper_changed.emit()


# ---------------------------------------------------------------------------
def _reveal_in_explorer(path: str) -> None:
    """Open Explorer with the file selected (Windows-only)."""
    try:
        if sys.platform == "win32":
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
        else:
            # Fallback: open the containing folder.
            folder = os.path.dirname(path)
            if folder:
                _open_with_default(folder)
    except OSError as exc:
        LOG.warning("reveal in explorer failed: %s", exc)


def _open_with_default(path: str) -> None:
    """Open *path* with the OS default application."""
    try:
        if sys.platform == "win32":
            os.startfile(path)  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])
    except OSError as exc:
        LOG.warning("open default failed: %s", exc)


def _copy_to_clipboard(text: str) -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        return
    app.clipboard().setText(text)
