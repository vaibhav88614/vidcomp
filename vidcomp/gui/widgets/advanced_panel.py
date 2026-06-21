"""Collapsible Advanced panel: per-method toggles and threshold sliders."""

from __future__ import annotations

from typing import Dict, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ...config import (
    AppConfig,
    DEFAULT_EXTENSIONS,
    MATCH_ALL,
    MATCH_ANY,
    METHOD_AUDIO,
    METHOD_METADATA,
    METHOD_PARTIAL_HASH,
    METHOD_PHASH,
    METHOD_PSNR,
    METHOD_SHA256,
    METHOD_SIZE,
    METHOD_SSIM,
    METHOD_VMAF,
    detect_preset_from_methods,
)
from ..widgets._helpers import h_separator


_METHOD_LABELS: Dict[str, str] = {
    METHOD_SIZE: "M1 — File size",
    METHOD_PARTIAL_HASH: "M3 — Partial hash (head + tail)",
    METHOD_SHA256: "M2 — SHA-256 (full hash)",
    METHOD_METADATA: "M4 — ffprobe metadata",
    METHOD_PHASH: "M5 — Perceptual hash (pHash)",
    METHOD_SSIM: "M6 — SSIM",
    METHOD_PSNR: "M7 — PSNR",
    METHOD_VMAF: "M8 — VMAF",
    METHOD_AUDIO: "M9 — Audio fingerprint (Chromaprint)",
}

_METHOD_TIPS: Dict[str, str] = {
    METHOD_SIZE: "Instant pre-filter that groups files by exact byte size.",
    METHOD_PARTIAL_HASH: "Quick hash of the first and last N bytes + size.",
    METHOD_SHA256: "Full SHA-256 hash — proves identical bytes.",
    METHOD_METADATA: "Compares duration, resolution, codec, fps, audio channels.",
    METHOD_PHASH: "Per-frame perceptual hash; tolerates re-encode and resize.",
    METHOD_SSIM: "Pair-wise SSIM via ffmpeg `ssim` filter.",
    METHOD_PSNR: "Pair-wise PSNR via ffmpeg `psnr` filter.",
    METHOD_VMAF: "Pair-wise VMAF via ffmpeg `libvmaf` (requires libvmaf build).",
    METHOD_AUDIO: "Chromaprint audio fingerprint via fpcalc.",
}


class AdvancedPanel(QWidget):
    """Per-method toggles + tunable thresholds.

    Editing a toggle marks the config as ``custom`` and emits ``modified``.
    The :class:`MainWindow` uses ``modified`` to keep the top-bar mode label
    in sync ("Active preset: …").
    """

    modified = Signal()

    def __init__(self, config: AppConfig, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._config = config
        self._suppress_signals = False
        self._build()
        self.refresh_from_config()

    # ------------------------------------------------------------------
    @property
    def config(self) -> AppConfig:
        return self._config

    # ------------------------------------------------------------------
    def _build(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 4, 8, 8)
        outer.setSpacing(6)

        # ---- Methods group
        methods_group = QGroupBox("Comparison methods")
        methods_layout = QGridLayout()
        methods_layout.setVerticalSpacing(4)
        methods_layout.setHorizontalSpacing(12)
        self._method_checks: Dict[str, QCheckBox] = {}
        order = [
            METHOD_SIZE,
            METHOD_PARTIAL_HASH,
            METHOD_SHA256,
            METHOD_METADATA,
            METHOD_PHASH,
            METHOD_AUDIO,
            METHOD_SSIM,
            METHOD_PSNR,
            METHOD_VMAF,
        ]
        for i, mid in enumerate(order):
            cb = QCheckBox(_METHOD_LABELS[mid])
            cb.setToolTip(_METHOD_TIPS[mid])
            cb.toggled.connect(self._on_method_toggled)
            row, col = divmod(i, 3)
            methods_layout.addWidget(cb, row, col)
            self._method_checks[mid] = cb
        methods_group.setLayout(methods_layout)
        outer.addWidget(methods_group)

        # ---- Match logic row
        logic_row = QHBoxLayout()
        logic_row.addWidget(QLabel("Match logic:"))
        self.match_combo = QComboBox()
        self.match_combo.addItem("ANY enabled method agrees (default, more matches)", MATCH_ANY)
        self.match_combo.addItem("ALL enabled methods must agree (stricter, fewer matches)", MATCH_ALL)
        self.match_combo.currentIndexChanged.connect(self._on_changed)
        logic_row.addWidget(self.match_combo, 1)
        outer.addLayout(logic_row)

        # ---- Thresholds group
        th_group = QGroupBox("Thresholds & parameters")
        th_form = QFormLayout()
        th_form.setLabelAlignment(Qt.AlignRight)

        self.phash_frames = QSpinBox()
        self.phash_frames.setRange(1, 64)
        self.phash_frames.setValue(self._config.phash_frames)
        self.phash_frames.setToolTip("Number of frames sampled per video for pHash.")
        self.phash_frames.valueChanged.connect(self._on_changed)
        th_form.addRow("pHash frames per video:", self.phash_frames)

        self.phash_threshold = QSpinBox()
        self.phash_threshold.setRange(0, 64)
        self.phash_threshold.setValue(self._config.phash_threshold)
        self.phash_threshold.setToolTip(
            "Max mean Hamming distance between two videos' frame hashes (0..64)."
        )
        self.phash_threshold.valueChanged.connect(self._on_changed)
        th_form.addRow("pHash Hamming threshold:", self.phash_threshold)

        self.ssim_threshold = QDoubleSpinBox()
        self.ssim_threshold.setRange(0.0, 1.0)
        self.ssim_threshold.setSingleStep(0.01)
        self.ssim_threshold.setDecimals(3)
        self.ssim_threshold.setValue(self._config.ssim_threshold)
        self.ssim_threshold.valueChanged.connect(self._on_changed)
        th_form.addRow("SSIM threshold (≥):", self.ssim_threshold)

        self.psnr_threshold = QDoubleSpinBox()
        self.psnr_threshold.setRange(0.0, 200.0)
        self.psnr_threshold.setSingleStep(0.5)
        self.psnr_threshold.setDecimals(1)
        self.psnr_threshold.setValue(self._config.psnr_threshold)
        self.psnr_threshold.valueChanged.connect(self._on_changed)
        th_form.addRow("PSNR threshold (dB, ≥):", self.psnr_threshold)

        self.vmaf_threshold = QDoubleSpinBox()
        self.vmaf_threshold.setRange(0.0, 100.0)
        self.vmaf_threshold.setSingleStep(0.5)
        self.vmaf_threshold.setDecimals(1)
        self.vmaf_threshold.setValue(self._config.vmaf_threshold)
        self.vmaf_threshold.valueChanged.connect(self._on_changed)
        th_form.addRow("VMAF threshold (≥):", self.vmaf_threshold)

        self.audio_threshold = QDoubleSpinBox()
        self.audio_threshold.setRange(0.0, 1.0)
        self.audio_threshold.setSingleStep(0.01)
        self.audio_threshold.setDecimals(2)
        self.audio_threshold.setValue(self._config.audio_threshold)
        self.audio_threshold.valueChanged.connect(self._on_changed)
        th_form.addRow("Audio similarity (≥):", self.audio_threshold)

        self.min_size_mb = QDoubleSpinBox()
        self.min_size_mb.setRange(0.0, 100_000.0)
        self.min_size_mb.setSingleStep(1.0)
        self.min_size_mb.setDecimals(2)
        self.min_size_mb.setValue(self._config.min_file_size_bytes / (1024 * 1024))
        self.min_size_mb.setSuffix(" MB")
        self.min_size_mb.valueChanged.connect(self._on_changed)
        th_form.addRow("Min file size:", self.min_size_mb)

        self.min_duration = QDoubleSpinBox()
        self.min_duration.setRange(0.0, 1e6)
        self.min_duration.setSingleStep(1.0)
        self.min_duration.setDecimals(1)
        self.min_duration.setValue(self._config.min_duration_sec)
        self.min_duration.setSuffix(" s")
        self.min_duration.valueChanged.connect(self._on_changed)
        th_form.addRow("Min duration:", self.min_duration)

        self.partial_hash_bytes = QSpinBox()
        self.partial_hash_bytes.setRange(4, 65536)
        self.partial_hash_bytes.setValue(self._config.partial_hash_bytes // 1024)
        self.partial_hash_bytes.setSuffix(" KiB")
        self.partial_hash_bytes.valueChanged.connect(self._on_changed)
        th_form.addRow("Partial hash window:", self.partial_hash_bytes)

        th_group.setLayout(th_form)
        outer.addWidget(th_group)

        # ---- Extensions row
        ext_row = QHBoxLayout()
        ext_row.addWidget(QLabel("Extensions (comma-separated):"))
        self.extensions_edit = QLineEdit()
        self.extensions_edit.setPlaceholderText(", ".join(DEFAULT_EXTENSIONS))
        self.extensions_edit.editingFinished.connect(self._on_changed)
        ext_row.addWidget(self.extensions_edit, 1)
        outer.addLayout(ext_row)

    # ------------------------------------------------------------------
    def refresh_from_config(self) -> None:
        """Re-populate the widgets from the bound :class:`AppConfig`."""
        self._suppress_signals = True
        try:
            for mid, cb in self._method_checks.items():
                cb.setChecked(mid in self._config.enabled_methods)
            self.match_combo.setCurrentIndex(
                0 if self._config.match_logic == MATCH_ANY else 1
            )
            self.phash_frames.setValue(self._config.phash_frames)
            self.phash_threshold.setValue(self._config.phash_threshold)
            self.ssim_threshold.setValue(self._config.ssim_threshold)
            self.psnr_threshold.setValue(self._config.psnr_threshold)
            self.vmaf_threshold.setValue(self._config.vmaf_threshold)
            self.audio_threshold.setValue(self._config.audio_threshold)
            self.min_size_mb.setValue(self._config.min_file_size_bytes / (1024 * 1024))
            self.min_duration.setValue(self._config.min_duration_sec)
            self.partial_hash_bytes.setValue(self._config.partial_hash_bytes // 1024)
            self.extensions_edit.setText(", ".join(self._config.extensions))
        finally:
            self._suppress_signals = False

    def set_vmaf_available(self, available: bool) -> None:
        """Disable the VMAF checkbox and add an explanatory tooltip when missing."""
        cb = self._method_checks.get(METHOD_VMAF)
        if cb is None:
            return
        cb.setEnabled(available)
        if not available:
            cb.setChecked(False)
            cb.setToolTip(
                _METHOD_TIPS[METHOD_VMAF]
                + "\n\nDisabled: your ffmpeg build does not include libvmaf."
            )
        else:
            cb.setToolTip(_METHOD_TIPS[METHOD_VMAF])

    def set_audio_available(self, available: bool) -> None:
        cb = self._method_checks.get(METHOD_AUDIO)
        if cb is None:
            return
        cb.setEnabled(available)
        if not available:
            cb.setChecked(False)
            cb.setToolTip(
                _METHOD_TIPS[METHOD_AUDIO]
                + "\n\nDisabled: fpcalc (Chromaprint) is not on PATH."
            )
        else:
            cb.setToolTip(_METHOD_TIPS[METHOD_AUDIO])

    # ------------------------------------------------------------------
    def _on_method_toggled(self, _checked: bool) -> None:
        if self._suppress_signals:
            return
        self._commit_methods_to_config()
        self._on_changed()

    def _on_changed(self) -> None:
        if self._suppress_signals:
            return
        self._commit_all_to_config()
        self._config.preset = detect_preset_from_methods(self._config.enabled_methods)
        self.modified.emit()

    def _commit_methods_to_config(self) -> None:
        self._config.enabled_methods = {
            mid for mid, cb in self._method_checks.items() if cb.isChecked()
        }

    def _commit_all_to_config(self) -> None:
        self._commit_methods_to_config()
        self._config.match_logic = (
            MATCH_ANY if self.match_combo.currentIndex() == 0 else MATCH_ALL
        )
        self._config.phash_frames = int(self.phash_frames.value())
        self._config.phash_threshold = int(self.phash_threshold.value())
        self._config.ssim_threshold = float(self.ssim_threshold.value())
        self._config.psnr_threshold = float(self.psnr_threshold.value())
        self._config.vmaf_threshold = float(self.vmaf_threshold.value())
        self._config.audio_threshold = float(self.audio_threshold.value())
        self._config.min_file_size_bytes = int(self.min_size_mb.value() * 1024 * 1024)
        self._config.min_duration_sec = float(self.min_duration.value())
        self._config.partial_hash_bytes = int(self.partial_hash_bytes.value()) * 1024
        text = self.extensions_edit.text().strip()
        if text:
            exts = [e.strip().lstrip(".").lower() for e in text.split(",") if e.strip()]
            if exts:
                self._config.extensions = exts
