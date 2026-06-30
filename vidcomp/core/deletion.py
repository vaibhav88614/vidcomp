"""Safe deletion of duplicate files.

Supports three modes: Recycle Bin (reversible), move to a quarantine folder,
and permanent delete.  A safety check guarantees that at least one file in each
duplicate group always survives, regardless of what the caller requests.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Iterable, Optional

from .models import DeleteMode, DeletionResult, DuplicateGroup

log = logging.getLogger("vidcomp.deletion")

try:
    from send2trash import send2trash  # type: ignore

    _HAVE_SEND2TRASH = True
except Exception:  # pragma: no cover - import guard
    _HAVE_SEND2TRASH = False


class SurvivorViolation(Exception):
    """Raised when a deletion request would wipe out an entire group."""


def enforce_survivors(
    selected_paths: Iterable[str], groups: Iterable[DuplicateGroup]
) -> list[str]:
    """Validate that no group would lose all of its files.

    Returns the (deduplicated) list of paths cleared for deletion.  Raises
    :class:`SurvivorViolation` listing offending groups if any group has every
    member selected.
    """
    selected = set(selected_paths)
    offending: list[str] = []
    for i, g in enumerate(groups, start=1):
        group_paths = {f.path for f in g.files}
        if group_paths and group_paths.issubset(selected):
            survivors = group_paths - selected
            if not survivors:
                offending.append(f"group #{i} ({len(group_paths)} files)")
    if offending:
        raise SurvivorViolation(
            "Refusing to delete every file in: " + ", ".join(offending)
        )
    return sorted(selected)


def _quarantine_destination(path: str, quarantine_root: str) -> str:
    """Compute a collision-free destination preserving the drive/relative path."""
    drive, rest = os.path.splitdrive(path)
    drive_token = drive.replace(":", "").replace("\\", "").replace("/", "") or "root"
    rel = rest.lstrip("\\/")
    dest = os.path.join(quarantine_root, drive_token, rel)
    base, ext = os.path.splitext(dest)
    candidate = dest
    n = 1
    while os.path.exists(candidate):
        candidate = f"{base}__{n}{ext}"
        n += 1
    return candidate


def delete_path(
    path: str,
    mode: DeleteMode,
    quarantine_root: Optional[str] = None,
) -> DeletionResult:
    """Delete a single file according to ``mode``."""
    log.debug("delete_path mode=%s quarantine=%s path=%s", mode.value, quarantine_root, path)
    if not os.path.exists(path):
        log.warning("delete: file vanished before deletion: %s", path)
        return DeletionResult(path, False, mode, error="file no longer exists")
    try:
        if mode == DeleteMode.RECYCLE_BIN:
            if not _HAVE_SEND2TRASH:
                return DeletionResult(
                    path, False, mode,
                    error="send2trash not installed; cannot use Recycle Bin",
                )
            send2trash(os.path.abspath(path))
            log.info("delete: recycled %s", path)
            return DeletionResult(path, True, mode)

        if mode == DeleteMode.QUARANTINE:
            if not quarantine_root:
                return DeletionResult(path, False, mode, error="no quarantine folder set")
            dest = _quarantine_destination(path, quarantine_root)
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.move(path, dest)
            log.info("delete: quarantined %s -> %s", path, dest)
            return DeletionResult(path, True, mode, destination=dest)

        if mode == DeleteMode.PERMANENT:
            os.remove(path)
            log.info("delete: PERMANENTLY removed %s", path)
            return DeletionResult(path, True, mode)

        return DeletionResult(path, False, mode, error=f"unknown mode {mode}")
    except PermissionError as exc:
        return DeletionResult(path, False, mode, error=f"permission denied / file in use: {exc}")
    except OSError as exc:
        return DeletionResult(path, False, mode, error=str(exc))


def delete_paths(
    paths: Iterable[str],
    mode: DeleteMode,
    quarantine_root: Optional[str] = None,
    groups: Optional[Iterable[DuplicateGroup]] = None,
) -> list[DeletionResult]:
    """Delete many files, optionally enforcing the per-group survivor rule."""
    path_list = list(paths)
    if groups is not None:
        path_list = enforce_survivors(path_list, list(groups))
    results: list[DeletionResult] = []
    for p in path_list:
        res = delete_path(p, mode, quarantine_root)
        if not res.success:
            log.warning("delete failed for %s: %s", p, res.error)
        results.append(res)
    return results
