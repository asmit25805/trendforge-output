import time
import types
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from src.core.engine import Engine
from src.core.models import (
    AutomationError,
    CaptureFrame,
    Session,
    UIElement,
    register_plugin,
)


# Helper to create a simple Session with deterministic values
def make_session(tmp_path: Path) -> Session:
    session = Session.load_from_env()
    session.window_id = "12345"
    session.backend_name = "mock"
    session.ocr_provider_name = "mock_ocr"
    session.debug_dir = str(tmp_path)
    return session


# Mock backend plugin
@register_plugin("mock")
class MockBackend:
    def __init__(self, session: Session) -> None:
        self.session = session
        self.inject_tap = MagicMock(name="inject_tap")
        self.inject_key = MagicMock(name="inject_key")
        self.captured = False

    def capture_window(self, window_id: str) -> CaptureFrame:
        self.captured = True
        return CaptureFrame(
            image=b"dummy_image_bytes",
            timestamp=time.time(),
            window_id=window_id,
        )


# Mock OCR provider plugin
@register_plugin("mock_ocr")
class MockOCR:
    def __init__(self, session) -> None:
        self.session = session
        self.call_count = 0
        self.elements_sequence = []

    def recognize(self, frame: CaptureFrame):
        self.call_count += 1
        if self.elements_sequence:
            return self.elements_sequence.pop(0)
        # default high‑confidence element
        return [
            UIElement(
                label="TestButton",
                bbox=(10, 20, 30, 40),
                confidence=0.9,
                type="button",
            )
        ]

    def detect_state(self, frame: CaptureFrame) -> str:
        return "default_state"


@pytest.fixture
def engine(tmp_path: Path) -> Engine:
    session = make_session(tmp_path)
    return Engine(session)


def test_engine_successful_cycle_calls_backend_and_ocr(engine: Engine):
    """Engine.run_cycle should capture the window, run OCR, and inject a tap."""
    # Arrange: ensure backend and OCR are the mocks defined above
    backend = engine.backend
    ocr = engine.ocr_provider
    assert isinstance(backend, MockBackend)
    assert isinstance(ocr, MockOCR)

    # Act
    engine.run_cycle()

    # Assert
    assert backend.captured is True
    assert backend.inject_tap.called
    # The injected coordinates should correspond to the mock UIElement bbox centre
    injected_args = backend.inject_tap.call_args[0]
    x, y = injected_args
    expected_x = 10 + 30 // 2
    expected_y = 20 + 40 // 2
    assert (x, y) == (expected_x, expected_y)


def test_engine_retries_on_transient_ocr_error(engine: Engine, monkeypatch):
    """Transient OCR errors should be retried up to three times before succeeding."""
    ocr = engine.ocr_provider
    # First two calls raise RuntimeError, third returns a valid element
    def flaky_recognize(frame):
        if ocr.call_count < 2:
            raise RuntimeError("Transient OCR failure")
        return [
            UIElement(
                label="RetryButton",
                bbox=(5, 5, 10, 10),
                confidence=0.95,
                type="button",
            )
        ]

    monkeypatch.setattr(ocr, "recognize", flaky_recognize)

    # Speed up back‑off sleeps
    monkeypatch.setattr(time, "sleep", lambda _: None)

    engine.run_cycle()

    # After successful retry, inject_tap should have been called once
    assert engine.backend.inject_tap.called
    injected_x, injected_y = engine.backend.inject_tap.call_args[0]
    assert (injected_x, injected_y) == (5 + 10 // 2, 5 + 10 // 2)


def test_engine_fails_after_max_retries(engine: Engine, monkeypatch):
    """If OCR keeps failing, Engine.run_cycle should raise AutomationError."""
    ocr = engine.ocr_provider

    def always_fail(frame):
        raise RuntimeError("Persistent OCR failure")

    monkeypatch.setattr(ocr, "recognize", always_fail)
    monkeypatch.setattr(time, "sleep", lambda _: None)

    with pytest.raises(AutomationError) as excinfo:
        engine.run_cycle()
    assert "OCR" in str(excinfo.value)


def test_engine_filters_low_confidence_and_retries(engine: Engine, monkeypatch):
    """Elements below the confidence threshold should trigger a retry."""
    ocr = engine.ocr_provider
    # First call returns low‑confidence element, second returns high‑confidence
    low_conf = [
        UIElement(
            label="LowConf",
            bbox=(0, 0, 10, 10),
            confidence=0.2,
            type="button",
        )
    ]
    high_conf = [
        UIElement(
            label="HighConf",
            bbox=(20, 30, 10, 10),
            confidence=0.9,
            type="button",
        )
    ]
    ocr.elements_sequence = [low_conf, high_conf]

    monkeypatch.setattr(time, "sleep", lambda _: None)

    engine.run_cycle()

    # The backend should have been called only once (after successful high‑conf)
    assert engine.backend.inject_tap.called
    injected_x, injected_y = engine.backend.inject_tap.call_args[0]
    assert (injected_x, injected_y) == (20 + 10 // 2, 30 + 10 // 2)


def test_engine_uses_configured_backend_and_ocr_provider(tmp_path: Path):
    """Engine should load the backend and OCR provider specified in the Session."""
    session = make_session(tmp_path)
    session.backend_name = "mock"
    session.ocr_provider_name = "mock_ocr"
    engine = Engine(session)

    assert isinstance(engine.backend, MockBackend)
    assert isinstance(engine.ocr_provider, MockOCR)


def test_engine_multiple_commands_translation(engine: Engine):
    """Engine should translate multiple helper calls into separate automation commands."""
    # Simulate a script that creates two commands via the helper namespace
    script = """
engine.helpers.tap_icon('First')
engine.helpers.tap_icon('Second')
"""
    # Execute the script; it should populate internal command queue
    engine.execute_script(script, globals={})

    # Mock the OCR to return elements matching both labels
    ocr = engine.ocr_provider
    ocr.elements_sequence = [
        [
            UIElement(
                label="First",
                bbox=(0, 0, 10, 10),
                confidence=0.9,
                type="button",
            ),
            UIElement(
                label="Second",
                bbox=(20, 20, 10, 10),
                confidence=0.9,
                type="button",
            ),
        ]
    ]

    engine.run_cycle()

    # Verify that inject_tap was called twice with the correct coordinates
    expected_calls = [
        call(0 + 10 // 2, 0 + 10 // 2),
        call(20 + 10 // 2, 20 + 10 // 2),
    ]
    assert engine.backend.inject_tap.call_args_list == expected_calls