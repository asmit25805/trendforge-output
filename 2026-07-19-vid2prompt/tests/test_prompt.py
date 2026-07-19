import base64
import json
import os
from pathlib import Path
from typing import List

import pytest
from PIL import Image

from src.core.models import FrameMetadata, Scene, TranscriptSegment, PromptPackage
from src.prompt.generator import PromptGenerator


@pytest.fixture
def temp_image(tmp_path: Path) -> Path:
    """Create a small PNG image and return its path."""
    img_path = tmp_path / "frame.png"
    image = Image.new("RGB", (10, 10), color="red")
    image.save(img_path, format="PNG")
    return img_path


def _make_frame(path: Path, timestamp: float, scene_id: int, ocr_text: str = "") -> FrameMetadata:
    """Construct a FrameMetadata instance with a perceptual hash."""
    # The perceptual hash is a 64‑bit hex string; using a dummy constant for tests.
    phash = "0" * 16
    return FrameMetadata(
        path=str(path),
        timestamp=timestamp,
        phash=phash,
        ocr_text=ocr_text,
        scene_id=scene_id,
    )


def _make_scene(keyframe: FrameMetadata, scene_id: int, start_idx: int, end_idx: int) -> Scene:
    """Construct a Scene instance."""
    return Scene(
        id=scene_id,
        start_idx=start_idx,
        end_idx=end_idx,
        confidence=0.99,
        keyframe=keyframe,
    )


def _make_transcript(start: float, end: float, text: str) -> TranscriptSegment:
    """Construct a TranscriptSegment instance."""
    return TranscriptSegment(start=start, end=end, text=text, speaker="")


def test_prompt_generator_embeds_images_and_counts_tokens(temp_image: Path) -> None:
    """Embedding images should produce base64 data and token estimates."""
    frame = _make_frame(temp_image, timestamp=0.0, scene_id=0, ocr_text="Hello")
    scene = _make_scene(frame, scene_id=0, start_idx=0, end_idx=0)
    transcript = [_make_transcript(0.0, 0.5, "Hello world")]
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[frame],
        scenes=[scene],
        transcript=transcript,
        metadata={},
    )
    generator = PromptGenerator(embed_images=True, token_estimate=True)
    payload = generator.generate(package)

    # Verify image is embedded as base64.
    frame_dict = payload["frames"][0]
    assert "image_base64" in frame_dict
    decoded = base64.b64decode(frame_dict["image_base64"])
    assert decoded[:8] == b"\x89PNG\r\n\x1a\n"

    # Verify token estimate exists and is positive.
    assert "token_estimate" in payload
    assert payload["token_estimate"] > 0


def test_prompt_generator_without_embedding(temp_image: Path) -> None:
    """When embed_images=False, image_base64 should be None."""
    frame = _make_frame(temp_image, timestamp=0.0, scene_id=0)
    scene = _make_scene(frame, scene_id=0, start_idx=0, end_idx=0)
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[frame],
        scenes=[scene],
        transcript=[],
        metadata={},
    )
    generator = PromptGenerator(embed_images=False, token_estimate=False)
    payload = generator.generate(package)

    frame_dict = payload["frames"][0]
    assert frame_dict["image_base64"] is None
    # Token estimate should be omitted when disabled.
    assert "token_estimate" not in payload


def test_prompt_generator_includes_ocr_text(temp_image: Path) -> None:
    """OCR text present in FrameMetadata must appear unchanged in the payload."""
    ocr_text = "Sample OCR content"
    frame = _make_frame(temp_image, timestamp=1.2, scene_id=1, ocr_text=ocr_text)
    scene = _make_scene(frame, scene_id=1, start_idx=0, end_idx=0)
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[frame],
        scenes=[scene],
        transcript=[],
        metadata={},
    )
    generator = PromptGenerator(embed_images=False, token_estimate=False)
    payload = generator.generate(package)

    assert payload["frames"][0]["ocr_text"] == ocr_text


def test_prompt_generator_scene_keyframe_structure(temp_image: Path) -> None:
    """Scene dictionaries must contain a properly formatted keyframe entry."""
    frame = _make_frame(temp_image, timestamp=0.5, scene_id=0)
    scene = _make_scene(frame, scene_id=0, start_idx=0, end_idx=0)
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[frame],
        scenes=[scene],
        transcript=[],
        metadata={},
    )
    generator = PromptGenerator(embed_images=False, token_estimate=False)
    payload = generator.generate(package)

    scene_dict = payload["scenes"][0]
    assert "keyframe" in scene_dict
    keyframe = scene_dict["keyframe"]
    assert keyframe["path"] == str(frame.path)
    assert keyframe["timestamp"] == frame.timestamp
    assert keyframe["phash"] == frame.phash


def test_prompt_generator_transcript_alignment() -> None:
    """Transcript segments should be preserved with correct timestamps."""
    segment1 = _make_transcript(0.0, 1.0, "First sentence.")
    segment2 = _make_transcript(1.0, 2.0, "Second sentence.")
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[],
        scenes=[],
        transcript=[segment1, segment2],
        metadata={},
    )
    generator = PromptGenerator(embed_images=False, token_estimate=False)
    payload = generator.generate(package)

    transcript = payload["transcript"]
    assert len(transcript) == 2
    assert transcript[0]["start"] == 0.0
    assert transcript[0]["end"] == 1.0
    assert transcript[0]["text"] == "First sentence."
    assert transcript[1]["text"] == "Second sentence."


def test_prompt_generator_collects_errors_on_frame_serialisation(monkeypatch, temp_image: Path) -> None:
    """If FrameMetadata.to_dict raises, the error should be recorded and processing continue."""
    frame = _make_frame(temp_image, timestamp=0.0, scene_id=0)

    # Force an exception when converting this specific frame.
    original_to_dict = FrameMetadata.to_dict  # type: ignore[attr-defined]

    def broken_to_dict(self, embed_image: bool = True):
        raise RuntimeError("forced failure")

    monkeypatch.setattr(FrameMetadata, "to_dict", broken_to_dict, raising=False)

    scene = _make_scene(frame, scene_id=0, start_idx=0, end_idx=0)
    package = PromptPackage(
        video_path="dummy.mp4",
        frames=[frame],
        scenes=[scene],
        transcript=[],
        metadata={},
    )
    generator = PromptGenerator(embed_images=False, token_estimate=False)
    payload = generator.generate(package)

    # The payload should still contain a minimal frame entry.
    assert payload["frames"][0]["path"] == frame.path
    # Errors list must contain the serialization failure.
    error_entries = [e for e in generator.errors if e["stage"] == "frame_serialisation"]
    assert len(error_entries) == 1
    assert "forced failure" in error_entries[0]["error"]

    # Restore original method for other tests.
    monkeypatch.setattr(FrameMetadata, "to_dict", original_to_dict, raising=False)