"""M2 — full SHA-256 hash (exact byte-identical duplicate detection)."""

from __future__ import annotations

import hashlib
import logging
from typing import Optional

from ...config import METHOD_SHA256
from ..models import VideoFile
from .base import ComparisonMethod, MethodContext

LOG = logging.getLogger(__name__)

_CHUNK = 1024 * 1024  # 1 MiB read chunks


class Sha256Method(ComparisonMethod):
    id = METHOD_SHA256
    display_name = "SHA-256 (full file hash)"
    kind = "signature"
    description = "Exact byte-by-byte hash. Two files with the same SHA-256 are identical."

    def compute_signature(self, file: VideoFile, ctx: MethodContext) -> Optional[str]:
        cached = ctx.cache.get_text(file.path, file.size, file.mtime, self.id)
        if cached is not None:
            return cached
        digest = self._hash_file(file.path, ctx)
        if digest is None:
            return None
        ctx.cache.put_text(file.path, file.size, file.mtime, self.id, digest)
        return digest

    @staticmethod
    def _hash_file(path: str, ctx: MethodContext) -> Optional[str]:
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                while True:
                    if ctx.is_cancelled():
                        return None
                    chunk = f.read(_CHUNK)
                    if not chunk:
                        break
                    h.update(chunk)
        except OSError as exc:
            LOG.warning("SHA-256 read failed for %s: %s", path, exc)
            return None
        return h.hexdigest()
