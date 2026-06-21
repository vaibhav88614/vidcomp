"""M6 — SSIM (structural similarity) via ffmpeg ``ssim`` filter."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...config import METHOD_SSIM
from .. import media
from ..models import MatchEvidence, VideoFile
from .base import ComparisonMethod, MethodContext
from .m4_metadata import get_or_fetch_metadata

LOG = logging.getLogger(__name__)


class SsimMethod(ComparisonMethod):
    id = METHOD_SSIM
    display_name = "SSIM (structural similarity)"
    kind = "pairwise"
    description = (
        "Frame-by-frame structural similarity computed by ffmpeg's `ssim` filter. "
        "Higher is more similar (max 1.0)."
    )

    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[Any],
        sig_b: Optional[Any],
        ctx: MethodContext,
    ) -> MatchEvidence:
        threshold = float(getattr(ctx.config, "ssim_threshold", 0.95))
        cached = ctx.cache.get_pair(a.path, b.path, a.mtime, b.mtime, self.id)
        if cached is not None:
            return self._evidence(cached, threshold)
        md_a = get_or_fetch_metadata(a, ctx)
        md_b = get_or_fetch_metadata(b, ctx)
        if ctx.is_cancelled():
            return MatchEvidence(
                self.id, False, 0.0, detail="cancelled", abstain=True
            )
        score = media.run_ssim(
            a.path, b.path,
            duration_a=(md_a.duration_sec if md_a else None),
            duration_b=(md_b.duration_sec if md_b else None),
            cancel_event=ctx.cancel_event,
        )
        if score is None:
            return MatchEvidence(
                self.id, False, 0.0, detail="ssim failed", abstain=True
            )
        ctx.cache.put_pair(a.path, b.path, a.mtime, b.mtime, self.id, score)
        return self._evidence(score, threshold)

    def _evidence(self, score: float, threshold: float) -> MatchEvidence:
        return MatchEvidence(
            method_id=self.id,
            matched=score >= threshold,
            score=score,
            detail=f"ssim={score:.4f} ≥ {threshold:.2f}" if score >= threshold
                   else f"ssim={score:.4f} < {threshold:.2f}",
        )
