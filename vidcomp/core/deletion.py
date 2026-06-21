"""File deletion: Recycle Bin, quarantine folder, permanent.

The :func:`delete_files` entry point enforces the "at least one survivor per
group" invariant by accepting a *protected* set of paths the caller must
preserve.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Iterable, List, Optional, Set

try:
    from send2trash import send2trash
except Exception:  # pragma: no cover
    send2trash = None  # type: ignore

from ..config import DELETE_PERMANENT, DELETE_QUARANTINE, DELETE_RECYCLE
from .models import DeletionReport, DeletionResult

LOG = logging.getLogger(__name__)


class DeletionError(Exception):
    """Raised when the caller violates a deletion invariant (e.g. would empty a group)."""


def delete_files(
    paths: Iterable[str],
    mode: str,
    protected_paths: Set[str],
    quarantine_root: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> DeletionReport:
    """Delete *paths* using *mode*; abort if any path is in *protected_paths*.

    Parameters
    ----------
    paths:
        Files to delete.
    mode:
        ``recycle``, ``quarantine`` or ``permanent``.
    protected_paths:
        Paths that must never be deleted — typically the union of each group's
        keeper.  If any path in *paths* appears here, :class:`DeletionError` is
        raised before any file is touched.
    quarantine_root:
        Destination root for quarantine mode (required if ``mode='quarantine'``).
    progress_cb:
        Optional ``(done, total, current_path)`` callback for the GUI.
    """
    paths = list(paths)
    if not paths:
        return DeletionReport(mode=mode)

    # Guard against the "delete every file in a group" footgun.
    bad = [p for p in paths if p in protected_paths]
    if bad:
        raise DeletionError(
            f"Refusing to delete {len(bad)} protected file(s); "
            f"at least one file per group must be kept. "
            f"First offender: {bad[0]}"
        )

    if mode == DELETE_QUARANTINE and not quarantine_root:
        raise DeletionError("quarantine_root is required for quarantine mode")

    report = DeletionReport(mode=mode)
    total = len(paths)
    for i, p in enumerate(paths, 1):
        if progress_cb is not None:
            try:
                progress_cb(i - 1, total, p)
            except Exception:  # noqa: BLE001
                pass
        # Capture size *before* attempting deletion (file is gone afterwards).
        size_before = _safe_size_before(p)
        result = _delete_one(p, mode, quarantine_root)
        report.results.append(result)
        if result.ok:
            report.bytes_reclaimed += size_before
    if progress_cb is not None:
        try:
            progress_cb(total, total, "")
        except Exception:  # noqa: BLE001
            pass
    return report


# ---------------------------------------------------------------------------
def _delete_one(path: str, mode: str, quarantine_root: Optional[str]) -> DeletionResult:
    if not os.path.exists(path):
        return DeletionResult(path=path, ok=False, error="file does not exist")
    try:
        if mode == DELETE_RECYCLE:
            return _to_recycle_bin(path)
        if mode == DELETE_QUARANTINE:
            return _to_quarantine(path, quarantine_root or "")
        if mode == DELETE_PERMANENT:
            return _permanent(path)
        return DeletionResult(path=path, ok=False, error=f"unknown mode: {mode}")
    except Exception as exc:  # noqa: BLE001
        return DeletionResult(path=path, ok=False, error=str(exc))


def _to_recycle_bin(path: str) -> DeletionResult:
    if send2trash is None:
        return DeletionResult(path=path, ok=False, error="send2trash not installed")
    try:
        send2trash(path)
    except Exception as exc:  # noqa: BLE001
        return DeletionResult(path=path, ok=False, error=str(exc))
    return DeletionResult(path=path, ok=True, target="Recycle Bin")


def _to_quarantine(path: str, root: str) -> DeletionResult:
    if not root:
        return DeletionResult(path=path, ok=False, error="no quarantine folder set")
    src = Path(path)
    dest_root = Path(root)
    dest_root.mkdir(parents=True, exist_ok=True)
    # Preserve some structure: drive letter + path tail.
    rel_tail = _safe_rel_tail(src)
    dest = dest_root / rel_tail
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest = _ensure_unique(dest)
    try:
        shutil.move(str(src), str(dest))
    except Exception as exc:  # noqa: BLE001
        return DeletionResult(path=path, ok=False, error=str(exc))
    return DeletionResult(path=path, ok=True, target=str(dest))


def _permanent(path: str) -> DeletionResult:
    try:
        os.remove(path)
    except OSError as exc:
        return DeletionResult(path=path, ok=False, error=str(exc))
    return DeletionResult(path=path, ok=True, target=None)


def _safe_rel_tail(src: Path) -> Path:
    """Build a relative quarantine sub-path that preserves enough of the source."""
    try:
        anchor = src.anchor  # 'C:\\' on Windows
        rest = str(src)[len(anchor):]
        rest = rest.replace(":", "_")  # paranoia
        return Path(anchor.replace("\\", "").replace(":", "")) / rest
    except Exception:  # noqa: BLE001
        return Path(src.name)


def _ensure_unique(dest: Path) -> Path:
    if not dest.exists():
        return dest
    stem = dest.stem
    suffix = dest.suffix
    parent = dest.parent
    i = 1
    while True:
        candidate = parent / f"{stem} ({i}){suffix}"
        if not candidate.exists():
            return candidate
        i += 1


def _safe_size_before(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def collect_protected_paths(groups) -> Set[str]:
    """Helper for the GUI: collect every keeper across all groups."""
    out: Set[str] = set()
    for g in groups:
        if g.keeper_path:
            out.add(g.keeper_path)
    return out