"""Keep-rule strategies: decide which file in a duplicate group to preserve."""

from __future__ import annotations

import logging
from typing import Callable, Dict, Optional

from ..config import (
    KEEP_HIGHEST_RES,
    KEEP_LARGEST,
    KEEP_LONGEST,
    KEEP_MANUAL,
    KEEP_NEWEST,
    KEEP_OLDEST,
)
from .methods.m4_metadata import get_or_fetch_metadata
from .methods.base import MethodContext
from .models import DuplicateGroup, VideoFile

LOG = logging.getLogger(__name__)


# A keep-rule is a function taking (group, ctx) and returning the file to keep.
KeepRuleFn = Callable[[DuplicateGroup, Optional[MethodContext]], Optional[VideoFile]]


def keep_largest_size(group: DuplicateGroup, ctx: Optional[MethodContext]) -> Optional[VideoFile]:
    return max(group.files, key=lambda f: (f.size, f.path.lower()))


def keep_newest(group: DuplicateGroup, ctx: Optional[MethodContext]) -> Optional[VideoFile]:
    return max(group.files, key=lambda f: (f.mtime, f.path.lower()))


def keep_oldest(group: DuplicateGroup, ctx: Optional[MethodContext]) -> Optional[VideoFile]:
    return min(group.files, key=lambda f: (f.mtime, f.path.lower()))


def keep_highest_resolution(
    group: DuplicateGroup, ctx: Optional[MethodContext]
) -> Optional[VideoFile]:
    def res_score(f: VideoFile) -> tuple:
        pixels = 0
        if ctx is not None:
            md = get_or_fetch_metadata(f, ctx)
            if md and md.width and md.height:
                pixels = md.width * md.height
        return (pixels, f.size)
    return max(group.files, key=res_score)


def keep_longest_duration(
    group: DuplicateGroup, ctx: Optional[MethodContext]
) -> Optional[VideoFile]:
    def dur_score(f: VideoFile) -> tuple:
        dur = 0.0
        if ctx is not None:
            md = get_or_fetch_metadata(f, ctx)
            if md and md.duration_sec:
                dur = md.duration_sec
        return (dur, f.size)
    return max(group.files, key=dur_score)


def keep_manual(group: DuplicateGroup, ctx: Optional[MethodContext]) -> Optional[VideoFile]:
    """No automatic pick — the user must select via the GUI."""
    return None


RULES: Dict[str, KeepRuleFn] = {
    KEEP_LARGEST: keep_largest_size,
    KEEP_NEWEST: keep_newest,
    KEEP_OLDEST: keep_oldest,
    KEEP_HIGHEST_RES: keep_highest_resolution,
    KEEP_LONGEST: keep_longest_duration,
    KEEP_MANUAL: keep_manual,
}

DISPLAY_NAMES: Dict[str, str] = {
    KEEP_LARGEST: "Largest file size",
    KEEP_NEWEST: "Newest (most recent date)",
    KEEP_OLDEST: "Oldest (earliest date)",
    KEEP_HIGHEST_RES: "Highest resolution",
    KEEP_LONGEST: "Longest duration",
    KEEP_MANUAL: "Manual selection only",
}


def apply_keep_rule(
    group: DuplicateGroup,
    rule_id: str,
    ctx: Optional[MethodContext] = None,
) -> Optional[VideoFile]:
    """Return the file the rule recommends keeping; updates ``group.keeper_path``."""
    fn = RULES.get(rule_id, keep_largest_size)
    keeper = fn(group, ctx)
    group.keeper_path = keeper.path if keeper is not None else None
    return keeper


def apply_to_all(
    groups, rule_id: str, ctx: Optional[MethodContext] = None
) -> None:
    """Apply the keep-rule to every group in-place."""
    for g in groups:
        apply_keep_rule(g, rule_id, ctx)
