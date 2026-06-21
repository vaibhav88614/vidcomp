"""M3 — partial / quick hash (first + last N bytes + size).

A cheap pre-filter that catches identical files long before we read the
whole file.  Implemented as ``SHA-256(head || tail || size)``.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ...config import METHOD_PARTIAL_HASH
from ..models import VideoFile
from .base import ComparisonMethod, MethodContext

LOG = logging.getLogger(__name__)


class PartialHashMethod(ComparisonMethod):
    id = METHOD_PARTIAL_HASH
    display_name = "Partial hash (head + tail)"
    kind = "signature"
    description = (
        "Hashes only the first and last N bytes of each file, plus its size. "
        "Very fast, great pre-filter before expensive checks."
    )

    def compute_signature(self, file: VideoFile, ctx: MethodContext) -> Optional[str]:
        cached = ctx.cache.get_text(file.path, file.size, file.mtime, self.id)
        if cached is not None:
            return cached
        n = max(4096, int(getattr(ctx.config, "partial_hash_bytes", 1024 * 1024)))
        digest = self._partial_hash(file.path, file.size, n)
        if digest is None:
            return None
        ctx.cache.put_text(file.path, file.size, file.mtime, self.id, digest)
        return digest

    @staticmethod
    def _partial_hash(path: str, size: int, n: int) -> Optional[str]:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                head = f.read(n)
                h.update(head)
                if size > n * 2:
                    f.seek(-n, 2)
                    tail = f.read(n)
                    h.update(tail)
                h.update(str(size).encode())
        except OSError as exc:
            LOG.warning("Partial hash read failed for %s: %s", path, exc)
            return None
        return h.hexdigest()
