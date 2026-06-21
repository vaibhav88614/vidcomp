"""M7 — PSNR (peak signal-to-noise ratio) via ffmpeg ``psnr`` filter."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ...config import METHOD_PSNR
from .. import media
from ..models import MatchEvidence, VideoFile
from .base import ComparisonMethod, MethodContext
from .m4_metadata import get_or_fetch_metadata

LOG = logging.getLogger(__name__)


class PsnrMethod(ComparisonMethod):
    id = METHOD_PSNR
    display_name = "PSNR (peak signal-to-noise ratio)"
    kind = "pairwise"
    description = (
        "Peak signal-to-noise ratio in dB.  Identical inputs hit infinity; "
        "values above ~30 dB usually indicate the same content."
    )

    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[Any],
        sig_b: Optional[Any],
        ctx: MethodContext,
    ) -> MatchEvidence:
        threshold = float(getattr(ctx.config, "psnr_threshold", 30.0))
        cached = ctx.cache.get_pair(a.path, b.path, a.mtime, b.mtime, self.id)
        if cached is not None:
            return self._evidence(cached, threshold)
        md_a = get_or_fetch_metadata(a, ctx)
        md_b = get_or_fetch_metadata(b, ctx)
        if ctx.is_cancelled():
            return MatchEvidence(
                self.id, False, 0.0, detail="cancelled", abstain=True
            )
        score = media.run_psnr(
            a.path, b.path,
            duration_a=(md_a.duration_sec if md_a else None),
            duration_b=(md_b.duration_sec if md_b else None),
            cancel_event=ctx.cancel_event,
        )
        if score is None:
            return MatchEvidence(
                self.id, False, 0.0, detail="psnr failed", abstain=True
            )
        ctx.cache.put_pair(a.path, b.path, a.mtime, b.mtime, self.id, score)
        return self._evidence(score, threshold)

    def _evidence(self, score: float, threshold: float) -> MatchEvidence:
        return MatchEvidence(
            method_id=self.id,
            matched=score >= threshold,
            score=score,
            detail=f"psnr={score:.2f}dB ≥ {threshold:.1f}dB" if score >= threshold
                   else f"psnr={score:.2f}dB < {threshold:.1f}dB",
        )
