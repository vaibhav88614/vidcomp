"""Application configuration: persistent settings + scan-preset definitions.

The configuration is a single :class:`AppConfig` dataclass.  It can be
serialised to JSON (``%APPDATA%/VidComp/config.json``) and reloaded.

Presets (``easy``, ``medium``, ``robust``) populate the enabled-method set and
thresholds; switching to ``custom`` lets the Advanced panel override anything.
"""

from __future__ import annotations

import json
import os
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import List, Set

LOG = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Method id constants — kept here as plain strings so this module has no
# import dependency on `vidcomp.core.methods` (avoids a circular import).
# The registry in :mod:`vidcomp.core.methods` must use the same ids.
# ---------------------------------------------------------------------------
METHOD_SIZE = "size"
METHOD_PARTIAL_HASH = "partial_hash"
METHOD_SHA256 = "sha256"
METHOD_METADATA = "metadata"
METHOD_PHASH = "phash"
METHOD_SSIM = "ssim"
METHOD_PSNR = "psnr"
METHOD_VMAF = "vmaf"
METHOD_AUDIO = "audio"

ALL_METHODS: List[str] = [
    METHOD_SIZE,
    METHOD_PARTIAL_HASH,
    METHOD_SHA256,
    METHOD_METADATA,
    METHOD_PHASH,
    METHOD_SSIM,
    METHOD_PSNR,
    METHOD_VMAF,
    METHOD_AUDIO,
]

# Default video extensions (case-insensitive, stored without leading dot).
DEFAULT_EXTENSIONS: List[str] = [
    "mp4", "mkv", "avi", "mov", "wmv", "flv", "webm", "m4v",
    "mpg", "mpeg", "3gp", "ts", "m2ts", "vob", "ogv",
]

# Preset names.
PRESET_EASY = "easy"
PRESET_MEDIUM = "medium"
PRESET_ROBUST = "robust"
PRESET_CUSTOM = "custom"
ALL_PRESETS: List[str] = [PRESET_EASY, PRESET_MEDIUM, PRESET_ROBUST, PRESET_CUSTOM]

# Delete modes.
DELETE_RECYCLE = "recycle"
DELETE_QUARANTINE = "quarantine"
DELETE_PERMANENT = "permanent"

# Keep-rule ids.
KEEP_HIGHEST_RES = "highest_resolution"
KEEP_LARGEST = "largest_size"
KEEP_LONGEST = "longest_duration"
KEEP_NEWEST = "newest"
KEEP_OLDEST = "oldest"
KEEP_MANUAL = "manual"
ALL_KEEP_RULES: List[str] = [
    KEEP_HIGHEST_RES,
    KEEP_LARGEST,
    KEEP_LONGEST,
    KEEP_NEWEST,
    KEEP_OLDEST,
    KEEP_MANUAL,
]

# Match combination logic.
MATCH_ANY = "any"
MATCH_ALL = "all"


def _appdata_root() -> Path:
    """Return ``%APPDATA%/VidComp`` (created if missing)."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    root = Path(base) / "VidComp"
    root.mkdir(parents=True, exist_ok=True)
    return root


def default_config_path() -> Path:
    return _appdata_root() / "config.json"


def default_cache_path() -> Path:
    return _appdata_root() / "cache.sqlite"


def default_thumbnail_dir() -> Path:
    d = _appdata_root() / "thumbnails"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_quarantine_dir() -> Path:
    d = _appdata_root() / "quarantine"
    d.mkdir(parents=True, exist_ok=True)
    return d


def default_log_path() -> Path:
    return _appdata_root() / "vidcomp.log"


@dataclass
class AppConfig:
    """Persistent application settings."""

    # ---- scan presets / methods ----
    preset: str = PRESET_MEDIUM
    enabled_methods: Set[str] = field(default_factory=lambda: set())
    match_logic: str = MATCH_ANY  # "any" or "all"

    # ---- filtering ----
    extensions: List[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    min_file_size_bytes: int = 1024  # ignore < 1 KiB
    min_duration_sec: float = 0.0

    # ---- per-method thresholds / params ----
    partial_hash_bytes: int = 1_048_576           # 1 MiB head + tail
    phash_frames: int = 9                         # frames sampled per video
    phash_threshold: int = 8                      # max mean Hamming distance (0..64)
    ssim_threshold: float = 0.95                  # min SSIM
    psnr_threshold: float = 30.0                  # min PSNR in dB
    vmaf_threshold: float = 90.0                  # min VMAF (0..100)
    audio_threshold: float = 0.85                 # min Chromaprint similarity (0..1)

    metadata_duration_tolerance_sec: float = 0.5
    metadata_fps_tolerance: float = 0.1

    # ---- pair-explosion guard ----
    max_pairs_per_bucket: int = 5000

    # ---- worker / performance ----
    worker_count: int = 4

    # ---- deletion ----
    delete_mode: str = DELETE_RECYCLE
    quarantine_path: str = ""                     # filled in __post_init__
    keep_rule: str = KEEP_HIGHEST_RES

    # ---- paths ----
    cache_path: str = ""
    thumbnail_cache_path: str = ""
    thumbnail_cache_max_bytes: int = 500 * 1024 * 1024  # 500 MB
    log_path: str = ""

    # ---- GUI ----
    advanced_panel_open: bool = False
    last_scan_folder: str = ""

    def __post_init__(self) -> None:
        if not self.enabled_methods:
            self.enabled_methods = methods_for_preset(self.preset)
        if not self.quarantine_path:
            self.quarantine_path = str(default_quarantine_dir())
        if not self.cache_path:
            self.cache_path = str(default_cache_path())
        if not self.thumbnail_cache_path:
            self.thumbnail_cache_path = str(default_thumbnail_dir())
        if not self.log_path:
            self.log_path = str(default_log_path())

    # ---- preset helpers ----
    def apply_preset(self, preset: str) -> None:
        """Switch to one of the named presets (overwrites the enabled-method set)."""
        if preset == PRESET_CUSTOM:
            self.preset = PRESET_CUSTOM
            return
        self.enabled_methods = methods_for_preset(preset)
        # Easy mode uses ALL logic because every cheap method is an exact-equality
        # check — requiring agreement gives correct exact-duplicate semantics.
        # Medium/Robust use ANY so a single perceptual match (pHash, audio, etc.)
        # is sufficient even if a cheap method (e.g. SHA-256) disagrees.
        self.match_logic = MATCH_ALL if preset == PRESET_EASY else MATCH_ANY
        self.preset = preset

    def mark_custom(self) -> None:
        """Flip the preset to ``custom`` (called when user toggles a method manually)."""
        self.preset = PRESET_CUSTOM

    # ---- persistence ----
    def save(self, path: Path | None = None) -> Path:
        path = path or default_config_path()
        data = asdict(self)
        data["enabled_methods"] = sorted(self.enabled_methods)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return path

    @classmethod
    def load(cls, path: Path | None = None) -> "AppConfig":
        path = path or default_config_path()
        if not path.exists():
            return cls()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            LOG.warning("Failed to load config %s: %s — using defaults", path, exc)
            return cls()

        # Normalise: enabled_methods may be a list on disk.
        if isinstance(data.get("enabled_methods"), list):
            data["enabled_methods"] = set(data["enabled_methods"])

        # Drop any unknown keys so renames don't crash future builds.
        valid = {f for f in cls.__dataclass_fields__}
        clean = {k: v for k, v in data.items() if k in valid}
        try:
            return cls(**clean)
        except TypeError as exc:
            LOG.warning("Config schema mismatch (%s) — using defaults", exc)
            return cls()


def methods_for_preset(preset: str) -> Set[str]:
    """Plain-string variant of the per-preset method set (no method imports)."""
    preset = preset.lower()
    easy = {METHOD_SIZE, METHOD_PARTIAL_HASH, METHOD_SHA256, METHOD_METADATA}
    if preset == PRESET_EASY:
        return set(easy)
    if preset == PRESET_MEDIUM:
        return easy | {METHOD_PHASH}
    if preset == PRESET_ROBUST:
        return easy | {METHOD_PHASH, METHOD_SSIM, METHOD_PSNR, METHOD_VMAF, METHOD_AUDIO}
    if preset == PRESET_CUSTOM:
        return easy | {METHOD_PHASH}
    raise ValueError(f"Unknown preset: {preset!r}")


def detect_preset_from_methods(methods: Set[str]) -> str:
    """Reverse-lookup: if ``methods`` matches a named preset exactly, return it."""
    for preset in (PRESET_EASY, PRESET_MEDIUM, PRESET_ROBUST):
        if methods == methods_for_preset(preset):
            return preset
    return PRESET_CUSTOM
