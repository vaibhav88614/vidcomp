"""M2 - Full SHA-256 hash (exact byte-identical duplicate detection)."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext

log = logging.getLogger("vidcomp.methods.sha256")

_CHUNK = 1 << 20  # 1 MiB read chunks


def sha256_of(path: str) -> Optional[str]:
    """Return the hex SHA-256 of a file, or ``None`` if it cannot be read."""
    h = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            while True:
                chunk = fh.read(_CHUNK)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except OSError as exc:
        log.debug("sha256 read failed for %s: %s", path, exc)
        return None


class Sha256Method(ComparisonMethod):
    """Confirms byte-identical files via full-content SHA-256."""

    method_id = MethodId.SHA256

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.sha256 is None:
            vf.sha256 = sha256_of(vf.path)

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        if a.sha256 and b.sha256 and a.sha256 == b.sha256:
            return MatchEvidence(
                method=MethodId.SHA256,
                score=1.0,
                detail="identical SHA-256 (byte-for-byte duplicate)",
            )
        return None
