'''"""Vision OCR provider using ``pytesseract``.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import List

import pytesseract
from PIL import Image

from src.core.models import AutomationError, CaptureFrame, UIElement, Session
from src.plugins import register_plugin, discover_config


@register_plugin("vision")
class VisionOCR:
    """OCR provider that extracts text using ``pytesseract``.

    The provider returns a list of :class:`UIElement` objects, each containing
    the recognised text and its bounding box.
    """

    def __init__(self, session: Session):
        self.session = session
        self.logger = logging.getLogger(__name__)

    def ocr(self, frame: CaptureFrame) -> List[UIElement]:
        """Run OCR on ``frame`` and return discovered UI elements.

        Parameters
        ----------
        frame: CaptureFrame
            The captured image to analyse.
        """
        try:
            image = Image.open(frame.image_path)
        except Exception as exc:
            raise AutomationError(f"Failed to open image {frame.image_path}: {exc}") from exc

        data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
        elements: List[UIElement] = []
        for i, text in enumerate(data.get("text", [])):
            txt = text.strip()
            if not txt:
                continue
            x = data["left"][i]
            y = data["top"][i]
            w = data["width"][i]
            h = data["height"][i]
            identifier = f"{txt}_{i}"
            elements.append(UIElement(identifier=identifier, bounds=(x, y, w, h), text=txt))
        return elements
'''