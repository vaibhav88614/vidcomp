"""M8 — VMAF (Netflix perceptual quality) via ffmpeg ``libvmaf`` filter.

Auto-disabled at the engine level when :func:`media.has_libvmaf` is False;
this module simply returns a non-matching evidence with a helpful detail
string if it ever runs without libvmaf so the user sees what happened.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...config import METHOD_VMAF
from .. import media
from ..models import MatchEvidence, VideoFile
from .base import ComparisonMethod, MethodContext
from .m4_metadata import get_or_fetch_metadata

LOG = logging.getLogger(__name__)


class VmafMethod(ComparisonMethod):
    id = METHOD_VMAF
    display_name = "VMAF (Netflix perceptual quality)"
    kind = "pairwise"
    description = (
        "VMAF perceptual quality score from ffmpeg's libvmaf filter. "
        "Range 0..100; same-content pairs score 90+ on similar encodes. "
        "Requires an ffmpeg build with libvmaf."
    )

    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[Any],
        sig_b: Optional[Any],
        ctx: MethodContext,
    ) -> MatchEvidence:
        threshold = float(getattr(ctx.config, "vmaf_threshold", 90.0))
        if not media.has_libvmaf():
            return MatchEvidence(
                self.id, False, 0.0, detail="libvmaf not available", abstain=True
            )
        cached = ctx.cache.get_pair(a.path, b.path, a.mtime, b.mtime, self.id)
        if cached is not None:
            return self._evidence(cached, threshold)
        md_a = get_or_fetch_metadata(a, ctx)
        md_b = get_or_fetch_metadata(b, ctx)
        if ctx.is_cancelled():
            return MatchEvidence(
                self.id, False, 0.0, detail="cancelled", abstain=True
            )
        score = media.run_vmaf(
            a.path, b.path,
            duration_a=(md_a.duration_sec if md_a else None),
            duration_b=(md_b.duration_sec if md_b else None),
            cancel_event=ctx.cancel_event,
        )
        if score is None:
            return MatchEvidence(
                self.id, False, 0.0, detail="vmaf failed", abstain=True
            )
        ctx.cache.put_pair(a.path, b.path, a.mtime, b.mtime, self.id, score)
        return self._evidence(score, threshold)

    def _evidence(self, score: float, threshold: float) -> MatchEvidence:
        return MatchEvidence(
            method_id=self.id,
            matched=score >= threshold,
            score=score,
            detail=f"vmaf={score:.2f} ≥ {threshold:.1f}" if score >= threshold
                   else f"vmaf={score:.2f} < {threshold:.1f}",
        )
