"""Thumbnail extraction and disk-bounded LRU cache.

* One PNG per source file (representative middle-frame).
* Filenames are SHA-1 of ``(absolute_path, size, mtime)`` — keeps the cache
  immune to filename changes and invalidates automatically when the source is
  modified.
* Eviction is byte-bounded; oldest-access files are removed first.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from pathlib import Path
from typing import Optional, Tuple

from . import media

LOG = logging.getLogger(__name__)

_PNG_SUFFIX = ".png"


class ThumbnailCache:
    """File-system cache of representative thumbnails."""

    def __init__(self, root: str | Path, max_bytes: int = 500 * 1024 * 1024):
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)
        self._max_bytes = max_bytes
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    @staticmethod
    def _key_for(path: str, size: int, mtime: float) -> str:
        h = hashlib.sha1()
        h.update(path.encode("utf-8", errors="replace"))
        h.update(b"|")
        h.update(str(size).encode())
        h.update(b"|")
        h.update(f"{mtime:.3f}".encode())
        return h.hexdigest()

    def path_for(self, path: str, size: int, mtime: float) -> Path:
        return self._root / (self._key_for(path, size, mtime) + _PNG_SUFFIX)

    # ------------------------------------------------------------------
    def get_or_extract(
        self,
        video_path: str,
        size: int,
        mtime: float,
        duration_sec: Optional[float],
        thumb_size: Tuple[int, int] = (320, 180),
        cancel_event: Optional[threading.Event] = None,
    ) -> Optional[Path]:
        """Return the on-disk thumbnail path, extracting it if necessary.

        Returns ``None`` if extraction fails (e.g. corrupt video) — the caller
        should fall back to a placeholder.
        """
        thumb_path = self.path_for(video_path, size, mtime)
        if thumb_path.exists() and thumb_path.stat().st_size > 0:
            self._touch(thumb_path)
            return thumb_path

        ts = (duration_sec or 0.0) / 2.0 if duration_sec else 1.0
        try:
            ok = media.extract_single_frame(
                video_path, ts, thumb_path, cancel_event=cancel_event, size=thumb_size
            )
        except Exception as exc:  # noqa: BLE001 — never crash on a single thumbnail
            LOG.debug("Thumbnail extraction crashed for %s: %s", video_path, exc)
            ok = False

        if not ok or not thumb_path.exists():
            return None
        return thumb_path

    # ------------------------------------------------------------------
    def _touch(self, p: Path) -> None:
        try:
            now = time.time()
            os.utime(p, (now, p.stat().st_mtime))
        except OSError:
            pass

    def total_bytes(self) -> int:
        total = 0
        for p in self._root.glob("*" + _PNG_SUFFIX):
            try:
                total += p.stat().st_size
            except OSError:
                continue
        return total

    def evict_if_needed(self) -> int:
        """Bring the cache below ``max_bytes`` by removing oldest-accessed entries.

        Returns the number of bytes freed.  Safe to call at startup.
        """
        with self._lock:
            freed = 0
            try:
                entries = []
                for p in self._root.glob("*" + _PNG_SUFFIX):
                    try:
                        st = p.stat()
                        entries.append((st.st_atime, st.st_size, p))
                    except OSError:
                        continue
                total = sum(e[1] for e in entries)
                if total <= self._max_bytes:
                    return 0
                # Sort oldest-access first.
                entries.sort(key=lambda e: e[0])
                for _atime, size, p in entries:
                    if total <= self._max_bytes:
                        break
                    try:
                        p.unlink()
                        total -= size
                        freed += size
                    except OSError:
                        continue
            except Exception as exc:  # noqa: BLE001
                LOG.warning("Thumbnail eviction error: %s", exc)
            return freed

    def clear(self) -> None:
        with self._lock:
            for p in self._root.glob("*" + _PNG_SUFFIX):
                try:
                    p.unlink()
                except OSError:
                    continue
