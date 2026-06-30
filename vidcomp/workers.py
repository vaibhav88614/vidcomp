"""Qt worker threads that run the engine off the GUI thread.

``ScanWorker`` runs a full scan (discovery + engine) on a ``QThread`` and
communicates exclusively through signals.  ``ThumbnailWorker`` generates a
single thumbnail on the global ``QThreadPool``.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from PySide6.QtCore import QObject, QRunnable, QThread, Signal

from .config import AppConfig
from .core.cache import SignatureCache
from .core.engine import DuplicateEngine, ScanStats
from .core.keep_rules import apply_keep_rule
from .core.media import MediaTools
from .core.models import DuplicateGroup, VideoFile
from .core.scanner import discover_videos
from .core.thumbnails import ThumbnailCache

log = logging.getLogger("vidcomp.workers")


class ScanWorker(QThread):
    """Runs discovery + the duplicate engine in a background thread."""

    progress = Signal(int, int, str)         # done, total, message
    log = Signal(str)
    error = Signal(str, str)                 # path, message
    discovered = Signal(int)                 # number of files found
    finished_ok = Signal(list, object)       # list[DuplicateGroup], ScanStats
    failed = Signal(str)

    def __init__(
        self,
        folder: str,
        config: AppConfig,
        tools: MediaTools,
        cache: Optional[SignatureCache] = None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._folder = folder
        self._config = config
        self._tools = tools
        self._cache = cache
        self._cancel = False
        self._start_time = 0.0

    def cancel(self) -> None:
        self._cancel = True

    def is_cancelled(self) -> bool:
        return self._cancel

    def run(self) -> None:  # noqa: D401 - QThread entry point
        self._start_time = time.time()
        opts = self._config.scan_options
        try:
            log.info(
                "ScanWorker start: folder=%s methods=%s logic=%s workers=%d",
                self._folder,
                sorted(m.value for m in opts.enabled_methods),
                opts.match_logic.value,
                opts.worker_count,
            )
            self.log.emit(f"Scanning folder: {self._folder}")
            files: list[VideoFile] = []
            for vf in discover_videos(
                self._folder,
                opts.extensions,
                opts.min_size_bytes,
                on_error=lambda p, m: self.error.emit(p, m),
                is_cancelled=self.is_cancelled,
            ):
                files.append(vf)
                if len(files) % 50 == 0:
                    self.progress.emit(0, 0, f"Discovered {len(files)} files...")
            if self._cancel:
                self.failed.emit("Scan cancelled.")
                return

            self.discovered.emit(len(files))
            self.log.emit(f"Discovered {len(files)} candidate video file(s).")
            if not files:
                self.finished_ok.emit([], ScanStats())
                return

            engine = DuplicateEngine(
                tools=self._tools,
                options=opts,
                cache=self._cache,
                on_progress=lambda d, t, m: self.progress.emit(d, t, m),
                on_log=lambda m: self.log.emit(m),
                on_error=lambda p, m: self.error.emit(p, m),
                is_cancelled=self.is_cancelled,
            )
            groups = engine.run(files)
            if self._cancel:
                self.failed.emit("Scan cancelled.")
                return

            apply_keep_rule(groups, self._config.keep_rule)
            elapsed = time.time() - self._start_time
            self.log.emit(f"Scan complete in {elapsed:.1f}s.")
            log.info(
                "ScanWorker done: groups=%d files=%d pairs=%d errors=%d elapsed=%.1fs",
                engine.stats.groups_found, engine.stats.files_total,
                engine.stats.pairs_compared, engine.stats.errors, elapsed,
            )
            self.finished_ok.emit(groups, engine.stats)
        except Exception as exc:  # pragma: no cover - defensive
            log.exception("scan worker crashed")
            self.failed.emit(str(exc))


class _ThumbSignals(QObject):
    done = Signal(str, str)  # video path, thumbnail path
    fail = Signal(str)       # video path


class ThumbnailWorker(QRunnable):
    """Generates one thumbnail on the global thread pool."""

    def __init__(self, vf: VideoFile, cache: ThumbnailCache) -> None:
        super().__init__()
        self._vf = vf
        self._cache = cache
        self.signals = _ThumbSignals()

    def run(self) -> None:
        try:
            path = self._cache.get_or_create(self._vf)
            if path:
                self.signals.done.emit(self._vf.path, path)
            else:
                self.signals.fail.emit(self._vf.path)
        except Exception as exc:
            log.debug("thumbnail worker failed for %s: %s", self._vf.path, exc)
            self.signals.fail.emit(self._vf.path)
