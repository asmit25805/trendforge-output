import subprocess
import shutil
import tempfile
import logging
import json
import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from PIL import Image
import numpy as np
import imagehash

from src.core.models import FrameMetadata, Scene, TranscriptSegment, PromptPackage
from src.detectors.scene import SceneDetector
from src.dedup.deduplicator import FrameDeduplicator
from src.prompt.generator import PromptGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")


@dataclass
class Config:
    """CLI configuration controlling optional steps and strictness."""
    ocr: bool = False
    strict: bool = False
    ocr_lang: str = "eng"
    whisper_model: str = "base"
    output_path: Path = Path("output.json")
    temp_dir: Optional[Path] = None
    ffmpeg_path: str = "ffmpeg"
    ffprobe_path: str = "ffprobe"


class VideoProcessor:
    """Orchestrates the full vid2prompt pipeline."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self.errors: List[Dict[str, str]] = []

    def _require_executable(self, name: str, path: str) -> None:
        if shutil.which(path) is None:
            msg = f"Required executable '{name}' not found in PATH."
            logger.error(msg)
            raise RuntimeError(msg)

    def _run_ffprobe_fps(self, video_path: Path) -> float:
        cmd = [
            self.config.ffprobe_path,
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=r_frame_rate",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(video_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        num, den = result.stdout.strip().split("/")
        fps = float(num) / float(den)
        logger.info(f"Detected video FPS: {fps:.2f}")
        return fps

    def _extract_frames(self, video_path: Path, work_dir: Path, fps: float) -> List[Path]:
        pattern = work_dir / "frame_%06d.jpg"
        cmd = [
            self.config.ffmpeg_path,
            "-i",
            str(video_path),
            "-vf",
            f"fps={fps}",
            "-q:v",
            "2",
            str(pattern),
        ]
        logger.info("Extracting frames with ffmpeg...")
        subprocess.run(cmd, capture_output=True, check=True)
        frames = sorted(work_dir.glob("frame_*.jpg"))
        logger.info(f"Extracted {len(frames)} frames.")
        return frames

    def _load_image_array(self, img_path: Path) -> np.ndarray:
        with Image.open(img_path) as img:
            return np.array(img.convert("RGB"))

    def _compute_phash(self, img_path: Path) -> str:
        with Image.open(img_path) as img:
            phash = imagehash.phash(img)
            return str(phash)

    def _run_ocr(self, frame: FrameMetadata) -> None:
        try:
            import pytesseract

            img = Image.open(frame.path)
            text = pytesseract.image_to_string(img, lang=self.config.ocr_lang)
            frame.ocr_text = text.strip()
        except Exception as exc:
            err = {"stage": "ocr", "message": f"OCR failed for {frame.path}: {exc}"}
            self.errors.append(err)
            logger.warning(err["message"])
            if self.config.strict:
                raise RuntimeError(err["message"])

    def _extract_audio(self, video_path: Path, work_dir: Path) -> Path:
        audio_path = work_dir / "audio.wav"
        cmd = [
            self.config.ffmpeg_path,
            "-i",
            str(video_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(audio_path),
        ]
        logger.info("Extracting audio track...")
        subprocess.run(cmd, capture_output=True, check=True)
        return audio_path

    def _transcribe(self, audio_path: Path, timestamps: List[float]) -> List[TranscriptSegment]:
        from src.transcribe.transcriber import Transcriber  # type: ignore

        transcriber = Transcriber(model_name=self.config.whisper_model)
        try:
            segments = transcriber.transcribe(str(audio_path), timestamps)
            return [
                TranscriptSegment(
                    start=s["start"],
                    end=s["end"],
                    text=s["text"],
                    speaker=s.get("speaker", ""),
                )
                for s in segments
            ]
        except Exception as exc:
            err = {"stage": "transcribe", "message": f"Transcription failed: {exc}"}
            self.errors.append(err)
            logger.warning(err["message"])
            if self.config.strict:
                raise RuntimeError(err["message"])
            return []

    def process(self, video_path: str, config: Config) -> PromptPackage:
        """Run the full pipeline and return a PromptPackage."""
        self.config = config
        self._require_executable("ffmpeg", self.config.ffmpeg_path)
        self._require_executable("ffprobe", self.config.ffprobe_path)

        video_path_obj = Path(video_path).resolve()
        if not video_path_obj.is_file():
            raise FileNotFoundError(f"Video file not found: {video_path}")

        temp_root = Path(self.config.temp_dir) if self.config.temp_dir else Path(tempfile.mkdtemp())
        logger.info(f"Using temporary workspace: {temp_root}")

        with tempfile.TemporaryDirectory(dir=temp_root) as work_dir_str:
            work_dir = Path(work_dir_str)

            fps = self._run_ffprobe_fps(video_path_obj)
            frame_paths = self._extract_frames(video_path_obj, work_dir, fps)

            # Build initial FrameMetadata list
            frames_meta: List[FrameMetadata] = []
            for idx, fp in enumerate(frame_paths):
                timestamp = idx / fps
                phash = self._compute_phash(fp)
                frames_meta.append(
                    FrameMetadata(
                        path=str(fp),
                        timestamp=timestamp,
                        phash=phash,
                        ocr_text="",
                        scene_id=-1,
                    )
                )

            # Scene detection
            logger.info("Detecting scenes...")
            img_arrays = [self._load_image_array(p) for p in frame_paths]
            detector = SceneDetector()
            scenes_raw = detector.detect(img_arrays)

            # Group frames by scene
            scenes: List[Scene] = []
            for scene_info in scenes_raw:
                start = scene_info.start_idx
                end = scene_info.end_idx
                scene_frames = frames_meta[start : end + 1]

                # Deduplication
                dedup = FrameDeduplicator()
                kept_frames = dedup.dedup(scene_frames)

                # Assign scene_id
                scene_id = scene_info.id
                for f in kept_frames:
                    f.scene_id = scene_id

                keyframe = kept_frames[0] if kept_frames else scene_frames[0]
                scenes.append(
                    Scene(
                        id=scene_id,
                        start_idx=start,
                        end_idx=end,
                        confidence=scene_info.confidence,
                        keyframe=keyframe,
                    )
                )

                # Replace original frames with deduped ones for final payload
                frames_meta = [
                    f for f in frames_meta if f not in scene_frames
                ] + kept_frames

            # OCR (optional)
            if self.config.ocr:
                logger.info("Running OCR on retained frames...")
                for frame in frames_meta:
                    self._run_ocr(frame)

            # Transcription
            audio_path = self._extract_audio(video_path_obj, work_dir)
            timestamps = [f.timestamp for f in frames_meta]
            transcript = self._transcribe(audio_path, timestamps)

            # Assemble package
            package = PromptPackage(
                video_path=str(video_path_obj),
                frames=frames_meta,
                scenes=scenes,
                transcript=transcript,
                metadata={},
            )

            # Generate final JSON payload
            generator = PromptGenerator()
            payload = generator.generate(package)
            payload["errors"] = self.errors

            # Write output
            output_path = self.config.output_path
            logger.info(f"Writing output to {output_path}")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)

            logger.info("Process completed successfully")
            return package

__all__ = ["VideoProcessor", "Config"]