"""M1 — file-size signature (free, instant pre-filter)."""

from __future__ import annotations

from typing import Optional

from ...config import METHOD_SIZE
from ..models import VideoFile
from .base import ComparisonMethod, MethodContext


class SizeMethod(ComparisonMethod):
    id = METHOD_SIZE
    display_name = "File size"
    kind = "signature"
    description = "Group files by exact byte size — instant first-pass filter."

    def compute_signature(self, file: VideoFile, ctx: MethodContext) -> Optional[int]:
        return file.size
