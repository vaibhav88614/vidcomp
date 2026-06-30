"""M7 - Peak Signal-to-Noise Ratio (PSNR) on aligned frames via ffmpeg."""

from __future__ import annotations

from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext
from .m6_ssim import get_ssim_psnr


class PsnrMethod(ComparisonMethod):
    """Match when the mean PSNR (dB) exceeds a configurable threshold."""

    method_id = MethodId.PSNR
    expensive = True
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_ffmpeg

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        _ssim, psnr = get_ssim_psnr(a, b, ctx)
        if psnr is None:
            return None
        threshold = float(getattr(ctx.options, "psnr_threshold", 30.0))
        if psnr >= threshold:
            # Normalize: 50 dB+ is effectively identical for an 8-bit signal.
            score = min(1.0, psnr / 50.0) if psnr != float("inf") else 1.0
            shown = "inf" if psnr == float("inf") else f"{psnr:.1f}"
            return MatchEvidence(
                method=MethodId.PSNR,
                score=round(score, 3),
                detail=f"PSNR {shown} dB >= {threshold:.1f}",
            )
        return None
