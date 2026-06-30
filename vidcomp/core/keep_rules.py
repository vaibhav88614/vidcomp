"""Keep-rule logic: decide which file in each group to protect from deletion.

Always guarantees at least one survivor per group.  Used both to set the
recommended "keep" badge and to drive the "Select all duplicates" action.
"""

from __future__ import annotations

from typing import Iterable, Optional

from .models import DuplicateGroup, KeepRule, VideoFile


def _resolution(vf: VideoFile) -> int:
    return vf.info.pixels if vf.info else 0


def _duration(vf: VideoFile) -> float:
    return (vf.info.duration or 0.0) if vf.info else 0.0


def pick_keeper(group: DuplicateGroup, rule: KeepRule) -> Optional[VideoFile]:
    """Return the file to KEEP for the given rule (None only if group empty)."""
    files = group.files
    if not files:
        return None
    if rule == KeepRule.MANUAL:
        # No automatic preference; keep the first as a safe default.
        return files[0]

    if rule == KeepRule.HIGHEST_RESOLUTION:
        return max(files, key=lambda f: (_resolution(f), f.size))
    if rule == KeepRule.LARGEST_SIZE:
        return max(files, key=lambda f: (f.size, _resolution(f)))
    if rule == KeepRule.LONGEST_DURATION:
        return max(files, key=lambda f: (_duration(f), f.size))
    if rule == KeepRule.NEWEST:
        return max(files, key=lambda f: f.mtime)
    if rule == KeepRule.OLDEST:
        return min(files, key=lambda f: f.mtime)
    return files[0]


def apply_keep_rule(groups: Iterable[DuplicateGroup], rule: KeepRule) -> None:
    """Set ``group.keep_path`` for every group according to ``rule``."""
    for g in groups:
        keeper = pick_keeper(g, rule)
        g.keep_path = keeper.path if keeper else None


def auto_select_duplicates(group: DuplicateGroup, rule: KeepRule) -> list[str]:
    """Return the paths to select for deletion in a group (never the keeper).

    Guarantees at least one survivor: the keeper is always excluded.
    """
    keeper = pick_keeper(group, rule)
    keep_path = keeper.path if keeper else (group.files[0].path if group.files else None)
    return [f.path for f in group.files if f.path != keep_path]
