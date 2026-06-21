"""VidComp main window — assembles all widgets and wires up worker threads."""

from __future__ import annotations

import logging
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__, __version__
from ..config import (
    AppConfig,
    MATCH_ANY,
    PRESET_CUSTOM,
    PRESET_EASY,
    PRESET_MEDIUM,
    PRESET_ROBUST,
    detect_preset_from_methods,
    methods_for_preset,
)
from ..core import deletion, media
from ..core.cache import Cache
from ..core.engine import EngineResult
from ..core.keep_rules import apply_to_all
from ..core.models import DeletionReport, DuplicateGroup, ScanProgress, ToolsStatus
from ..core.thumbnails import ThumbnailCache
from ..workers import DeletionWorker, ScanWorker
from .style import app_qss
from .widgets.about_dialog import AboutDialog
from .widgets.advanced_panel import AdvancedPanel
from .widgets.delete_confirm_dialog import DeleteConfirmDialog
from .widgets.delete_report_dialog import DeleteReportDialog
from .widgets.help_dialog import HelpDialog
from .widgets.log_panel import LogPanel, QtLogHandler
from .widgets.missing_tools_dialog import MissingToolsDialog
from .widgets.progress_panel import ProgressPanel
from .widgets.result_tree import ResultTree
from .widgets.settings_dialog import SettingsDialog
from .widgets.summary_bar import SummaryBar
from .widgets.top_bar import TopBar

LOG = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Top-level VidComp window."""

    def __init__(self, config: AppConfig, log_handler: QtLogHandler) -> None:
        super().__init__()
        self._config = config
        self._cache = Cache(config.cache_path)
        self._thumb_cache = ThumbnailCache(
            config.thumbnail_cache_path,
            max_bytes=config.thumbnail_cache_max_bytes,
        )
        # Evict cache at startup (cheap and bounded).
        self._thumb_cache.evict_if_needed()

        self._tools_status: Optional[ToolsStatus] = None
        self._scan_thread: Optional[QThread] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._delete_thread: Optional[QThread] = None
        self._delete_worker: Optional[DeletionWorker] = None
        self._current_result: Optional[EngineResult] = None
        self._closing = False

        self.setWindowTitle(f"{__app_name__} {__version__}")
        self.resize(1280, 820)
        self.setStyleSheet(app_qss())

        self._build_ui()
        self._build_menu()
        self._wire_signals()

        # Attach the log handler to the in-app panel.
        self.log_panel.attach_handler(log_handler)

        # Restore last-scanned folder.
        if config.last_scan_folder:
            self.top_bar.set_folder(config.last_scan_folder)

        # Apply preset to widget.
        self.top_bar.set_mode(
            config.preset if config.preset != PRESET_CUSTOM else PRESET_MEDIUM
        )
        self.advanced_panel.setVisible(config.advanced_panel_open)
        self.top_bar.set_advanced_open(config.advanced_panel_open)
        self._update_preset_label()

        # Defer tool detection to after the window has shown (so dialog has a parent).
        QTimer.singleShot(0, self._initial_tool_check)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.top_bar = TopBar()
        self.advanced_panel = AdvancedPanel(self._config)
        self.progress_panel = ProgressPanel()
        self.result_tree = ResultTree(self._thumb_cache)
        self.summary_bar = SummaryBar(self._config)
        self.log_panel = LogPanel()

        self.preset_status = QLabel()
        self.preset_status.setProperty("role", "subtle")
        self.preset_status.setContentsMargins(8, 0, 8, 0)

        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        outer.addWidget(self.top_bar)
        outer.addWidget(self.preset_status)
        outer.addWidget(self.advanced_panel)

        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setFrameShadow(QFrame.Sunken)
        outer.addWidget(sep)

        outer.addWidget(self.progress_panel)
        outer.addWidget(self.result_tree, 1)
        outer.addWidget(self.summary_bar)

        self.setCentralWidget(central)

        # Log dock (hidden by default).
        self.log_dock = QDockWidget("Log", self)
        self.log_dock.setWidget(self.log_panel)
        self.log_dock.setAllowedAreas(Qt.BottomDockWidgetArea | Qt.RightDockWidgetArea)
        self.log_dock.setVisible(False)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.log_dock)

        # Status bar.
        self.setStatusBar(QStatusBar(self))
        self.statusBar().showMessage("Ready.")

    def _build_menu(self) -> None:
        mb = self.menuBar()
        # File
        file_m = mb.addMenu("&File")
        open_act = QAction("Open &folder…", self)
        open_act.setShortcut(QKeySequence.Open)
        open_act.triggered.connect(self._on_open_folder_menu)
        file_m.addAction(open_act)
        file_m.addSeparator()
        quit_act = QAction("&Quit", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(self.close)
        file_m.addAction(quit_act)

        # Settings
        settings_m = mb.addMenu("&Settings")
        settings_act = QAction("&Preferences…", self)
        settings_act.triggered.connect(self._open_settings)
        settings_m.addAction(settings_act)
        clear_cache_act = QAction("Clear thumbnail cache", self)
        clear_cache_act.triggered.connect(self._clear_thumb_cache)
        settings_m.addAction(clear_cache_act)
        retest_act = QAction("Re-check external tools", self)
        retest_act.triggered.connect(self._retest_tools)
        settings_m.addAction(retest_act)

        # View
        view_m = mb.addMenu("&View")
        toggle_log_act = self.log_dock.toggleViewAction()
        toggle_log_act.setText("Show &log panel")
        view_m.addAction(toggle_log_act)

        # Help
        help_m = mb.addMenu("&Help")
        help_act = QAction("&Help…", self)
        help_act.setShortcut(QKeySequence.HelpContents)
        help_act.triggered.connect(self._open_help)
        help_m.addAction(help_act)
        about_act = QAction("&About VidComp", self)
        about_act.triggered.connect(self._open_about)
        help_m.addAction(about_act)

    def _wire_signals(self) -> None:
        self.top_bar.scan_requested.connect(self._on_scan_requested)
        self.top_bar.cancel_requested.connect(self._on_cancel_requested)
        self.top_bar.mode_changed.connect(self._on_mode_changed)
        self.top_bar.advanced_toggled.connect(self._on_advanced_toggled)
        self.advanced_panel.modified.connect(self._on_advanced_modified)
        self.summary_bar.select_duplicates.connect(self._on_select_duplicates)
        self.summary_bar.delete_selected.connect(self._on_delete_selected)
        self.summary_bar.keep_rule_changed.connect(self._on_keep_rule_changed)
        self.result_tree.itemChanged.connect(self._refresh_summary)
        self.result_tree.keeper_changed.connect(self._on_tree_keeper_changed)

    # ------------------------------------------------------------------
    # Tool detection
    # ------------------------------------------------------------------
    def _initial_tool_check(self) -> None:
        status = media.detect_tools(force=True)
        self._tools_status = status
        self.advanced_panel.set_vmaf_available(status.libvmaf)
        self.advanced_panel.set_audio_available(status.fpcalc.available)
        if not status.required_ok or status.missing_optional:
            dlg = MissingToolsDialog(status, parent=self)
            if not status.required_ok:
                if dlg.exec() == 0:
                    QTimer.singleShot(0, self.close)
                    return
            else:
                dlg.exec()
        self.statusBar().showMessage(self._tools_status_text(), 4000)

    def _retest_tools(self) -> None:
        status = media.detect_tools(force=True)
        self._tools_status = status
        self.advanced_panel.set_vmaf_available(status.libvmaf)
        self.advanced_panel.set_audio_available(status.fpcalc.available)
        MissingToolsDialog(status, parent=self).exec()

    def _tools_status_text(self) -> str:
        s = self._tools_status
        if s is None:
            return ""
        parts = []
        parts.append("ffmpeg ✓" if s.ffmpeg.available else "ffmpeg ✗")
        parts.append("ffprobe ✓" if s.ffprobe.available else "ffprobe ✗")
        parts.append("fpcalc ✓" if s.fpcalc.available else "fpcalc ✗")
        parts.append("libvmaf ✓" if s.libvmaf else "libvmaf ✗")
        return " | ".join(parts)

    # ------------------------------------------------------------------
    # Top-bar handlers
    # ------------------------------------------------------------------
    def _on_open_folder_menu(self) -> None:
        start = self.top_bar.folder() or str(Path.home())
        chosen = QFileDialog.getExistingDirectory(self, "Choose folder to scan", start)
        if chosen:
            self.top_bar.set_folder(chosen)

    def _on_mode_changed(self, preset: str) -> None:
        self._config.apply_preset(preset)
        self.advanced_panel.refresh_from_config()
        self._update_preset_label()

    def _on_advanced_toggled(self, checked: bool) -> None:
        self.advanced_panel.setVisible(checked)
        self._config.advanced_panel_open = checked

    def _on_advanced_modified(self) -> None:
        # Mark preset as custom if the user diverges.
        self._config.preset = detect_preset_from_methods(self._config.enabled_methods)
        self.top_bar.set_mode(
            self._config.preset if self._config.preset != PRESET_CUSTOM else self._config.preset
        )
        # Override top-bar radios silently when preset is custom — none stays checked.
        self._update_preset_label()

    def _update_preset_label(self) -> None:
        preset = detect_preset_from_methods(self._config.enabled_methods)
        if preset != self._config.preset:
            self._config.preset = preset
        names = {
            PRESET_EASY: "Easy",
            PRESET_MEDIUM: "Medium",
            PRESET_ROBUST: "Robust",
            PRESET_CUSTOM: "Custom",
        }
        method_count = len(self._config.enabled_methods)
        logic = "ANY" if self._config.match_logic == MATCH_ANY else "ALL"
        self.preset_status.setText(
            f"Active preset: <b>{names.get(preset, preset)}</b> · "
            f"{method_count} method(s) enabled · match logic: <b>{logic}</b>"
        )

    # ------------------------------------------------------------------
    # Scan lifecycle
    # ------------------------------------------------------------------
    def _on_scan_requested(self) -> None:
        if self._scan_thread is not None:
            return
        folder = self.top_bar.folder()
        if not folder:
            QMessageBox.warning(self, "No folder", "Choose a folder to scan first.")
            return
        if not Path(folder).is_dir():
            QMessageBox.warning(
                self, "Not a folder", f"This path is not a directory:\n{folder}"
            )
            return
        if not self._config.enabled_methods:
            QMessageBox.warning(
                self, "No methods enabled",
                "Enable at least one comparison method in the Advanced panel.",
            )
            return
        if self._tools_status is None or not self._tools_status.required_ok:
            QMessageBox.critical(
                self, "Missing tools",
                "ffmpeg and ffprobe must be installed and on PATH before scanning.",
            )
            return

        # Persist last-scanned folder.
        self._config.last_scan_folder = folder
        try:
            self._config.save()
        except OSError as exc:
            LOG.warning("Could not save config: %s", exc)

        # Clear previous results.
        self.result_tree.clear_results()
        self._current_result = None
        self._refresh_summary()
        self.progress_panel.reset()
        self.top_bar.set_scanning(True)
        self.statusBar().showMessage("Scanning…")

        # Spawn worker on a fresh QThread.
        self._scan_thread = QThread(self)
        self._scan_worker = ScanWorker(self._config, self._cache, folder)
        self._scan_worker.moveToThread(self._scan_thread)
        self._scan_thread.started.connect(self._scan_worker.run)
        self._scan_worker.progress.connect(self.progress_panel.update_progress)
        self._scan_worker.log_line.connect(self.log_panel.append_line)
        self._scan_worker.finished.connect(self._on_scan_finished)
        self._scan_worker.error.connect(self._on_scan_error)
        self._scan_thread.start()

    def _on_cancel_requested(self) -> None:
        if self._scan_worker is not None:
            self._scan_worker.request_cancel()
            self.statusBar().showMessage("Cancelling…")

    def _on_scan_finished(self, result: EngineResult) -> None:
        self._current_result = result
        # Tear down worker thread.
        if self._scan_thread is not None:
            self._scan_thread.quit()
            self._scan_thread.wait(2000)
            self._scan_thread.deleteLater()
            self._scan_thread = None
        if self._scan_worker is not None:
            self._scan_worker.deleteLater()
            self._scan_worker = None

        self.top_bar.set_scanning(False)
        # Re-apply keep-rule from current GUI selection (in case user changed combo).
        apply_to_all(result.groups, self.summary_bar.selected_keep_rule(), ctx=None)

        # Push into the tree.
        self.result_tree.set_groups(result.groups, result.metadata)
        # Refresh summary.
        self._refresh_summary()
        self.statusBar().showMessage(
            f"Scan complete: {len(result.groups)} group(s) · "
            f"{result.file_count} files scanned · "
            f"{result.skipped} skipped · "
            f"{result.elapsed_sec:.1f}s · "
            f"{result.pair_count:,} pairs evaluated.",
            10000,
        )

    def _on_scan_error(self, message: str) -> None:
        LOG.error("Scan worker error: %s", message)
        QMessageBox.critical(self, "Scan error", message)

    # ------------------------------------------------------------------
    # Summary + selection
    # ------------------------------------------------------------------
    def _refresh_summary(self, *_args) -> None:
        groups = self.result_tree.groups()
        group_count = len(groups)
        duplicate_count = sum(max(0, len(g.files) - 1) for g in groups)
        reclaimable = sum(g.reclaimable_bytes() for g in groups)
        sel = self.result_tree.selected_for_deletion()
        sel_bytes = self.result_tree.selected_size_bytes()
        self.summary_bar.update_summary(
            group_count, duplicate_count, reclaimable,
            selected_count=len(sel), selected_bytes=sel_bytes,
        )

    def _on_select_duplicates(self) -> None:
        n = self.result_tree.auto_check_duplicates()
        self.statusBar().showMessage(f"Selected {n} duplicate file(s).", 4000)
        self._refresh_summary()

    def _on_keep_rule_changed(self, rule: str) -> None:
        groups = self.result_tree.groups()
        apply_to_all(groups, rule, ctx=None)
        for g in groups:
            self.result_tree.update_keeper(g.group_id, g.keeper_path)
        self._refresh_summary()

    def _on_tree_keeper_changed(self) -> None:
        # User manually picked a keeper — keep_rule becomes "manual" implicitly.
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Deletion
    # ------------------------------------------------------------------
    def _on_delete_selected(self) -> None:
        if self._delete_thread is not None:
            return
        paths = self.result_tree.selected_for_deletion()
        if not paths:
            return
        protected = self.result_tree.protected_paths()
        in_protected = [p for p in paths if p in protected]
        if in_protected:
            QMessageBox.warning(
                self, "Protected files selected",
                f"{len(in_protected)} of your selected file(s) are the keeper for "
                "their group. Uncheck them or change the keeper before deleting.",
            )
            return
        bytes_to_free = self.result_tree.selected_size_bytes()
        mode = self._config.delete_mode
        confirm = DeleteConfirmDialog(
            count=len(paths),
            bytes_to_free=bytes_to_free,
            mode=mode,
            quarantine_path=self._config.quarantine_path,
            parent=self,
        )
        if confirm.exec() != confirm.Accepted:
            return

        self.statusBar().showMessage(f"Deleting {len(paths)} file(s)…")
        self._delete_thread = QThread(self)
        self._delete_worker = DeletionWorker(
            paths=paths,
            mode=mode,
            protected_paths=protected,
            quarantine_root=self._config.quarantine_path,
        )
        self._delete_worker.moveToThread(self._delete_thread)
        self._delete_thread.started.connect(self._delete_worker.run)
        self._delete_worker.progress.connect(self._on_delete_progress)
        self._delete_worker.finished.connect(self._on_delete_finished)
        self._delete_worker.error.connect(self._on_delete_error)
        self._delete_thread.start()

    def _on_delete_progress(self, done: int, total: int, current: str) -> None:
        self.statusBar().showMessage(f"Deleting {done}/{total} — {current}")

    def _on_delete_finished(self, report: DeletionReport) -> None:
        if self._delete_thread is not None:
            self._delete_thread.quit()
            self._delete_thread.wait(2000)
            self._delete_thread.deleteLater()
            self._delete_thread = None
        if self._delete_worker is not None:
            self._delete_worker.deleteLater()
            self._delete_worker = None
        self.statusBar().showMessage(
            f"Deleted {len(report.succeeded)} file(s), "
            f"{len(report.failed)} failed.",
            8000,
        )
        # Remove deleted paths from the tree.
        deleted_paths = {r.path for r in report.succeeded}
        if deleted_paths:
            self._drop_paths(deleted_paths)
        DeleteReportDialog(report, parent=self).exec()

    def _on_delete_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Deletion error", msg)

    def _drop_paths(self, deleted: set) -> None:
        """Remove deleted files from the in-memory groups + tree."""
        if self._current_result is None:
            return
        groups = []
        for g in self._current_result.groups:
            survivors = [f for f in g.files if f.path not in deleted]
            if len(survivors) >= 2:
                g.files = survivors
                # If the keeper was deleted (shouldn't happen — protected), pick first.
                if g.keeper_path in deleted:
                    g.keeper_path = survivors[0].path
                groups.append(g)
        self._current_result.groups = groups
        self.result_tree.set_groups(groups, self._current_result.metadata)
        self._refresh_summary()

    # ------------------------------------------------------------------
    # Settings / Help / About
    # ------------------------------------------------------------------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, parent=self)
        if dlg.exec() == dlg.Accepted:
            dlg.commit_to_config()
            try:
                self._config.save()
            except OSError as exc:
                LOG.warning("Could not save config: %s", exc)
            # Pick up cache path changes by re-opening the cache.
            try:
                self._cache.close()
            except Exception:  # noqa: BLE001
                pass
            self._cache = Cache(self._config.cache_path)
            self._thumb_cache = ThumbnailCache(
                self._config.thumbnail_cache_path,
                max_bytes=self._config.thumbnail_cache_max_bytes,
            )
            self.summary_bar.set_keep_rule(self._config.keep_rule)

    def _clear_thumb_cache(self) -> None:
        if QMessageBox.question(
            self, "Clear thumbnails",
            "Delete all cached thumbnails? Future scans will re-extract them.",
            QMessageBox.Yes | QMessageBox.No,
        ) == QMessageBox.Yes:
            self._thumb_cache.clear()
            self.statusBar().showMessage("Thumbnail cache cleared.", 4000)

    def _open_help(self) -> None:
        HelpDialog(self).exec()

    def _open_about(self) -> None:
        AboutDialog(self).exec()

    # ------------------------------------------------------------------
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._closing:
            event.accept()
            return
        if self._scan_thread is not None:
            ans = QMessageBox.question(
                self, "Quit during scan",
                "A scan is in progress. Cancel and quit?",
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                event.ignore()
                return
            if self._scan_worker is not None:
                self._scan_worker.request_cancel()
            if self._scan_thread is not None:
                self._scan_thread.quit()
                self._scan_thread.wait(5000)
        self._closing = True
        # Stop pending thumbnail loads to release the engine cleanly.
        self.result_tree.cancel_pending_thumbnails()
        try:
            self._config.save()
        except OSError:
            pass
        try:
            self._cache.close()
        except Exception:  # noqa: BLE001
            pass
        event.accept()
