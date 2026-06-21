"""M9 — Chromaprint audio fingerprint.

Signature-style method: each file gets a fingerprint cached as JSON
(``{"duration":..,"fp":[...]}``); two files match when their
fingerprint similarity is above the configured threshold.

The engine still evaluates this *between* candidate pairs (it's a
similarity, not a hash equality), but the costly part (running ``fpcalc``)
is cached per-file rather than per-pair.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from ...config import METHOD_AUDIO
from .. import media
from ..models import MatchEvidence, VideoFile
from .base import ComparisonMethod, MethodContext

LOG = logging.getLogger(__name__)


class AudioFingerprintMethod(ComparisonMethod):
    id = METHOD_AUDIO
    display_name = "Audio fingerprint (Chromaprint)"
    kind = "signature"
    description = (
        "Chromaprint audio fingerprint via fpcalc.  Matches files with the same "
        "or near-identical audio regardless of video encoding."
    )

    def compute_signature(
        self, file: VideoFile, ctx: MethodContext
    ) -> Optional[bytes]:
        if not media.has_fpcalc():
            return None
        cached = ctx.cache.get_artifact(file.path, file.size, file.mtime, self.id)
        if cached is not None:
            return cached
        fp = media.audio_fingerprint(file.path, cancel_event=ctx.cancel_event)
        if fp is None:
            return None
        duration, raw = fp
        payload = json.dumps({"duration": duration, "fp": raw}).encode("utf-8")
        ctx.cache.put_artifact(file.path, file.size, file.mtime, self.id, payload)
        return payload

    def evaluate_pair(
        self,
        a: VideoFile,
        b: VideoFile,
        sig_a: Optional[bytes],
        sig_b: Optional[bytes],
        ctx: MethodContext,
    ) -> MatchEvidence:
        if not sig_a or not sig_b:
            return MatchEvidence(
                self.id, False, 0.0, detail="no fingerprint", abstain=True
            )
        fp_a = decode_fingerprint(sig_a)
        fp_b = decode_fingerprint(sig_b)
        if not fp_a or not fp_b:
            return MatchEvidence(
                self.id, False, 0.0, detail="invalid fingerprint", abstain=True
            )
        sim = media.fingerprint_similarity(fp_a, fp_b)
        threshold = float(getattr(ctx.config, "audio_threshold", 0.85))
        matched = sim >= threshold
        return MatchEvidence(
            method_id=self.id,
            matched=matched,
            score=sim,
            detail=(f"audio sim={sim:.3f} "
                    f"{'≥' if matched else '<'} {threshold:.2f}"),
        )


def decode_fingerprint(blob: bytes) -> Optional[list[int]]:
    """Return the raw integer fingerprint list from a cached blob, or None."""
    if not blob:
        return None
    try:
        data = json.loads(blob.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    fp = data.get("fp")
    if not isinstance(fp, list):
        return None
    try:
        return [int(x) for x in fp]
    except (TypeError, ValueError):
        return None
