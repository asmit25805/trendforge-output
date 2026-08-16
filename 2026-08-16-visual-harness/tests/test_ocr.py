import json
import logging
import time
from io import BytesIO
from pathlib import Path
from typing import List

import pytest
from PIL import Image, ImageDraw, ImageFont

from src.core.models import AutomationError, CaptureFrame, Session, UIElement
from src.ocr.vision_ocr import VisionOCR


def _create_image_with_text(text: str, size: tuple[int, int] = (200, 60)) -> bytes:
    """Create a PNG image containing *text* and return its raw bytes."""
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    # Use a basic font; fallback to default if truetype not available
    try:
        font = ImageFont.truetype("DejaVuSans-Bold.ttf", 24)
    except OSError:
        font = ImageFont.load_default()
    w, h = draw.textsize(text, font=font)
    draw.text(((size[0] - w) / 2, (size[1] - h) / 2), text, fill="black", font=font)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def session(tmp_path: Path) -> Session:
    """Create a deterministic Session for the tests."""
    s = Session.load_from_env()
    s.debug_dir = str(tmp_path)
    s.window_id = "dummy"
    s.backend_name = "mock"
    s.ocr_provider_name = "vision"
    return s


@pytest.fixture
def vision_ocr(session: Session) -> VisionOCR:
    """Instantiate VisionOCR with a clean logger."""
    # Ensure a fresh logger for each test to avoid duplicate handlers
    logger = logging.getLogger("visual_harness.ocr.vision")
    for h in list(logger.handlers):
        logger.removeHandler(h)
    return VisionOCR(session)


def _mock_ocr_data(texts: List[dict]) -> List[dict]:
    """Helper to build a structure compatible with pytesseract.image_to_data."""
    # pytesseract returns a dict with keys: level, page_num, block_num, par_num,
    # line_num, word_num, left, top, width, height, conf, text
    # We'll return a list of dicts for each word.
    return texts


def test_recognize_returns_ui_elements_above_threshold(
    vision_ocr: VisionOCR, tmp_path: Path
) -> None:
    """OCR should return UIElements whose confidence meets the default threshold."""
    img_bytes = _create_image_with_text("ClickMe")
    frame = CaptureFrame(image=img_bytes, timestamp=time.time(), window_id="win")
    # Mock pytesseract to return a single high‑confidence word
    def fake_image_to_data(image, lang, config=""):
        return _mock_ocr_data(
            [
                {
                    "level": 5,
                    "page_num": 1,
                    "block_num": 1,
                    "par_num": 1,
                    "line_num": 1,
                    "word_num": 1,
                    "left": 10,
                    "top": 20,
                    "width": 80,
                    "height": 30,
                    "conf": "95",
                    "text": "ClickMe",
                }
            ]
        )

    vision_ocr._ocr_via_tesseract = lambda img: [
        UIElement(
            label=item["text"],
            bbox=(item["left"], item["top"], item["width"], item["height"]),
            confidence=float(item["conf"]) / 100,
            type="button",
        )
        for item in fake_image_to_data(None, None)
    ]

    elements = vision_ocr.recognize(frame)
    assert len(elements) == 1
    el = elements[0]
    assert isinstance(el, UIElement)
    assert el.label == "ClickMe"
    assert el.confidence >= vision_ocr.confidence_threshold


def test_recognize_filters_by_confidence_threshold(
    vision_ocr: VisionOCR, tmp_path: Path
) -> None:
    """Elements below the configured confidence threshold must be filtered out."""
    img_bytes = _create_image_with_text("LowConf")
    frame = CaptureFrame(image=img_bytes, timestamp=time.time(), window_id="win")
    # Force a low confidence value
    vision_ocr.confidence_threshold = 0.9

    def fake_image_to_data(image, lang, config=""):
        return _mock_ocr_data(
            [
                {
                    "level": 5,
                    "page_num": 1,
                    "block_num": 1,
                    "par_num": 1,
                    "line_num": 1,
                    "word_num": 1,
                    "left": 5,
                    "top": 5,
                    "width": 50,
                    "height": 20,
                    "conf": "60",
                    "text": "LowConf",
                }
            ]
        )

    vision_ocr._ocr_via_tesseract = lambda img: [
        UIElement(
            label=item["text"],
            bbox=(item["left"], item["top"], item["width"], item["height"]),
            confidence=float(item["conf"]) / 100,
            type="button",
        )
        for item in fake_image_to_data(None, None)
    ]

    elements = vision_ocr.recognize(frame)
    assert elements == []


def test_recognize_raises_automation_error_on_invalid_image(
    vision_ocr: VisionOCR,
) -> None:
    """If the image cannot be opened, an AutomationError must be raised."""
    # Corrupt image bytes
    frame = CaptureFrame(image=b"not_an_image", timestamp=time.time(), window_id="win")
    with pytest.raises(AutomationError) as excinfo:
        vision_ocr.recognize(frame)
    assert "unable to decode image" in str(excinfo.value).lower()


def test_recognize_retries_on_transient_failure(
    vision_ocr: VisionOCR, tmp_path: Path
) -> None:
    """Transient OCR failures should be retried up to three times."""
    img_bytes = _create_image_with_text("Retry")
    frame = CaptureFrame(image=img_bytes, timestamp=time.time(), window_id="win")
    call_counter = {"count": 0}

    def flaky_ocr(image):
        call_counter["count"] += 1
        if call_counter["count"] < 3:
            raise RuntimeError("temporary OCR failure")
        return [
            UIElement(
                label="Retry",
                bbox=(10, 10, 30, 10),
                confidence=0.95,
                type="button",
            )
        ]

    vision_ocr._ocr_via_tesseract = flaky_ocr
    elements = vision_ocr.recognize(frame)
    assert len(elements) == 1
    assert call_counter["count"] == 3
    assert elements[0].label == "Retry"


def test_recognize_uses_configured_language(
    vision_ocr: VisionOCR, tmp_path: Path, monkeypatch
) -> None:
    """The language setting from the config must be passed to the OCR engine."""
    img_bytes = _create_image_with_text("Lang")
    frame = CaptureFrame(image=img_bytes, timestamp=time.time(), window_id="win")
    vision_ocr.language = "fra"

    captured_args = {}

    def fake_image_to_data(image, lang, config=""):
        captured_args["lang"] = lang
        return _mock_ocr_data(
            [
                {
                    "level": 5,
                    "page_num": 1,
                    "block_num": 1,
                    "par_num": 1,
                    "line_num": 1,
                    "word_num": 1,
                    "left": 15,
                    "top": 15,
                    "width": 40,
                    "height": 20,
                    "conf": "88",
                    "text": "Lang",
                }
            ]
        )

    monkeypatch.setattr(vision_ocr, "_ocr_via_tesseract", lambda img: [
        UIElement(
            label=item["text"],
            bbox=(item["left"], item["top"], item["width"], item["height"]),
            confidence=float(item["conf"]) / 100,
            type="button",
        )
        for item in fake_image_to_data(None, None)
    ])
    # Replace the internal call that would invoke pytesseract directly
    vision_ocr._run_with_retries = lambda func, img: func(img)

    elements = vision_ocr.recognize(frame)
    assert captured_args.get("lang") == "fra"
    assert elements[0].label == "Lang"


def test_recognize_multiple_elements_returned(
    vision_ocr: VisionOCR, tmp_path: Path
) -> None:
    """When OCR detects several words, each should become a UIElement."""
    img_bytes = _create_image_with_text("One Two")
    frame = CaptureFrame(image=img_bytes, timestamp=time.time(), window_id="win")

    def fake_image_to_data(image, lang, config=""):
        return _mock_ocr_data(
            [
                {
                    "level": 5,
                    "page_num": 1,
                    "block_num": 1,
                    "par_num": 1,
                    "line_num": 1,
                    "word_num": 1,
                    "left": 5,
                    "top": 5,
                    "width": 30,
                    "height": 15,
                    "conf": "92",
                    "text": "One",
                },
                {
                    "level": 5,
                    "page_num": 1,
                    "block_num": 1,
                    "par_num": 1,
                    "line_num": 1,
                    "word_num": 2,
                    "left": 40,
                    "top": 5,
                    "width": 35,
                    "height": 15,
                    "conf": "90",
                    "text": "Two",
                },
            ]
        )

    vision_ocr._ocr_via_tesseract = lambda img: [
        UIElement(
            label=item["text"],
            bbox=(item["left"], item["top"], item["width"], item["height"]),
            confidence=float(item["conf"]) / 100,
            type="button",
        )
        for item in fake_image_to_data(None, None)
    ]

    elements = vision_ocr.recognize(frame)
    labels = {el.label for el in elements}
    assert labels == {"One", "Two"}
    assert len(elements) == 2