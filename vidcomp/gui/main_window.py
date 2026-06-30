"""VidComp main window: ties the engine, workers and widgets together."""

from __future__ import annotations

import logging
import os
import time
from typing import List, Optional

from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from .. import __app_name__
from ..config import AppConfig, options_for_mode
from ..core.cache import SignatureCache
from ..core.deletion import SurvivorViolation, delete_paths
from ..core.media import MediaTools
from ..core.models import (
    DeleteMode,
    DuplicateGroup,
    KeepRule,
    MethodId,
    ScanMode,
)
from ..core.keep_rules import apply_keep_rule
from ..core.thumbnails import ThumbnailCache
from ..core.utils import format_eta, human_size
from ..workers import ScanWorker, ThumbnailWorker
from .style import apply_theme
from .widgets.advanced_panel import AdvancedPanel
from .widgets.help_dialog import HelpDialog
from .widgets.results_view import ResultsView
from .widgets.settings_dialog import SettingsDialog, _KEEP_LABELS
from .widgets.tool_check_dialog import ToolCheckDialog

log = logging.getLogger("vidcomp.gui")

_MODE_ORDER = [ScanMode.EASY, ScanMode.MEDIUM, ScanMode.ROBUST]
_MODE_LABELS = {ScanMode.EASY: "Easy", ScanMode.MEDIUM: "Medium", ScanMode.ROBUST: "Robust"}


class MainWindow(QMainWindow):
    """Top-level window."""

    def __init__(self, config: AppConfig, tools: MediaTools) -> None:
        super().__init__()
        self.config = config
        self.tools = tools
        self.cache: Optional[SignatureCache] = None
        self.thumb_cache: Optional[ThumbnailCache] = None
        self.worker: Optional[ScanWorker] = None
        self._scan_start = 0.0
        self._phase_start = 0.0
        self._last_total = -1

        self.setWindowTitle(__app_name__)
        self.resize(1180, 820)

        self._build_menu()
        self._build_ui()
        self._init_caches()
        self._sync_tool_availability()
        self._load_options_into_ui()

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._tick_elapsed)

    # --- UI construction --------------------------------------------------
    def _build_menu(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        act_open = QAction("Open folder...", self)
        act_open.triggered.connect(self._browse_folder)
        file_menu.addAction(act_open)
        file_menu.addSeparator()
        act_exit = QAction("Exit", self)
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        settings_menu = bar.addMenu("&Settings")
        act_settings = QAction("Preferences...", self)
        act_settings.triggered.connect(self._open_settings)
        settings_menu.addAction(act_settings)

        help_menu = bar.addMenu("&Help")
        act_help = QAction("Help && About", self)
        act_help.triggered.connect(lambda: HelpDialog(self).exec())
        help_menu.addAction(act_help)
        act_tools = QAction("Check external tools", self)
        act_tools.triggered.connect(self._show_tool_check)
        help_menu.addAction(act_tools)

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        # --- top bar ---
        top = QHBoxLayout()
        top.addWidget(QLabel("Folder:"))
        self.folder_edit = QLineEdit(self.config.last_folder)
        self.folder_edit.setPlaceholderText("Choose a folder to scan (subfolders included)")
        top.addWidget(self.folder_edit, 1)
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_folder)
        top.addWidget(browse_btn)
        root.addLayout(top)

        # --- mode + scan controls ---
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Mode:"))
        self.mode_group = QButtonGroup(self)
        for mode in _MODE_ORDER:
            rb = QRadioButton(_MODE_LABELS[mode])
            rb.setProperty("mode", mode.value)
            self.mode_group.addButton(rb)
            mode_row.addWidget(rb)
            if mode == self.config.scan_options.mode:
                rb.setChecked(True)
        self.mode_group.buttonClicked.connect(self._on_mode_changed)

        self.preset_label = QLabel("")
        self.preset_label.setStyleSheet("color:#7aa2f7;font-weight:600;")
        mode_row.addWidget(self.preset_label)
        mode_row.addStretch(1)

        self.advanced_btn = QPushButton("Advanced \u25be")
        self.advanced_btn.setCheckable(True)
        self.advanced_btn.toggled.connect(self._toggle_advanced)
        mode_row.addWidget(self.advanced_btn)

        self.scan_btn = QPushButton("Scan")
        self.scan_btn.setObjectName("primary")
        self.scan_btn.clicked.connect(self._start_scan)
        mode_row.addWidget(self.scan_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_scan)
        mode_row.addWidget(self.cancel_btn)
        root.addLayout(mode_row)

        # --- advanced panel (collapsible) ---
        self.advanced_panel = AdvancedPanel()
        self.advanced_panel.changed.connect(self._on_advanced_changed)
        self.advanced_scroll = QScrollArea()
        self.advanced_scroll.setWidgetResizable(True)
        self.advanced_scroll.setWidget(self.advanced_panel)
        self.advanced_scroll.setMaximumHeight(320)
        self.advanced_scroll.setVisible(False)
        root.addWidget(self.advanced_scroll)

        # --- progress area ---
        prog_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        prog_row.addWidget(self.progress_bar, 1)
        self.eta_label = QLabel("")
        prog_row.addWidget(self.eta_label)
        root.addLayout(prog_row)
        self.status_label = QLabel("Ready.")
        self.status_label.setStyleSheet("color:#9aa4b2;")
        root.addWidget(self.status_label)

        # --- results + log splitter ---
        splitter = QSplitter(Qt.Vertical)
        results_scroll = QScrollArea()
        results_scroll.setWidgetResizable(True)
        self.results_view = ResultsView()
        self.results_view.selectionChanged.connect(self._update_summary)
        results_scroll.setWidget(self.results_view)
        splitter.addWidget(results_scroll)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.log_view.setPlaceholderText("Log output...")
        splitter.addWidget(self.log_view)
        splitter.setSizes([620, 140])
        root.addWidget(splitter, 1)

        # --- bottom bar ---
        bottom = QHBoxLayout()
        self.summary_label = QLabel("No results.")
        self.summary_label.setStyleSheet("font-weight:600;")
        bottom.addWidget(self.summary_label, 1)

        bottom.addWidget(QLabel("Keep:"))
        self.keep_combo = QComboBox()
        for rule, label in _KEEP_LABELS.items():
            self.keep_combo.addItem(label, rule.value)
        self.keep_combo.setCurrentIndex(max(0, self.keep_combo.findData(self.config.keep_rule.value)))
        self.keep_combo.currentIndexChanged.connect(self._on_keep_rule_changed)
        bottom.addWidget(self.keep_combo)

        self.select_btn = QPushButton("Select duplicates")
        self.select_btn.clicked.connect(self._select_duplicates)
        self.select_btn.setEnabled(False)
        bottom.addWidget(self.select_btn)

        self.delete_btn = QPushButton("Delete selected")
        self.delete_btn.setObjectName("danger")
        self.delete_btn.clicked.connect(self._delete_selected)
        self.delete_btn.setEnabled(False)
        bottom.addWidget(self.delete_btn)
        root.addLayout(bottom)

    # --- setup helpers ----------------------------------------------------
    def _init_caches(self) -> None:
        try:
            self.cache = SignatureCache(os.path.join(self.config.cache_dir, "signatures.db"))
        except Exception as exc:
            self.append_log(f"Cache disabled: {exc}")
            self.cache = None
        self.thumb_cache = ThumbnailCache(
            self.config.thumbnail_dir, self.tools, self.config.thumbnail_cache_mb
        )

    def _sync_tool_availability(self) -> None:
        self.advanced_panel.set_vmaf_available(self.tools.has_vmaf())
        self.advanced_panel.set_audio_available(self.tools.has_fpcalc)

    def _load_options_into_ui(self) -> None:
        self.advanced_panel.load_options(self.config.scan_options)
        self._update_preset_label(self.config.scan_options.mode)

    # --- mode / advanced --------------------------------------------------
    def _on_mode_changed(self, button) -> None:
        mode = ScanMode(button.property("mode"))
        opts = options_for_mode(mode, self.config.scan_options)
        opts.mode = mode
        self.config.scan_options = opts
        self.advanced_panel.load_options(opts)
        self._update_preset_label(mode)

    def _on_advanced_changed(self) -> None:
        # Manual edits switch the active preset to Custom.
        self.config.scan_options.mode = ScanMode.CUSTOM
        for btn in self.mode_group.buttons():
            btn.setAutoExclusive(False)
            btn.setChecked(False)
            btn.setAutoExclusive(True)
        self._update_preset_label(ScanMode.CUSTOM)

    def _update_preset_label(self, mode: ScanMode) -> None:
        if mode == ScanMode.CUSTOM:
            self.preset_label.setText("Active: Custom")
        else:
            self.preset_label.setText(f"Active: {_MODE_LABELS.get(mode, mode.value)}")

    def _toggle_advanced(self, checked: bool) -> None:
        self.advanced_scroll.setVisible(checked)
        self.advanced_btn.setText("Advanced \u25b4" if checked else "Advanced \u25be")

    # --- scanning ---------------------------------------------------------
    def _browse_folder(self) -> None:
        start = self.folder_edit.text() or self.config.last_folder or os.path.expanduser("~")
        folder = QFileDialog.getExistingDirectory(self, "Choose folder to scan", start)
        if folder:
            self.folder_edit.setText(folder)

    def _start_scan(self) -> None:
        folder = self.folder_edit.text().strip()
        log.debug("_start_scan requested for folder=%r", folder)
        if not folder or not os.path.isdir(folder):
            QMessageBox.warning(self, "VidComp", "Please choose a valid folder to scan.")
            log.warning("Scan aborted: invalid folder %r", folder)
            return
        # Commit current advanced settings into the scan options.
        self.advanced_panel.apply_to(self.config.scan_options)
        self.config.scan_options.worker_count = self.config.worker_count
        if not self.config.scan_options.enabled_methods:
            QMessageBox.warning(self, "VidComp", "Enable at least one comparison method.")
            return
        self.config.last_folder = folder
        self.config.save()

        self.results_view.clear()
        self.log_view.clear()
        self._set_scanning(True)
        self._scan_start = time.time()
        self._phase_start = time.time()
        self._last_total = -1
        log.info(
            "Launching scan: folder=%s methods=%s logic=%s",
            folder,
            sorted(m.value for m in self.config.scan_options.enabled_methods),
            self.config.scan_options.match_logic.value,
        )

        self.worker = ScanWorker(folder, self.config, self.tools, self.cache)
        self.worker.progress.connect(self._on_progress)
        self.worker.log.connect(self.append_log)
        self.worker.error.connect(lambda p, m: self.append_log(f"[skip] {p}: {m}"))
        self.worker.discovered.connect(lambda n: self.status_label.setText(f"Discovered {n} files."))
        self.worker.finished_ok.connect(self._on_scan_finished)
        self.worker.failed.connect(self._on_scan_failed)
        self._elapsed_timer.start()
        self.worker.start()

    def _cancel_scan(self) -> None:
        if self.worker and self.worker.isRunning():
            self.append_log("Cancelling...")
            self.worker.cancel()
            self.cancel_btn.setEnabled(False)

    def _set_scanning(self, scanning: bool) -> None:
        self.scan_btn.setEnabled(not scanning)
        self.cancel_btn.setEnabled(scanning)
        self.select_btn.setEnabled(not scanning and bool(self.results_view.cards))
        self.delete_btn.setEnabled(not scanning and bool(self.results_view.selected_paths()))
        if not scanning:
            self._elapsed_timer.stop()

    def _on_progress(self, done: int, total: int, message: str) -> None:
        if total != self._last_total:
            self._last_total = total
            self._phase_start = time.time()
        if total > 0:
            self.progress_bar.setMaximum(total)
            self.progress_bar.setValue(min(done, total))
            elapsed = max(1e-6, time.time() - self._phase_start)
            rate = done / elapsed
            remaining = (total - done) / rate if rate > 0 else None
            self.eta_label.setText(f"{done}/{total}  ETA {format_eta(remaining)}")
        else:
            self.progress_bar.setMaximum(0)  # busy indicator
        if message:
            self.status_label.setText(message)

    def _tick_elapsed(self) -> None:
        if self._scan_start:
            elapsed = int(time.time() - self._scan_start)
            m, s = divmod(elapsed, 60)
            self.setWindowTitle(f"{__app_name__}  -  scanning {m:02d}:{s:02d}")

    def _on_scan_finished(self, groups: List[DuplicateGroup], stats) -> None:
        self._set_scanning(False)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(100)
        self.setWindowTitle(__app_name__)
        apply_keep_rule(groups, self._current_keep_rule())
        self.results_view.set_groups(groups)
        self.select_btn.setEnabled(bool(groups))
        self._update_summary()
        self._dispatch_thumbnails()
        self.status_label.setText(
            f"Done. {len(groups)} group(s), {stats.pairs_compared} pairs compared, "
            f"{stats.errors} error(s)."
        )

    def _on_scan_failed(self, message: str) -> None:
        self._set_scanning(False)
        self.progress_bar.setMaximum(100)
        self.progress_bar.setValue(0)
        self.setWindowTitle(__app_name__)
        self.append_log(message)
        self.status_label.setText(message)

    # --- thumbnails -------------------------------------------------------
    def _dispatch_thumbnails(self) -> None:
        if not self.thumb_cache:
            return
        pool = QThreadPool.globalInstance()
        # Retain references so the Python wrappers/signal objects survive until
        # their run() completes on the pool thread.
        self._thumb_workers = getattr(self, "_thumb_workers", [])
        self._thumb_workers.clear()
        for vf in self.results_view.files():
            worker = ThumbnailWorker(vf, self.thumb_cache)
            worker.signals.done.connect(self.results_view.update_thumbnail)
            worker.signals.done.connect(lambda *_args, w=worker: self._thumb_done(w))
            worker.signals.fail.connect(lambda *_args, w=worker: self._thumb_done(w))
            self._thumb_workers.append(worker)
            pool.start(worker)

    def _thumb_done(self, worker) -> None:
        try:
            self._thumb_workers.remove(worker)
        except (ValueError, AttributeError):
            pass

    # --- selection / deletion --------------------------------------------
    def _current_keep_rule(self) -> KeepRule:
        return KeepRule(self.keep_combo.currentData())

    def _on_keep_rule_changed(self) -> None:
        rule = self._current_keep_rule()
        self.config.keep_rule = rule
        apply_keep_rule(self.results_view.groups(), rule)
        self.results_view.apply_keep_rule_display()
        self._update_summary()

    def _select_duplicates(self) -> None:
        self.results_view.select_duplicates(self._current_keep_rule())

    def _update_summary(self) -> None:
        groups = self.results_view.groups()
        total_dupes = sum(max(0, len(g.files) - 1) for g in groups)
        reclaimable = sum(g.reclaimable for g in groups)
        selected = self.results_view.selected_paths()
        sel_bytes = 0
        files = {vf.path: vf for vf in self.results_view.files()}
        for p in selected:
            if p in files:
                sel_bytes += files[p].size
        self.summary_label.setText(
            f"{len(groups)} groups - {total_dupes} duplicates - "
            f"reclaimable {human_size(reclaimable)}   |   "
            f"selected {len(selected)} ({human_size(sel_bytes)})"
        )
        self.delete_btn.setEnabled(bool(selected))

    def _delete_selected(self) -> None:
        selected = self.results_view.selected_paths()
        log.debug("_delete_selected: %d path(s) chosen", len(selected))
        if not selected:
            return
        groups = self.results_view.groups()
        # Pre-validate survivor safety before showing the confirmation.
        try:
            from ..core.deletion import enforce_survivors

            enforce_survivors(selected, groups)
        except SurvivorViolation as exc:
            QMessageBox.warning(self, "VidComp - unsafe selection", str(exc))
            return

        files = {vf.path: vf for vf in self.results_view.files()}
        total_bytes = sum(files[p].size for p in selected if p in files)
        mode = self.config.delete_mode
        mode_text = {
            DeleteMode.RECYCLE_BIN: "Send to Recycle Bin",
            DeleteMode.QUARANTINE: f"Move to quarantine ({self.config.quarantine_folder})",
            DeleteMode.PERMANENT: "PERMANENTLY DELETE",
        }[mode]

        msg = (
            f"About to remove {len(selected)} file(s), reclaiming "
            f"{human_size(total_bytes)}.\n\nMode: {mode_text}\n\nProceed?"
        )
        confirm = QMessageBox.question(
            self, "Confirm deletion", msg,
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        if mode == DeleteMode.PERMANENT:
            extra = QMessageBox.warning(
                self, "Permanent delete",
                "These files will be permanently deleted and CANNOT be recovered.\n\nAre you absolutely sure?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if extra != QMessageBox.Yes:
                return

        log.info(
            "Deleting %d file(s) via %s (reclaim %s)",
            len(selected), mode.value, human_size(total_bytes),
        )
        results = delete_paths(
            selected, mode, self.config.quarantine_folder, groups=groups
        )
        ok = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        log.info("Deletion result: %d succeeded, %d failed", len(ok), len(failed))
        for r in failed:
            self.append_log(f"[delete failed] {r.path}: {r.error}")

        # Remove successfully deleted files from the view and re-group display.
        self._remove_deleted(set(r.path for r in ok))

        report = f"Deleted {len(ok)} file(s)."
        if failed:
            report += f" {len(failed)} failed (see log)."
        QMessageBox.information(self, "Deletion report", report)
        self.status_label.setText(report)
        self._update_summary()

    def _remove_deleted(self, deleted: set[str]) -> None:
        groups = self.results_view.groups()
        new_groups: List[DuplicateGroup] = []
        for g in groups:
            g.files = [f for f in g.files if f.path not in deleted]
            if len(g.files) >= 2:
                new_groups.append(g)
        apply_keep_rule(new_groups, self._current_keep_rule())
        self.results_view.set_groups(new_groups)
        self.select_btn.setEnabled(bool(new_groups))
        self._dispatch_thumbnails()

    # --- settings ---------------------------------------------------------
    def _open_settings(self) -> None:
        dlg = SettingsDialog(self.config, self)
        if dlg.exec():
            dlg.apply_to_config()
            self.config.save()
            from PySide6.QtWidgets import QApplication

            apply_theme(QApplication.instance(), self.config.dark_mode)
            self._init_caches()
            self.keep_combo.setCurrentIndex(
                max(0, self.keep_combo.findData(self.config.keep_rule.value))
            )
            self._on_keep_rule_changed()

    def _show_tool_check(self) -> None:
        ToolCheckDialog(self.tools.status(), self).exec()

    # --- misc -------------------------------------------------------------
    def append_log(self, message: str) -> None:
        self.log_view.appendPlainText(message)
        log.info(message)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)
        if self.cache:
            self.cache.close()
        self.config.save()
        super().closeEvent(event)
