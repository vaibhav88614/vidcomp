"""Thumbnail extraction and a bounded on-disk thumbnail cache.

Thumbnails are stored as JPEGs named by a hash of ``(path, size, mtime)`` so
they survive across runs and are reused on re-scan.  The cache is pruned to a
configurable size budget (least-recently-used files removed first).
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Optional

from .media import MediaTools
from .models import VideoFile

log = logging.getLogger("vidcomp.thumbnails")


class ThumbnailCache:
    """Manages thumbnail generation and a size-bounded disk cache."""

    def __init__(self, cache_dir: str, tools: MediaTools, budget_mb: int = 512) -> None:
        self.cache_dir = cache_dir
        self.tools = tools
        self.budget_bytes = max(0, budget_mb) * 1024 * 1024
        os.makedirs(self.cache_dir, exist_ok=True)

    def _key(self, vf: VideoFile) -> str:
        raw = f"{vf.path}|{vf.size}|{int(vf.mtime)}".encode("utf-8", "ignore")
        return hashlib.sha1(raw).hexdigest()

    def path_for(self, vf: VideoFile) -> str:
        return os.path.join(self.cache_dir, self._key(vf) + ".jpg")

    def get_or_create(self, vf: VideoFile) -> Optional[str]:
        """Return a cached thumbnail path, generating it if necessary."""
        out = self.path_for(vf)
        if os.path.isfile(out) and os.path.getsize(out) > 0:
            _touch(out)
            return out
        duration = vf.info.duration if vf.info else None
        result = self.tools.extract_thumbnail(vf.path, out, duration)
        if result:
            self.prune()
        return result

    def prune(self) -> None:
        """Evict least-recently-used thumbnails to stay within the budget."""
        if self.budget_bytes <= 0:
            return
        try:
            entries: list[tuple[float, int, str]] = []
            total = 0
            for name in os.listdir(self.cache_dir):
                fp = os.path.join(self.cache_dir, name)
                if not os.path.isfile(fp):
                    continue
                st = os.stat(fp)
                entries.append((st.st_atime, st.st_size, fp))
                total += st.st_size
            if total <= self.budget_bytes:
                return
            entries.sort()  # oldest access first
            for _atime, sz, fp in entries:
                if total <= self.budget_bytes:
                    break
                try:
                    os.remove(fp)
                    total -= sz
                except OSError:
                    pass
        except Exception as exc:
            log.debug("thumbnail prune failed: %s", exc)


def _touch(path: str) -> None:
    try:
        os.utime(path, None)
    except OSError:
        pass
