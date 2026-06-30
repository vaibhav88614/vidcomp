"""M9 - Audio fingerprint match via Chromaprint (fpcalc).

Compares the raw Chromaprint fingerprints of two files using a bit-error-rate
over the best sliding alignment.  This matches identical or near-identical
audio tracks regardless of the video encoding.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext

log = logging.getLogger("vidcomp.methods.audio")

_POPCOUNT = bytes(bin(i).count("1") for i in range(256))


def _to_ints(fp: Optional[str]) -> List[int]:
    if not fp:
        return []
    out: List[int] = []
    for tok in fp.split(","):
        tok = tok.strip()
        if not tok:
            continue
        try:
            out.append(int(tok) & 0xFFFFFFFF)
        except ValueError:
            continue
    return out


def _bit_similarity(a: List[int], b: List[int], max_offset: int = 80) -> Optional[float]:
    """Best 0..1 similarity over a limited sliding alignment of two raw FPs."""
    if not a or not b:
        return None
    best = 0.0
    la, lb = len(a), len(b)
    offsets = range(-min(max_offset, lb - 1), min(max_offset, la - 1) + 1)
    for off in offsets:
        # Align a[i+off] with b[i].
        start_a = max(0, off)
        start_b = max(0, -off)
        n = min(la - start_a, lb - start_b)
        if n <= 0:
            continue
        diff_bits = 0
        for i in range(n):
            x = a[start_a + i] ^ b[start_b + i]
            diff_bits += (
                _POPCOUNT[x & 0xFF]
                + _POPCOUNT[(x >> 8) & 0xFF]
                + _POPCOUNT[(x >> 16) & 0xFF]
                + _POPCOUNT[(x >> 24) & 0xFF]
            )
        sim = 1.0 - (diff_bits / (32.0 * n))
        if sim > best:
            best = sim
    return best


class AudioFingerprintMethod(ComparisonMethod):
    """Chromaprint/AcoustID-based audio similarity matching."""

    method_id = MethodId.AUDIO
    expensive = True
    needs_tools = True

    def available(self, ctx: MethodContext) -> bool:
        return ctx.tools.has_fpcalc

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.audio_fingerprint is not None:
            return
        if not self.available(ctx):
            return
        fp, dur = ctx.tools.fingerprint(vf.path)
        vf.audio_fingerprint = fp or ""
        vf.audio_fp_duration = dur

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        ia = _to_ints(a.audio_fingerprint)
        ib = _to_ints(b.audio_fingerprint)
        if not ia or not ib:
            return None
        sim = _bit_similarity(ia, ib)
        if sim is None:
            return None
        threshold = float(getattr(ctx.options, "audio_threshold", 0.85))
        if sim >= threshold:
            return MatchEvidence(
                method=MethodId.AUDIO,
                score=round(sim, 3),
                detail=f"audio fingerprint similarity {sim:.2f} >= {threshold:.2f}",
            )
        return None
