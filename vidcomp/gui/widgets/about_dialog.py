"""About dialog."""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from ... import __version__


_ABOUT = f"""
<h2>VidComp {__version__}</h2>
<p>A GUI video duplicate / similarity comparer for Windows.</p>
<p>Built with PySide6, OpenCV, NumPy, Pillow, ffmpeg/ffprobe and Chromaprint.</p>
<p style='color:#888888'>Perceptual hashing (M5) is built in using OpenCV + NumPy &mdash;
no separate <code>phash</code> or <code>imagehash</code> package is required.</p>
<p style='color:#888888'>This program is provided as-is without warranty.</p>
"""


class AboutDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About VidComp")
        layout = QVBoxLayout(self)
        label = QLabel(_ABOUT)
        label.setTextFormat(Qt.RichText)
        label.setWordWrap(True)
        layout.addWidget(label)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.accepted.connect(self.accept)
        btns.button(QDialogButtonBox.Close).clicked.connect(self.accept)
        layout.addWidget(btns)
