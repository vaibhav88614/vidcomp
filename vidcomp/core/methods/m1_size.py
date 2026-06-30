"""M1 - File size match (instant pre-filter)."""

from __future__ import annotations

from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext


class SizeMethod(ComparisonMethod):
    """Two files match when their byte sizes are identical.

    This is the cheapest possible signal and primarily exists to bucket
    candidates; on its own it is weak, so the engine usually pairs it with a
    hash for confirmation.
    """

    method_id = MethodId.SIZE

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        if a.size == b.size and a.size > 0:
            return MatchEvidence(
                method=MethodId.SIZE,
                score=1.0,
                detail=f"identical size ({a.size} bytes)",
            )
        return None
