"""Dialog shown when required external tools are missing on PATH."""

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

from ...core.models import ToolsStatus


_FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/"
_CHROMAPRINT_URL = "https://acoustid.org/chromaprint"


class MissingToolsDialog(QDialog):
    """Friendly dialog explaining which tools are missing and how to install them."""

    def __init__(self, status: ToolsStatus, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Missing external tools")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)

        required_ok = status.required_ok
        if required_ok:
            heading = QLabel(
                "<b>VidComp can run, but some optional features will be disabled.</b>"
            )
        else:
            heading = QLabel(
                "<b style='color:#c62828'>VidComp cannot scan videos without "
                "ffmpeg + ffprobe.</b>"
            )
        heading.setWordWrap(True)
        layout.addWidget(heading)

        body_lines = []
        if not status.ffmpeg.available:
            body_lines.append(
                f"&bull; <b>ffmpeg</b> — not found.<br>"
                f"&nbsp;&nbsp;Install from <a href='{_FFMPEG_URL}'>{_FFMPEG_URL}</a> "
                "and add the <code>bin</code> folder to your PATH."
            )
        if not status.ffprobe.available:
            body_lines.append(
                "&bull; <b>ffprobe</b> — not found (shipped with ffmpeg above)."
            )
        if not status.fpcalc.available:
            body_lines.append(
                f"&bull; <b>fpcalc</b> (Chromaprint) — not found.<br>"
                f"&nbsp;&nbsp;Audio-fingerprint matching (M9) will be disabled. "
                f"Install from <a href='{_CHROMAPRINT_URL}'>{_CHROMAPRINT_URL}</a> "
                "and add it to your PATH."
            )
        if not status.libvmaf:
            body_lines.append(
                "&bull; <b>libvmaf</b> — not present in your ffmpeg build.<br>"
                "&nbsp;&nbsp;VMAF (M8) will be disabled.  "
                "Use a full ffmpeg build (e.g. gyan.dev 'full') to enable it."
            )

        body = QLabel("<br><br>".join(body_lines) or "All tools found.")
        body.setWordWrap(True)
        body.setOpenExternalLinks(True)
        body.setTextInteractionFlags(Qt.TextBrowserInteraction)
        layout.addWidget(body)

        layout.addStretch(1)

        if required_ok:
            btns = QDialogButtonBox(QDialogButtonBox.Ok)
            btns.button(QDialogButtonBox.Ok).setText("Continue")
            btns.accepted.connect(self.accept)
        else:
            btns = QDialogButtonBox(QDialogButtonBox.Close)
            btns.rejected.connect(self.reject)
            btns.accepted.connect(self.reject)
            btns.button(QDialogButtonBox.Close).setText("Quit")
            btns.button(QDialogButtonBox.Close).clicked.connect(self.reject)
        layout.addWidget(btns)
