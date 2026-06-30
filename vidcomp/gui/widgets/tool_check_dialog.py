"""Startup dialog reporting external-tool availability with setup guidance."""

from __future__ import annotations

from typing import List

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ...core.media import ToolStatus

_INSTRUCTIONS = """
<h3>External tools</h3>
<p>VidComp uses three command-line tools. Install any that are missing and make
sure they are on your <b>PATH</b>, then restart VidComp.</p>
<ul>
  <li><b>ffmpeg</b> &amp; <b>ffprobe</b> - metadata, frame extraction, SSIM/PSNR/VMAF.<br>
      Download a Windows build from
      <a href="https://www.gyan.dev/ffmpeg/builds/">gyan.dev</a> or
      <a href="https://github.com/BtbN/FFmpeg-Builds/releases">BtbN</a>,
      unzip it, and add its <code>bin</code> folder to PATH.
      For VMAF support pick a build that includes <code>libvmaf</code>.</li>
  <li><b>fpcalc</b> (Chromaprint) - audio fingerprinting.<br>
      Download from
      <a href="https://acoustid.org/chromaprint">acoustid.org/chromaprint</a>,
      unzip, and add the folder to PATH.</li>
</ul>
<p>Easy mode works with just ffmpeg/ffprobe. Audio (M9) needs fpcalc and VMAF
(M8) needs an ffmpeg build with libvmaf; both degrade gracefully if absent.</p>
"""


class ToolCheckDialog(QDialog):
    """Shows which tools were found and how to install the rest."""

    def __init__(self, statuses: List[ToolStatus], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("VidComp - External Tools")
        self.setMinimumSize(620, 480)
        layout = QVBoxLayout(self)

        summary_lines = []
        for st in statuses:
            mark = "OK" if st.available else "MISSING"
            extra = ""
            if st.name == "ffmpeg" and st.available:
                extra = "  (libvmaf: yes)" if st.has_vmaf else "  (libvmaf: no)"
            loc = f"  -  {st.path}" if st.path else ""
            summary_lines.append(f"[{mark}] {st.name}{extra}{loc}")
        summary = QLabel("\n".join(summary_lines))
        summary.setStyleSheet("font-family:Consolas,monospace;")
        summary.setTextInteractionFlags(summary.textInteractionFlags())
        layout.addWidget(summary)

        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setHtml(_INSTRUCTIONS)
        layout.addWidget(browser, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
