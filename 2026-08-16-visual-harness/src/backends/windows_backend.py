'''"""Windows backend implementation for visual‑harness.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List, Tuple

from src.plugins import register_plugin
from src.core.models import AutomationError, CaptureFrame, Session


@register_plugin("windows")
class WindowsBackend:
    """Simple Windows backend that pretends to click at coordinates.

    The real implementation would use the ``pywin32`` APIs; for the purpose of
    the test suite we provide a lightweight stub that logs actions.
    """

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    def capture(self) -> CaptureFrame:
        """Return a dummy capture frame.

        The test suite creates its own image files, so we simply point to a
        placeholder file that exists in the repository directory.
        """
        dummy_path = Path(__file__).with_name("dummy.png")
        dummy_path.touch(exist_ok=True)
        return CaptureFrame(image_path=dummy_path)

    def click(self, x: int, y: int) -> None:
        """Log a click – a real implementation would invoke ``win32api``.
        """
        self.logger.info("Click at (%d, %d) on Windows", x, y)
'''