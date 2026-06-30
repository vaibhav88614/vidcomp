"""Advanced (power-user) panel: per-method toggles and tunable thresholds."""

from __future__ import annotations

from typing import Dict

from PySide6.QtCore import Signal
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
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtCore import Qt

from ...config import ScanOptions
from ...core.models import METHOD_LABELS, MatchLogic, MethodId


class AdvancedPanel(QWidget):
    """Collapsible content exposing every method M1-M9 plus thresholds.

    Emits :attr:`changed` whenever the user edits a control so the main window
    can flag the active preset as "Custom".
    """

    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._method_boxes: Dict[MethodId, QCheckBox] = {}
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        # --- method toggles ---
        methods_box = QGroupBox("Comparison methods (M1-M9)")
        grid = QGridLayout(methods_box)
        for i, mid in enumerate(MethodId):
            cb = QCheckBox(METHOD_LABELS[mid])
            cb.toggled.connect(self._on_changed)
            self._method_boxes[mid] = cb
            grid.addWidget(cb, i // 3, i % 3)
        root.addWidget(methods_box)

        # --- thresholds ---
        thr_box = QGroupBox("Thresholds & sampling")
        form = QFormLayout(thr_box)

        self.phash_slider = QSlider(Qt.Horizontal)
        self.phash_slider.setRange(0, 32)
        self.phash_label = QLabel("8")
        self.phash_slider.valueChanged.connect(lambda v: self.phash_label.setText(str(v)))
        self.phash_slider.valueChanged.connect(self._on_changed)
        ph_row = QHBoxLayout()
        ph_row.addWidget(self.phash_slider)
        ph_row.addWidget(self.phash_label)
        form.addRow("pHash max Hamming distance:", _wrap(ph_row))

        self.frames_spin = QSpinBox()
        self.frames_spin.setRange(1, 60)
        self.frames_spin.valueChanged.connect(self._on_changed)
        form.addRow("Frames sampled per video:", self.frames_spin)

        self.ssim_spin = QDoubleSpinBox()
        self.ssim_spin.setRange(0.0, 1.0)
        self.ssim_spin.setSingleStep(0.01)
        self.ssim_spin.setDecimals(3)
        self.ssim_spin.valueChanged.connect(self._on_changed)
        form.addRow("SSIM threshold (0-1):", self.ssim_spin)

        self.psnr_spin = QDoubleSpinBox()
        self.psnr_spin.setRange(0.0, 100.0)
        self.psnr_spin.setSingleStep(1.0)
        self.psnr_spin.valueChanged.connect(self._on_changed)
        form.addRow("PSNR threshold (dB):", self.psnr_spin)

        self.vmaf_spin = QDoubleSpinBox()
        self.vmaf_spin.setRange(0.0, 100.0)
        self.vmaf_spin.setSingleStep(1.0)
        self.vmaf_spin.valueChanged.connect(self._on_changed)
        form.addRow("VMAF threshold (0-100):", self.vmaf_spin)

        self.audio_spin = QDoubleSpinBox()
        self.audio_spin.setRange(0.0, 1.0)
        self.audio_spin.setSingleStep(0.01)
        self.audio_spin.setDecimals(2)
        self.audio_spin.valueChanged.connect(self._on_changed)
        form.addRow("Audio similarity threshold (0-1):", self.audio_spin)

        root.addWidget(thr_box)

        # --- logic & filters ---
        filt_box = QGroupBox("Match logic & filters")
        fform = QFormLayout(filt_box)

        self.logic_combo = QComboBox()
        self.logic_combo.addItem("ANY enabled method agrees", MatchLogic.ANY.value)
        self.logic_combo.addItem("ALL enabled methods agree", MatchLogic.ALL.value)
        self.logic_combo.currentIndexChanged.connect(self._on_changed)
        fform.addRow("Combination logic:", self.logic_combo)

        self.ext_edit = QLineEdit()
        self.ext_edit.setPlaceholderText(".mp4 .mkv .avi ...")
        self.ext_edit.editingFinished.connect(self._on_changed)
        fform.addRow("Extensions:", self.ext_edit)

        self.min_size_spin = QDoubleSpinBox()
        self.min_size_spin.setRange(0.0, 1_000_000.0)
        self.min_size_spin.setSuffix(" MB")
        self.min_size_spin.valueChanged.connect(self._on_changed)
        fform.addRow("Min file size:", self.min_size_spin)

        self.min_dur_spin = QDoubleSpinBox()
        self.min_dur_spin.setRange(0.0, 100000.0)
        self.min_dur_spin.setSuffix(" s")
        self.min_dur_spin.valueChanged.connect(self._on_changed)
        fform.addRow("Min duration:", self.min_dur_spin)

        root.addWidget(filt_box)
        root.addStretch(1)

    # --- preset / vmaf availability ---------------------------------------
    def set_vmaf_available(self, available: bool) -> None:
        cb = self._method_boxes[MethodId.VMAF]
        cb.setEnabled(available)
        if not available:
            cb.setToolTip("VMAF requires an ffmpeg build with libvmaf.")

    def set_audio_available(self, available: bool) -> None:
        cb = self._method_boxes[MethodId.AUDIO]
        cb.setEnabled(available)
        if not available:
            cb.setToolTip("Audio fingerprinting requires fpcalc (Chromaprint).")

    # --- load / apply ------------------------------------------------------
    def load_options(self, opts: ScanOptions) -> None:
        """Populate controls from ``opts`` without emitting :attr:`changed`."""
        self._loading = True
        try:
            for mid, cb in self._method_boxes.items():
                cb.setChecked(mid in opts.enabled_methods)
            self.phash_slider.setValue(int(opts.phash_threshold))
            self.frames_spin.setValue(int(opts.frame_samples))
            self.ssim_spin.setValue(float(opts.ssim_threshold))
            self.psnr_spin.setValue(float(opts.psnr_threshold))
            self.vmaf_spin.setValue(float(opts.vmaf_threshold))
            self.audio_spin.setValue(float(opts.audio_threshold))
            idx = self.logic_combo.findData(opts.match_logic.value)
            self.logic_combo.setCurrentIndex(max(0, idx))
            self.ext_edit.setText(" ".join(opts.extensions))
            self.min_size_spin.setValue(opts.min_size_bytes / (1024 * 1024))
            self.min_dur_spin.setValue(float(opts.min_duration_seconds))
        finally:
            self._loading = False

    def apply_to(self, opts: ScanOptions) -> None:
        """Write current control values back into ``opts``."""
        opts.enabled_methods = {
            mid for mid, cb in self._method_boxes.items() if cb.isChecked()
        }
        opts.phash_threshold = self.phash_slider.value()
        opts.frame_samples = self.frames_spin.value()
        opts.ssim_threshold = self.ssim_spin.value()
        opts.psnr_threshold = self.psnr_spin.value()
        opts.vmaf_threshold = self.vmaf_spin.value()
        opts.audio_threshold = self.audio_spin.value()
        opts.match_logic = MatchLogic(self.logic_combo.currentData())
        exts = [t.strip() for t in self.ext_edit.text().replace(",", " ").split() if t.strip()]
        opts.extensions = [("." + e.lstrip(".").lower()) for e in exts] or opts.extensions
        opts.min_size_bytes = int(self.min_size_spin.value() * 1024 * 1024)
        opts.min_duration_seconds = float(self.min_dur_spin.value())

    def _on_changed(self, *args: object) -> None:
        if not self._loading:
            self.changed.emit()


def _wrap(layout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    layout.setContentsMargins(0, 0, 0, 0)
    return w
