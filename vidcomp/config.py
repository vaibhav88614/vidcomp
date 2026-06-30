"""Application configuration, scan options and mode presets.

``ScanOptions`` describes a single scan (which methods run, thresholds, filters)
and is consumed by the engine.  ``AppConfig`` holds persistent app-wide
settings (delete mode, paths, worker count, ...).  Both serialise to JSON.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .core.models import DeleteMode, KeepRule, MatchLogic, MethodId, ScanMode

# Default supported video extensions (lower-case, with leading dot).
DEFAULT_EXTENSIONS: list[str] = [
    ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".flv", ".webm", ".m4v",
    ".mpg", ".mpeg", ".3gp", ".ts", ".m2ts", ".vob", ".ogv",
]


def default_config_dir() -> Path:
    """Per-user config directory (``%APPDATA%\\VidComp`` on Windows)."""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = Path(base) / "VidComp"
    return d


def default_cache_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return Path(base) / "VidComp" / "cache"


@dataclass
class ScanOptions:
    """Everything the engine needs to perform one scan.

    ``enabled_methods`` is the authoritative set of active comparison methods.
    The Easy/Medium/Robust presets simply pre-populate this set and the
    thresholds; switching to ``CUSTOM`` lets the user override freely.
    """

    mode: ScanMode = ScanMode.EASY
    enabled_methods: set[MethodId] = field(default_factory=set)
    match_logic: MatchLogic = MatchLogic.ANY

    # Thresholds (sensible defaults).
    phash_threshold: int = 8          # max Hamming distance for a pHash match
    frame_samples: int = 9            # frames sampled per video for pHash/SSIM
    ssim_threshold: float = 0.92      # 0..1, higher == more similar
    psnr_threshold: float = 30.0      # dB
    vmaf_threshold: float = 90.0      # 0..100
    audio_threshold: float = 0.85     # 0..1 fingerprint similarity
    partial_hash_bytes: int = 1 << 20  # first+last N bytes for the quick hash

    # Filters.
    extensions: list[str] = field(default_factory=lambda: list(DEFAULT_EXTENSIONS))
    min_size_bytes: int = 0
    min_duration_seconds: float = 0.0

    # Concurrency.
    worker_count: int = max(2, (os.cpu_count() or 4))

    def is_enabled(self, method: MethodId) -> bool:
        return method in self.enabled_methods

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["mode"] = self.mode.value
        d["match_logic"] = self.match_logic.value
        d["enabled_methods"] = sorted(m.value for m in self.enabled_methods)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ScanOptions":
        opts = cls()
        opts.mode = ScanMode(d.get("mode", ScanMode.EASY.value))
        opts.match_logic = MatchLogic(d.get("match_logic", MatchLogic.ANY.value))
        # Tolerate unknown method identifiers in saved configs (e.g. legacy
        # "metadata" entries from before M4 was removed) instead of crashing.
        loaded_methods: set[MethodId] = set()
        for m in d.get("enabled_methods", []):
            try:
                loaded_methods.add(MethodId(m))
            except ValueError:
                continue
        opts.enabled_methods = loaded_methods
        for key in (
            "phash_threshold", "frame_samples", "ssim_threshold", "psnr_threshold",
            "vmaf_threshold", "audio_threshold", "partial_hash_bytes",
            "min_size_bytes", "min_duration_seconds", "worker_count",
        ):
            if key in d and d[key] is not None:
                setattr(opts, key, d[key])
        if d.get("extensions"):
            opts.extensions = list(d["extensions"])
        return opts


# --- Mode -> method mapping (Section 3 of the spec) ------------------------

_EASY_METHODS = {MethodId.SIZE, MethodId.PARTIAL_HASH, MethodId.SHA256}
_MEDIUM_METHODS = _EASY_METHODS | {MethodId.PHASH}
_ROBUST_METHODS = _MEDIUM_METHODS | {
    MethodId.SSIM, MethodId.PSNR, MethodId.VMAF, MethodId.AUDIO,
}

PRESET_METHODS: dict[ScanMode, set[MethodId]] = {
    ScanMode.EASY: set(_EASY_METHODS),
    ScanMode.MEDIUM: set(_MEDIUM_METHODS),
    ScanMode.ROBUST: set(_ROBUST_METHODS),
}


def options_for_mode(mode: ScanMode, base: ScanOptions | None = None) -> ScanOptions:
    """Return a fresh ``ScanOptions`` pre-populated for the given preset.

    Robust mode favours ALL-logic only loosely; per the spec the default
    combination logic stays ANY so any single strong signal can flag a match,
    while the expensive metrics act as confirming evidence.  Users can flip
    this in the Advanced panel.
    """

    opts = ScanOptions() if base is None else base
    opts.mode = mode
    if mode in PRESET_METHODS:
        opts.enabled_methods = set(PRESET_METHODS[mode])
    return opts


@dataclass
class AppConfig:
    """Persistent application settings."""

    last_folder: str = ""
    keep_rule: KeepRule = KeepRule.HIGHEST_RESOLUTION
    delete_mode: DeleteMode = DeleteMode.RECYCLE_BIN
    quarantine_folder: str = str(default_config_dir() / "quarantine")
    cache_dir: str = str(default_cache_dir())
    thumbnail_dir: str = str(default_cache_dir() / "thumbnails")
    thumbnail_cache_mb: int = 512
    worker_count: int = max(2, (os.cpu_count() or 4))
    dark_mode: bool = True
    scan_options: ScanOptions = field(default_factory=ScanOptions)

    # --- persistence -------------------------------------------------------
    @staticmethod
    def config_path() -> Path:
        return default_config_dir() / "config.json"

    def to_dict(self) -> dict[str, Any]:
        return {
            "last_folder": self.last_folder,
            "keep_rule": self.keep_rule.value,
            "delete_mode": self.delete_mode.value,
            "quarantine_folder": self.quarantine_folder,
            "cache_dir": self.cache_dir,
            "thumbnail_dir": self.thumbnail_dir,
            "thumbnail_cache_mb": self.thumbnail_cache_mb,
            "worker_count": self.worker_count,
            "dark_mode": self.dark_mode,
            "scan_options": self.scan_options.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        cfg.last_folder = d.get("last_folder", "")
        if d.get("keep_rule"):
            cfg.keep_rule = KeepRule(d["keep_rule"])
        if d.get("delete_mode"):
            cfg.delete_mode = DeleteMode(d["delete_mode"])
        cfg.quarantine_folder = d.get("quarantine_folder", cfg.quarantine_folder)
        cfg.cache_dir = d.get("cache_dir", cfg.cache_dir)
        cfg.thumbnail_dir = d.get("thumbnail_dir", cfg.thumbnail_dir)
        cfg.thumbnail_cache_mb = d.get("thumbnail_cache_mb", cfg.thumbnail_cache_mb)
        cfg.worker_count = d.get("worker_count", cfg.worker_count)
        cfg.dark_mode = d.get("dark_mode", cfg.dark_mode)
        if d.get("scan_options"):
            cfg.scan_options = ScanOptions.from_dict(d["scan_options"])
        return cfg

    @classmethod
    def load(cls) -> "AppConfig":
        """Load config from disk, falling back to defaults on any error."""
        p = cls.config_path()
        try:
            if p.is_file():
                with open(p, "r", encoding="utf-8") as fh:
                    return cls.from_dict(json.load(fh))
        except Exception:
            pass
        cfg = cls()
        # Ensure the Easy preset is populated on first run.
        cfg.scan_options = options_for_mode(ScanMode.EASY)
        return cfg

    def save(self) -> None:
        p = self.config_path()
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, indent=2)
        except Exception:
            # Settings persistence is best-effort; never crash the app.
            pass
