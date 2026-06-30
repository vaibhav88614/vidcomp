"""VidComp - a GUI video duplicate / similarity finder.

The package is split into an engine (``vidcomp.core``) that is completely
independent of any GUI, and a PySide6 front-end (``vidcomp.gui``).  All heavy
work is performed in worker threads (``vidcomp.workers``) so the UI never
freezes.
"""

from __future__ import annotations

__version__ = "1.0.0"
__app_name__ = "VidComp"

__all__ = ["__version__", "__app_name__"]
