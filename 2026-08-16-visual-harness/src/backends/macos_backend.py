'''"""macOS backend implementation for visual‑harness.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from src.plugins import register_plugin
from src.core.models import AutomationError, CaptureFrame, Session


@register_plugin("macos")
class MacOSBackend:
    """Simple macOS backend placeholder.

    The real backend would use ``pyobjc`` to synthesize mouse events.  For the
    test environment we only need to provide ``capture`` and ``click`` methods
    that behave predictably.
    """

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    def capture(self) -> CaptureFrame:
        """Return a dummy capture frame.

        The test suite supplies its own image files, so we create a placeholder
        file that exists alongside the source.
        """
        dummy_path = Path(__file__).with_name("dummy.png")
        dummy_path.touch(exist_ok=True)
        return CaptureFrame(image_path=dummy_path)

    def click(self, x: int, y: int) -> None:
        """Log a click – a real implementation would use ``Quartz`` APIs.
        """
        self.logger.info("Click at (%d, %d) on macOS", x, y)
'''