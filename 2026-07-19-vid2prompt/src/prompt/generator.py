import logging
from pathlib import Path
from typing import List, Dict, Any

from src.core.models import (
    FrameMetadata,
    Scene,
    TranscriptSegment,
    PromptPackage,
)

logger = logging.getLogger(__name__)


def _count_tokens(text: str) -> int:
    """
    Rough token count using whitespace splitting.
    """
    if not text:
        return 0
    return len(text.split())


def _estimate_image_tokens(image_path: Path) -> int:
    """
    Estimate token cost for an embedded image.
    The estimate follows OpenAI's rule of 85 tokens per 1 MiB of base64 data.
    """
    try:
        size_bytes = image_path.stat().st_size
    except Exception as exc:
        logger.warning(f"Unable to stat image {image_path}: {exc}")
        return 0
    size_mib = size_bytes / (1024 * 1024)
    return int(size_mib * 85)


class PromptGenerator:
    """
    Combines keyframes, OCR text, scene info, and transcript into a JSON‑serialisable payload.
    """

    def __init__(self, embed_images: bool = True, token_estimate: bool = True) -> None:
        """
        Initialise the generator.

        Args:
            embed_images: If True, image files are base64‑encoded and embedded in the output.
            token_estimate: If True, an approximate token count is added to the payload.
        """
        self.embed_images = embed_images
        self.token_estimate = token_estimate
        self.errors: List[Dict[str, str]] = []

    def _frame_to_dict(self, frame: FrameMetadata) -> Dict[str, Any]:
        """
        Convert a FrameMetadata instance to a serialisable dictionary,
        optionally embedding the image.
        """
        try:
            return frame.to_dict(embed_image=self.embed_images)
        except Exception as exc:
            logger.error(f"Failed to convert frame {frame.path}: {exc}")
            self.errors.append(
                {"stage": "frame_serialisation", "path": frame.path, "error": str(exc)}
            )
            # Return a minimal representation to keep the payload well‑formed.
            return {
                "path": frame.path,
                "timestamp": frame.timestamp,
                "phash": frame.phash,
                "ocr_text": frame.ocr_text,
                "scene_id": frame.scene_id,
                "image_base64": None,
            }

    def _scene_to_dict(self, scene: Scene) -> Dict[str, Any]:
        """
        Convert a Scene instance to a serialisable dictionary.
        The keyframe is represented using the same image‑embedding policy.
        """
        try:
            keyframe_dict = self._frame_to_dict(scene.keyframe)
        except Exception as exc:
            logger.error(f"Failed to process keyframe for scene {scene.id}: {exc}")
            self.errors.append(
                {
                    "stage": "scene_keyframe",
                    "scene_id": str(scene.id),
                    "error": str(exc),
                }
            )
            keyframe_dict = {}
        return {
            "id": scene.id,
            "start_idx": scene.start_idx,
            "end_idx": scene.end_idx,
            "confidence": scene.confidence,
            "keyframe": keyframe_dict,
        }

    def _transcript_to_dict(self, segment: TranscriptSegment) -> Dict[str, Any]:
        """
        Convert a TranscriptSegment instance to a serialisable dictionary.
        """
        return {
            "start": segment.start,
            "end": segment.end,
            "text": segment.text,
            "speaker": segment.speaker,
        }

    def _calculate_token_estimate(self, package: PromptPackage) -> int:
        """
        Produce a rough token estimate for the whole payload.
        Tokens from OCR text, transcript text, metadata strings and
        embedded images are summed.
        """
        total = 0

        # OCR text tokens
        for frame in package.frames:
            total += _count_tokens(frame.ocr_text)

        # Transcript tokens
        for seg in package.transcript:
            total += _count_tokens(seg.text)

        # Metadata tokens (keys and values)
        for key, value in package.metadata.items():
            total += _count_tokens(str(key))
            total += _count_tokens(str(value))

        # Image tokens if images are embedded
        if self.embed_images:
            for frame in package.frames:
                try:
                    total += _estimate_image_tokens(Path(frame.path))
                except Exception as exc:
                    logger.debug(f"Token estimate for image {frame.path} failed: {exc}")

        return total

    def generate(self, package: PromptPackage) -> Dict[str, Any]:
        """
        Produce the final LLM‑friendly payload dictionary.
        """
        if not isinstance(package, PromptPackage):
            raise TypeError("generate expects a PromptPackage instance")

        logger.info("Generating prompt payload for video %s", package.video_path)

        # Convert frames
        frames_list: List[Dict[str, Any]] = [
            self._frame_to_dict(frame) for frame in package.frames
        ]

        # Convert scenes
        scenes_list: List[Dict[str, Any]] = [
            self._scene_to_dict(scene) for scene in package.scenes
        ]

        # Convert transcript
        transcript_list: List[Dict[str, Any]] = [
            self._transcript_to_dict(seg) for seg in package.transcript
        ]

        payload: Dict[str, Any] = {
            "video_path": package.video_path,
            "metadata": package.metadata,
            "frames": frames_list,
            "scenes": scenes_list,
            "transcript": transcript_list,
        }

        if self.token_estimate:
            token_count = self._calculate_token_estimate(package)
            payload["token_estimate"] = token_count
            logger.debug("Estimated token count: %d", token_count)

        if self.errors:
            payload["errors"] = self.errors
            logger.debug("Collected %d errors during generation", len(self.errors))

        return payload