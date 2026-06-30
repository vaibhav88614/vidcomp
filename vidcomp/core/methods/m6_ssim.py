"""M6 - Structural Similarity (SSIM) on sampled/aligned frames via ffmpeg."""

from __future__ import annotations

from typing import Optional, Tuple

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext


def get_ssim_psnr(a: VideoFile, b: VideoFile, ctx: MethodContext) -> Tuple[Optional[float], Optional[float]]:
    """Memoized SSIM+PSNR for a pair so M6 and M7 share one ffmpeg run."""
    key = frozenset((a.path, b.path))
    if key in ctx.pair_cache:
        return ctx.pair_cache[key]
    result = ctx.tools.ssim_psnr(a.path, b.path)
    ctx.pair_cache[key] = result
    return result


class SsimMethod(ComparisonMethod):
    """Match when the mean SSIM across compared frames exceeds a threshold."""

    method_id = MethodId.SSIM
    expensive = True
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_ffmpeg

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        ssim, _psnr = get_ssim_psnr(a, b, ctx)
        if ssim is None:
            return None
        threshold = float(getattr(ctx.options, "ssim_threshold", 0.92))
        if ssim >= threshold:
            return MatchEvidence(
                method=MethodId.SSIM,
                score=round(min(1.0, ssim), 3),
                detail=f"SSIM {ssim:.3f} >= {threshold:.3f}",
            )
        return None
