"""Recursive video-file discovery.

Walks a folder tree, filters by configurable extension and minimum-size, and
yields :class:`VideoFile` records.  Unreadable entries are skipped and reported
through an optional callback rather than aborting the whole scan.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Iterable, Iterator, Optional

from .models import VideoFile

log = logging.getLogger("vidcomp.scanner")

ErrorCallback = Callable[[str, str], None]  # (path, message)


def discover_videos(
    root: str,
    extensions: Iterable[str],
    min_size_bytes: int = 0,
    on_error: Optional[ErrorCallback] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> Iterator[VideoFile]:
    """Yield :class:`VideoFile` for every matching file under ``root``.

    ``extensions`` are matched case-insensitively and may be given with or
    without a leading dot.  Files smaller than ``min_size_bytes`` (including
    zero-byte files) are skipped.
    """
    norm_exts = {
        ("." + e.lower().lstrip(".")) for e in extensions if e
    }
    log.info(
        "Discovering videos under %s (exts=%s, min_size=%d bytes)",
        root, sorted(norm_exts), min_size_bytes,
    )
    yielded = 0
    skipped = 0

    for dirpath, dirnames, filenames in os.walk(root, onerror=_walk_error(on_error)):
        if is_cancelled and is_cancelled():
            log.info("Discovery cancelled after %d file(s)", yielded)
            return
        log.debug("walk: %s (%d files)", dirpath, len(filenames))
        for fname in filenames:
            if is_cancelled and is_cancelled():
                log.info("Discovery cancelled after %d file(s)", yielded)
                return
            ext = os.path.splitext(fname)[1].lower()
            if ext not in norm_exts:
                continue
            full = os.path.join(dirpath, fname)
            try:
                st = os.stat(full)
            except OSError as exc:
                _report(on_error, full, f"stat failed: {exc}")
                skipped += 1
                continue
            if st.st_size <= 0:
                _report(on_error, full, "zero-byte file skipped")
                skipped += 1
                continue
            if st.st_size < min_size_bytes:
                skipped += 1
                continue
            yielded += 1
            yield VideoFile(
                path=full,
                size=st.st_size,
                mtime=st.st_mtime,
                ctime=getattr(st, "st_ctime", st.st_mtime),
            )

    log.info("Discovery finished: %d kept, %d skipped", yielded, skipped)


def collect_videos(
    root: str,
    extensions: Iterable[str],
    min_size_bytes: int = 0,
    on_error: Optional[ErrorCallback] = None,
    is_cancelled: Optional[Callable[[], bool]] = None,
) -> list[VideoFile]:
    """Eager wrapper around :func:`discover_videos`."""
    return list(
        discover_videos(root, extensions, min_size_bytes, on_error, is_cancelled)
    )


def _walk_error(on_error: Optional[ErrorCallback]):
    def handler(exc: OSError) -> None:
        path = getattr(exc, "filename", "") or ""
        _report(on_error, path, f"directory walk error: {exc}")
    return handler


def _report(on_error: Optional[ErrorCallback], path: str, message: str) -> None:
    log.debug("%s: %s", path, message)
    if on_error:
        try:
            on_error(path, message)
        except Exception:
            pass
