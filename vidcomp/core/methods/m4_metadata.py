"""M4 — ffprobe metadata signature.

Two files match when their metadata-tuple matches within configured
tolerances (duration, fps).  Resolution, codec, audio-channels must match
exactly.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from typing import Any, Optional, Tuple

from ...config import METHOD_METADATA
from .. import media
from ..models import MediaMetadata, VideoFile
from .base import ComparisonMethod, MethodContext

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class MetadataSignature:
    duration_bucket: Optional[float]
    width: Optional[int]
    height: Optional[int]
    video_codec: Optional[str]
    fps_bucket: Optional[float]
    audio_codec: Optional[str]
    audio_channels: Optional[int]


class MetadataMethod(ComparisonMethod):
    id = METHOD_METADATA
    display_name = "Container & stream metadata"
    kind = "signature"
    description = (
        "Compares duration, resolution, codecs and audio channels reported by ffprobe. "
        "Catches re-muxed or container-changed duplicates very quickly."
    )

    # ------------------------------------------------------------------
    def compute_signature(
        self, file: VideoFile, ctx: MethodContext
    ) -> Optional[Tuple[Any, ...]]:
        md = self._fetch_metadata(file, ctx)
        if md is None or not md.has_video:
            return None
        dur_tol = float(getattr(ctx.config, "metadata_duration_tolerance_sec", 0.5))
        fps_tol = float(getattr(ctx.config, "metadata_fps_tolerance", 0.1))
        dur_bucket = None
        if md.duration_sec is not None and dur_tol > 0:
            dur_bucket = round(md.duration_sec / dur_tol)
        fps_bucket = None
        if md.fps is not None and fps_tol > 0:
            fps_bucket = round(md.fps / fps_tol)
        return (
            dur_bucket,
            md.width,
            md.height,
            md.video_codec,
            fps_bucket,
            md.audio_codec,
            md.audio_channels,
        )

    # ------------------------------------------------------------------
    def _fetch_metadata(
        self, file: VideoFile, ctx: MethodContext
    ) -> Optional[MediaMetadata]:
        if file.path in ctx.metadata_cache:
            return ctx.metadata_cache[file.path]
        cached_json = ctx.cache.get_text(file.path, file.size, file.mtime, "ffprobe_json")
        if cached_json is not None:
            try:
                md = media.parse_ffprobe_json(cached_json)
                ctx.metadata_cache[file.path] = md
                return md
            except (ValueError, json.JSONDecodeError):
                LOG.debug("Cached ffprobe json was unparseable for %s", file.path)
        try:
            md = media.probe_metadata(file.path, cancel_event=ctx.cancel_event)
        except Exception as exc:  # noqa: BLE001
            LOG.warning("ffprobe failed for %s: %s", file.path, exc)
            return None
        if md.raw_json:
            ctx.cache.put_text(
                file.path, file.size, file.mtime, "ffprobe_json", md.raw_json
            )
        ctx.metadata_cache[file.path] = md
        return md


def get_or_fetch_metadata(
    file: VideoFile, ctx: MethodContext
) -> Optional[MediaMetadata]:
    """Shared helper so other methods can reuse the metadata cache."""
    return MetadataMethod()._fetch_metadata(file, ctx)
