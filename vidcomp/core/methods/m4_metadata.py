"""M4 - Metadata comparison via ffprobe.

Compares duration, resolution, codec, bitrate, fps and audio channels with
sensible tolerances.  This catches exact copies and near-exact remuxes and also
acts as a cheap gate before perceptual/structural comparisons.
"""

from __future__ import annotations

from typing import Optional

from ..models import MatchEvidence, MediaInfo, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext


def _duration_close(a: Optional[float], b: Optional[float], tol: float = 1.0) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(tol, 0.02 * max(a, b))


class MetadataMethod(ComparisonMethod):
    """Match on container/stream metadata similarity."""

    method_id = MethodId.METADATA
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_ffprobe

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.info is None:
            vf.info = ctx.tools.probe(vf.path)

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        ia, ib = a.info, b.info
        if not ia or not ib or not ia.ok or not ib.ok:
            return None

        # Duration is the strongest single metadata signal.
        if not _duration_close(ia.duration, ib.duration):
            return None

        matches: list[str] = ["duration"]
        score_parts: list[float] = [1.0]

        if ia.resolution and ib.resolution:
            if ia.resolution == ib.resolution:
                matches.append("resolution")
                score_parts.append(1.0)
            else:
                score_parts.append(0.5)

        if ia.video_codec and ib.video_codec:
            if ia.video_codec == ib.video_codec:
                matches.append("codec")
                score_parts.append(1.0)
            else:
                score_parts.append(0.6)

        if ia.fps and ib.fps and abs(ia.fps - ib.fps) <= 0.5:
            matches.append("fps")
            score_parts.append(1.0)

        if ia.audio_channels and ib.audio_channels and ia.audio_channels == ib.audio_channels:
            matches.append("audio-ch")

        if ia.bitrate and ib.bitrate:
            hi = max(ia.bitrate, ib.bitrate)
            if hi and abs(ia.bitrate - ib.bitrate) / hi <= 0.1:
                matches.append("bitrate")

        score = sum(score_parts) / len(score_parts)
        # Require at least duration + one more attribute to call it a match.
        if len(matches) < 2:
            return None
        return MatchEvidence(
            method=MethodId.METADATA,
            score=round(score, 3),
            detail="metadata match: " + ", ".join(matches),
        )
