import base64
import json
import logging
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

def _encode_file_to_base64(file_path: Path) -> str:
    """Read a binary file and return its base64 representation."""
    try:
        with file_path.open("rb") as f:
            encoded = base64.b64encode(f.read()).decode("utf-8")
        return encoded
    except Exception as exc:
        logger.error(f"Failed to encode {file_path} to base64: {exc}")
        raise

def _validate_timestamp(value: float, name: str) -> None:
    """Ensure a timestamp is non‑negative and finite."""
    if not isinstance(value, (int, float)):
        raise TypeError(f"{name} must be a number, got {type(value)}")
    if value < 0 or not (value < float("inf")):
        raise ValueError(f"{name} must be non‑negative and finite, got {value}")

def _validate_nonempty_str(value: str, name: str) -> None:
    """Ensure a string is not empty."""
    if not isinstance(value, str):
        raise TypeError(f"{name} must be a string, got {type(value)}")
    if not value:
        raise ValueError(f"{name} cannot be empty")

@dataclass
class FrameMetadata:
    """
    Metadata for a single extracted frame.
    """
    path: str
    timestamp: float
    phash: str
    ocr_text: str = ""
    scene_id: int = -1

    def __post_init__(self) -> None:
        _validate_nonempty_str(self.path, "path")
        _validate_timestamp(self.timestamp, "timestamp")
        _validate_nonempty_str(self.phash, "phash")
        if not isinstance(self.ocr_text, str):
            raise TypeError("ocr_text must be a string")
        if not isinstance(self.scene_id, int) or self.scene_id < 0:
            raise ValueError("scene_id must be a non‑negative integer")

    def to_dict(self, embed_image: bool = False) -> Dict[str, Any]:
        """
        Convert the frame metadata to a serialisable dictionary.
        If embed_image is True, the image file is base64‑encoded and added under the key ``image_base64``.
        """
        data = {
            "path": self.path,
            "timestamp": self.timestamp,
            "phash": self.phash,
            "ocr_text": self.ocr_text,
            "scene_id": self.scene_id,
        }
        if embed_image:
            try:
                image_path = Path(self.path)
                data["image_base64"] = _encode_file_to_base64(image_path)
            except Exception as exc:
                logger.warning(f"Embedding image failed for {self.path}: {exc}")
                data["image_base64"] = None
        return data

@dataclass
class Scene:
    """
    Represents a continuous segment of the video identified as a scene.
    """
    id: int
    start_idx: int
    end_idx: int
    confidence: float
    keyframe: FrameMetadata

    def __post_init__(self) -> None:
        if not isinstance(self.id, int) or self.id < 0:
            raise ValueError("Scene id must be a non‑negative integer")
        if not isinstance(self.start_idx, int) or self.start_idx < 0:
            raise ValueError("start_idx must be a non‑negative integer")
        if not isinstance(self.end_idx, int) or self.end_idx < self.start_idx:
            raise ValueError("end_idx must be >= start_idx")
        if not isinstance(self.confidence, float) or not (0.0 <= self.confidence <= 1.0):
            raise ValueError("confidence must be a float in [0, 1]")
        if not isinstance(self.keyframe, FrameMetadata):
            raise TypeError("keyframe must be a FrameMetadata instance")

    def to_dict(self, embed_image: bool = False) -> Dict[str, Any]:
        """
        Serialize the scene to a dictionary.
        ``embed_image`` propagates to the contained ``keyframe``.
        """
        return {
            "id": self.id,
            "start_idx": self.start_idx,
            "end_idx": self.end_idx,
            "confidence": self.confidence,
            "keyframe": self.keyframe.to_dict(embed_image=embed_image),
        }

@dataclass
class TranscriptSegment:
    """
    A segment of transcribed speech aligned to a time interval.
    """
    start: float
    end: float
    text: str
    speaker: Optional[str] = None

    def __post_init__(self) -> None:
        _validate_timestamp(self.start, "start")
        _validate_timestamp(self.end, "end")
        if self.end < self.start:
            raise ValueError("end timestamp must be >= start timestamp")
        _validate_nonempty_str(self.text, "text")
        if self.speaker is not None and not isinstance(self.speaker, str):
            raise TypeError("speaker must be a string if provided")

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize the transcript segment to a dictionary.
        """
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "speaker": self.speaker,
        }

@dataclass
class PromptPackage:
    """
    Aggregates all information required to build the final LLM‑ready prompt.
    """
    video_path: str
    frames: List[FrameMetadata] = field(default_factory=list)
    scenes: List[Scene] = field(default_factory=list)
    transcript: List[TranscriptSegment] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    errors: List[Dict[str, str]] = field(default_factory=list)

    def __post_init__(self) -> None:
        _validate_nonempty_str(self.video_path, "video_path")
        if not isinstance(self.frames, list):
            raise TypeError("frames must be a list of FrameMetadata")
        if not isinstance(self.scenes, list):
            raise TypeError("scenes must be a list of Scene")
        if not isinstance(self.transcript, list):
            raise TypeError("transcript must be a list of TranscriptSegment")
        if not isinstance(self.metadata, dict):
            raise TypeError("metadata must be a dictionary")
        if not isinstance(self.errors, list):
            raise TypeError("errors must be a list")

    def add_error(self, code: str, message: str) -> None:
        """
        Record a processing error for later inclusion in the JSON payload.
        """
        self.errors.append({"code": code, "message": message})
        logger.debug(f"Recorded error [{code}]: {message}")

    def to_dict(self, embed_images: bool = False) -> Dict[str, Any]:
        """
        Convert the entire package to a JSON‑serialisable dictionary.
        If ``embed_images`` is True, each frame includes a base64‑encoded image.
        """
        return {
            "video_path": self.video_path,
            "frames": [f.to_dict(embed_image=embed_images) for f in self.frames],
            "scenes": [s.to_dict(embed_image=embed_images) for s in self.scenes],
            "transcript": [t.to_dict() for t in self.transcript],
            "metadata": self.metadata,
            "errors": self.errors,
        }

    def to_json(self, embed_images: bool = False, indent: int = 2) -> str:
        """
        Serialize the package to a JSON string.
        """
        try:
            payload = self.to_dict(embed_images=embed_images)
            return json.dumps(payload, ensure_ascii=False, indent=indent)
        except TypeError as exc:
            logger.error(f"Failed to serialize PromptPackage to JSON: {exc}")
            raise

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PromptPackage":
        """
        Reconstruct a PromptPackage from a dictionary produced by ``to_dict``.
        """
        frames = [FrameMetadata(**f) for f in data.get("frames", [])]
        scenes = [
            Scene(
                id=s["id"],
                start_idx=s["start_idx"],
                end_idx=s["end_idx"],
                confidence=s["confidence"],
                keyframe=FrameMetadata(**s["keyframe"]),
            )
            for s in data.get("scenes", [])
        ]
        transcript = [TranscriptSegment(**t) for t in data.get("transcript", [])]
        return cls(
            video_path=data["video_path"],
            frames=frames,
            scenes=scenes,
            transcript=transcript,
            metadata=data.get("metadata", {}),
            errors=data.get("errors", []),
        )