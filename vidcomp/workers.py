"""Qt worker classes for scanning and deletion.

Both classes are :class:`QObject` subclasses designed to be moved onto a
``QThread`` via ``QObject.moveToThread``.  They communicate with the GUI by
emitting signals — never by touching widgets directly.
"""

from __future__ import annotations

import logging
import threading
import traceback
from pathlib import Path
from typing import Iterable, List, Optional, Set

from PySide6.QtCore import QObject, Signal, Slot

from .config import AppConfig
from .core import deletion
from .core.cache import Cache
from .core.engine import Engine, EngineResult
from .core.models import DeletionReport, DuplicateGroup, ScanProgress

LOG = logging.getLogger(__name__)


class ScanWorker(QObject):
    """Runs an :class:`Engine` scan; emits progress and final groups."""

    progress = Signal(ScanProgress)
    log_line = Signal(str)
    finished = Signal(object)            # emits EngineResult
    error = Signal(str)

    def __init__(
        self,
        config: AppConfig,
        cache: Cache,
        root: str,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._cache = cache
        self._root = root
        self._cancel_event = threading.Event()
        self._engine: Optional[Engine] = None

    # ------------------------------------------------------------------
    def request_cancel(self) -> None:
        """Thread-safe — may be called from the GUI thread."""
        self._cancel_event.set()
        LOG.info("Scan cancel requested.")

    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    # ------------------------------------------------------------------
    @Slot()
    def run(self) -> None:
        """Worker entry point (invoked once by the QThread)."""
        try:
            self._engine = Engine(
                config=self._config,
                cache=self._cache,
                cancel_event=self._cancel_event,
                progress_cb=lambda p: self.progress.emit(p),
                log_cb=lambda line: self.log_line.emit(line),
            )
            result = self._engine.run(self._root)
            self.finished.emit(result)
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Scan worker crashed")
            tb = traceback.format_exc()
            self.error.emit(f"{exc}\n\n{tb}")
            # Also emit a finished signal with an empty result so the UI returns
            # to the idle state.
            self.finished.emit(EngineResult())


class DeletionWorker(QObject):
    """Runs a batch deletion in a worker thread."""

    progress = Signal(int, int, str)     # done, total, current_path
    finished = Signal(object)            # emits DeletionReport
    error = Signal(str)

    def __init__(
        self,
        paths: List[str],
        mode: str,
        protected_paths: Set[str],
        quarantine_root: str = "",
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._paths = list(paths)
        self._mode = mode
        self._protected = set(protected_paths)
        self._quarantine_root = quarantine_root

    # ------------------------------------------------------------------
    @Slot()
    def run(self) -> None:
        try:
            report = deletion.delete_files(
                paths=self._paths,
                mode=self._mode,
                protected_paths=self._protected,
                quarantine_root=self._quarantine_root,
                progress_cb=lambda done, total, p: self.progress.emit(done, total, p),
            )
            self.finished.emit(report)
        except deletion.DeletionError as exc:
            self.error.emit(str(exc))
            self.finished.emit(DeletionReport(mode=self._mode))
        except Exception as exc:  # noqa: BLE001
            LOG.exception("Deletion worker crashed")
            self.error.emit(str(exc))
            self.finished.emit(DeletionReport(mode=self._mode))
