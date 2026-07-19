import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest
from unittest import mock

from src.core.engine import VideoProcessor, Config
from src.core.models import PromptPackage
from src.prompt.generator import PromptGenerator


@pytest.fixture
def temp_video(tmp_path: Path) -> Path:
    """
    Create a short silent video using ffmpeg for testing.
    """
    video_path = tmp_path / "test.mp4"
    # Generate a 2‑second black video (640x360)
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        "color=c=black:s=640x360:d=2",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(video_path),
    ]
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return video_path


def _run_processor(video_path: Path, *, strict: bool = False, ocr: bool = False) -> PromptPackage:
    """
    Helper that runs the VideoProcessor with a minimal Config.
    """
    cfg = Config(
        ocr_enabled=ocr,
        strict=strict,
        embed_images=False,
        token_estimate=False,
    )
    processor = VideoProcessor()
    return processor.process(str(video_path), cfg)


def test_engine_process_creates_prompt_package(temp_video: Path) -> None:
    """
    Verify that processing a valid video returns a populated PromptPackage.
    """
    package = _run_processor(temp_video)
    assert isinstance(package, PromptPackage)
    assert package.video_path == str(temp_video)
    assert len(package.frames) > 0, "No frames extracted"
    assert len(package.scenes) > 0, "No scenes detected"
    # Transcript may be empty for silent video but must be a list.
    assert isinstance(package.transcript, list)


def test_engine_missing_ffmpeg_fatal_error(temp_video: Path) -> None:
    """
    Ensure the pipeline aborts with a non‑zero exit code when ffmpeg is unavailable.
    """
    with mock.patch.object(shutil, "which", return_value=None):
        cfg = Config()
        processor = VideoProcessor()
        with pytest.raises(SystemExit) as excinfo:
            processor.process(str(temp_video), cfg)
        assert excinfo.value.code != 0


def test_engine_ocr_failure_is_logged(temp_video: Path) -> None:
    """
    Simulate an OCR failure on a single frame and verify it is recorded without aborting.
    """
    # Patch the OCR function used inside VideoProcessor to raise on the first call.
    original_ocr = VideoProcessor._run_ocr  # type: ignore[attr-defined]

    def failing_ocr(self, frame_path: str) -> str:
        if not hasattr(self, "_ocr_failed"):
            self._ocr_failed = True
            raise RuntimeError("OCR engine crashed")
        return original_ocr(self, frame_path)  # type: ignore[arg-type]

    with mock.patch.object(VideoProcessor, "_run_ocr", failing_ocr):
        package = _run_processor(temp_video, ocr=True)
        # The package should still contain frames and scenes.
        assert len(package.frames) > 0
        # Errors list must contain an OCR entry.
        ocr_errors = [e for e in package.metadata.get("errors", []) if e.get("stage") == "ocr"]
        assert ocr_errors, "OCR error not recorded"


def test_engine_strict_mode_fatal_on_ocr_error(temp_video: Path) -> None:
    """
    With strict mode enabled, an OCR failure should abort the pipeline.
    """
    original_ocr = VideoProcessor._run_ocr  # type: ignore[attr-defined]

    def failing_ocr(self, frame_path: str) -> str:
        raise RuntimeError("OCR engine crashed")

    with mock.patch.object(VideoProcessor, "_run_ocr", failing_ocr):
        cfg = Config(ocr_enabled=True, strict=True)
        processor = VideoProcessor()
        with pytest.raises(SystemExit) as excinfo:
            processor.process(str(temp_video), cfg)
        assert excinfo.value.code != 0


def test_engine_transcriber_partial_failure(temp_video: Path) -> None:
    """
    Simulate a Whisper transcription error for a segment and ensure processing continues.
    """
    original_transcribe = VideoProcessor._run_transcribe  # type: ignore[attr-defined]

    def flaky_transcribe(self, audio_path: str, timestamps: List[float]) -> List[Dict[str, Any]]:
        # Return a valid segment for the first timestamp, then raise.
        if not hasattr(self, "_transcribe_called"):
            self._transcribe_called = True
            return original_transcribe(self, audio_path, timestamps)  # type: ignore[arg-type]
        raise RuntimeError("Whisper decoding error")

    with mock.patch.object(VideoProcessor, "_run_transcribe", flaky_transcribe):
        package = _run_processor(temp_video, strict=False)
        # At least one transcript segment should be present.
        assert len(package.transcript) >= 1
        # Errors list must contain a transcription entry.
        trans_errors = [
            e for e in package.metadata.get("errors", []) if e.get("stage") == "transcription"
        ]
        assert trans_errors, "Transcription error not recorded"


def test_prompt_generator_token_estimate(temp_video: Path) -> None:
    """
    Verify that token estimation is added when enabled and reflects image size.
    """
    package = _run_processor(temp_video, ocr=False)
    generator = PromptGenerator(embed_images=False, token_estimate=True)
    payload = generator.generate(package)
    assert "token_estimate" in payload
    # Token estimate should be a positive integer.
    assert isinstance(payload["token_estimate"], int)
    assert payload["token_estimate"] > 0
    # Ensure errors from generator are propagated.
    if generator.errors:
        assert isinstance(payload.get("errors"), list) and payload["errors"] == generator.errors