'''"""Engine implementation for visual‑harness.
"""

from __future__ import annotations

import logging
from typing import List

from src.core.models import (
    AutomationCommand,
    AutomationError,
    CaptureFrame,
    Session,
    UIElement,
)
from src.backends.macos_backend import MacOSBackend
from src.backends.windows_backend import WindowsBackend
from src.ocr.vision_ocr import VisionOCR


class Engine:
    """Orchestrates capture, OCR, and backend actions.

    The engine is deliberately lightweight – it supports only the ``click``
    action required by the test suite.  Additional actions can be added later
    without breaking the existing public API.
    """

    def __init__(self, backend_name: str, session: Session):
        self.logger = logging.getLogger(__name__)
        if backend_name == "windows":
            self.backend = WindowsBackend(session)
        elif backend_name == "macos":
            self.backend = MacOSBackend(session)
        else:
            raise AutomationError(f"Unsupported backend: {backend_name}")
        self.ocr = VisionOCR(session)

    def run(self, commands: List[AutomationCommand]) -> List[AutomationCommand]:
        """Execute a list of :class:`AutomationCommand` objects.

        Currently only the ``click`` action is supported.  For each command we
        capture the current screen, run OCR, locate the target element by its
        ``text`` attribute, and ask the backend to click the centre of the
        element's bounding box.
        """
        for cmd in commands:
            self.logger.debug("Executing command %s", cmd)
            if cmd.action != "click":
                raise AutomationError(f"Unsupported action: {cmd.action}")

            # Capture the screen and run OCR
            frame: CaptureFrame = self.backend.capture()
            elements: List[UIElement] = self.ocr.ocr(frame)

            # Find the element whose text matches the command's target
            target = next((e for e in elements if e.text == cmd.target), None)
            if not target:
                raise AutomationError(f"Element with text '{cmd.target}' not found")

            x, y, w, h = target.bounds
            cx = x + w // 2
            cy = y + h // 2
            self.backend.click(cx, cy)
        return commands
'''