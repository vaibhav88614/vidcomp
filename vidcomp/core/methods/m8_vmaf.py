"""M8 - VMAF (Netflix perceptual quality metric) via ffmpeg libvmaf (optional)."""

from __future__ import annotations

from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext


class VmafMethod(ComparisonMethod):
    """Match when the mean VMAF score exceeds a configurable threshold.

    Only available when the resolved ffmpeg build exposes ``libvmaf``; the
    engine and GUI disable the method gracefully otherwise.
    """

    method_id = MethodId.VMAF
    expensive = True
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_ffmpeg and ctx.tools.has_vmaf()

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        key = ("vmaf", frozenset((a.path, b.path)))
        if key in ctx.pair_cache:
            score = ctx.pair_cache[key]
        else:
            score = ctx.tools.vmaf(a.path, b.path)
            ctx.pair_cache[key] = score
        if score is None:
            return None
        threshold = float(getattr(ctx.options, "vmaf_threshold", 90.0))
        if score >= threshold:
            return MatchEvidence(
                method=MethodId.VMAF,
                score=round(min(1.0, score / 100.0), 3),
                detail=f"VMAF {score:.1f} >= {threshold:.1f}",
            )
        return None
