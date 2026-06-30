"""M3 - Partial/quick hash (first + last N bytes) for fast pre-filtering."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ..models import MatchEvidence, MethodId, VideoFile
from .base import ComparisonMethod, MethodContext

log = logging.getLogger("vidcomp.methods.partial")


def partial_hash_of(path: str, size: int, n_bytes: int) -> Optional[str]:
    """Hash the first and last ``n_bytes`` of a file plus its total size.

    Including the size guards against collisions between files that happen to
    share head/tail bytes but differ in length.
    """
    h = hashlib.sha256()
    h.update(str(size).encode("ascii"))
    try:
        with open(path, "rb") as fh:
            head = fh.read(n_bytes)
            h.update(head)
            if size > n_bytes:
                seek_to = max(n_bytes, size - n_bytes)
                fh.seek(seek_to)
                h.update(fh.read(n_bytes))
        return h.hexdigest()
    except OSError as exc:
        log.debug("partial hash failed for %s: %s", path, exc)
        return None


class PartialHashMethod(ComparisonMethod):
    """Quick head+tail hash; a strong (but not definitive) duplicate signal."""

    method_id = MethodId.PARTIAL_HASH

    def prepare(self, vf: VideoFile, ctx: MethodContext) -> None:
        if vf.partial_hash is None:
            n = getattr(ctx.options, "partial_hash_bytes", 1 << 20)
            vf.partial_hash = partial_hash_of(vf.path, vf.size, n)

    def compare(
        self, a: VideoFile, b: VideoFile, ctx: MethodContext
    ) -> Optional[MatchEvidence]:
        if a.partial_hash and b.partial_hash and a.partial_hash == b.partial_hash:
            return MatchEvidence(
                method=MethodId.PARTIAL_HASH,
                score=0.95,
                detail="matching head+tail quick hash",
            )
        return None
