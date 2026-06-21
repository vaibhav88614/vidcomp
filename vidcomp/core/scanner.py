"""Recursive folder walker for video files.

Uses :func:`os.scandir` for speed; gracefully skips files we can't ``stat``
(permission errors, races, unsupported names, etc.).  On Windows, files with
paths longer than ``MAX_PATH`` (260 chars) are still readable because the
``\\\\?\\`` prefix is applied transparently when needed.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional, Set

from .models import VideoFile

LOG = logging.getLogger(__name__)


def _normalise_extensions(extensions: Iterable[str]) -> Set[str]:
    out: Set[str] = set()
    for e in extensions:
        e = e.strip().lower().lstrip(".")
        if e:
            out.add(e)
    return out


def _windows_long_path(path: str) -> str:
    """Apply the ``\\\\?\\`` long-path prefix on Windows for paths >= 260 chars."""
    if sys.platform != "win32":
        return path
    if path.startswith("\\\\?\\"):
        return path
    if len(path) < 250:
        return path
    if path.startswith("\\\\"):
        # UNC path → \\?\UNC\server\share\...
        return "\\\\?\\UNC\\" + path.lstrip("\\")
    return "\\\\?\\" + path


def walk_directory(
    root: str | Path,
    extensions: Iterable[str],
    min_file_size_bytes: int = 0,
    cancel_check: Optional[Callable[[], bool]] = None,
    on_skip: Optional[Callable[[str, str], None]] = None,
) -> Iterator[VideoFile]:
    """Yield :class:`VideoFile` for every matching file under *root* recursively.

    Parameters
    ----------
    root:
        Folder to scan.
    extensions:
        Iterable of extensions (with or without leading dot, case-insensitive).
    min_file_size_bytes:
        Files smaller than this are skipped (helps ignore stub/placeholder files).
    cancel_check:
        Optional callable returning ``True`` if scanning should stop early.
    on_skip:
        Optional callback ``(path, reason)`` invoked for files we couldn't read.
    """
    root_path = Path(root)
    if not root_path.exists() or not root_path.is_dir():
        LOG.warning("Scan root does not exist or is not a directory: %s", root_path)
        return

    allowed = _normalise_extensions(extensions)
    if not allowed:
        return

    stack = [str(root_path)]
    while stack:
        if cancel_check is not None and cancel_check():
            return
        current = stack.pop()
        try:
            it = os.scandir(_windows_long_path(current))
        except (PermissionError, OSError) as exc:
            if on_skip:
                on_skip(current, f"cannot list directory: {exc}")
            continue
        try:
            for entry in it:
                if cancel_check is not None and cancel_check():
                    return
                try:
                    if entry.is_dir(follow_symlinks=False):
                        stack.append(entry.path)
                        continue
                    if not entry.is_file(follow_symlinks=False):
                        continue
                    name = entry.name
                    dot = name.rfind(".")
                    if dot < 0:
                        continue
                    ext = name[dot + 1:].lower()
                    if ext not in allowed:
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError as exc:
                        if on_skip:
                            on_skip(entry.path, f"stat failed: {exc}")
                        continue
                    if st.st_size < min_file_size_bytes:
                        continue
                    # Re-canonicalise the path to drop the long-path prefix.
                    p = entry.path
                    if p.startswith("\\\\?\\"):
                        p = p[4:]
                        if p.startswith("UNC\\"):
                            p = "\\\\" + p[4:]
                    yield VideoFile(
                        path=p,
                        size=st.st_size,
                        mtime=st.st_mtime,
                        ctime=st.st_ctime,
                    )
                except OSError as exc:
                    if on_skip:
                        on_skip(getattr(entry, "path", "?"), f"entry error: {exc}")
        finally:
            try:
                it.close()
            except Exception:  # noqa: BLE001
                pass
