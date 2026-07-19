import logging
from pathlib import Path
from typing import List, Dict, Iterable

from src.core.models import FrameMetadata


class FrameDeduplicator:
    """
    Removes near‑identical frames inside a scene to minimise token usage while preserving visual context.
    """

    def __init__(self, phash_threshold: int = 5, logger: logging.Logger | None = None) -> None:
        """
        Initialise the deduplicator.

        Args:
            phash_threshold: Maximum Hamming distance between perceptual hashes for frames to be considered duplicates.
            logger: Optional logger; if omitted a module‑level logger is created.
        """
        self.phash_threshold = phash_threshold
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _hex_to_int(phash: str) -> int:
        """
        Convert a 16‑character hexadecimal perceptual hash to a 64‑bit integer.

        Args:
            phash: Hexadecimal string representation of the hash.

        Returns:
            Integer value of the hash.

        Raises:
            ValueError: If the string is not a valid 16‑character hex.
        """
        if len(phash) != 16:
            raise ValueError(f"Invalid phash length: expected 16, got {len(phash)}")
        return int(phash, 16)

    @staticmethod
    def _hamming_distance(hash_a: str, hash_b: str) -> int:
        """
        Compute the Hamming distance between two 64‑bit perceptual hashes.

        Args:
            hash_a: Hexadecimal string of the first hash.
            hash_b: Hexadecimal string of the second hash.

        Returns:
            Number of differing bits.
        """
        int_a = FrameDeduplicator._hex_to_int(hash_a)
        int_b = FrameDeduplicator._hex_to_int(hash_b)
        xor = int_a ^ int_b
        # Python's bit_count (3.8+) counts set bits efficiently.
        return xor.bit_count()

    def _dedup_scene(self, frames: List[FrameMetadata]) -> List[FrameMetadata]:
        """
        Deduplicate frames belonging to a single scene.

        The first frame is always kept. Subsequent frames are kept only if their
        perceptual hash differs from the last retained frame by more than the
        configured threshold.

        Args:
            frames: List of FrameMetadata objects belonging to the same scene,
                    ordered by timestamp.

        Returns:
            Filtered list of FrameMetadata objects.
        """
        if not frames:
            return []

        retained: List[FrameMetadata] = [frames[0]]
        last_hash = frames[0].phash

        for frame in frames[1:]:
            try:
                distance = self._hamming_distance(last_hash, frame.phash)
            except Exception as exc:
                # Log the problem and conservatively keep the frame.
                self.logger.warning(
                    "Failed to compute hamming distance for frame %s: %s. Keeping frame.",
                    frame.path,
                    exc,
                )
                retained.append(frame)
                last_hash = frame.phash
                continue

            if distance > self.phash_threshold:
                retained.append(frame)
                last_hash = frame.phash
                self.logger.debug(
                    "Kept frame %s (distance %d > %d)", frame.path, distance, self.phash_threshold
                )
            else:
                self.logger.debug(
                    "Discarded duplicate frame %s (distance %d <= %d)", frame.path, distance, self.phash_threshold
                )
        return retained

    def dedup(self, frames: List[FrameMetadata]) -> List[FrameMetadata]:
        """
        Filter near‑duplicate frames across all scenes.

        Frames are first grouped by their ``scene_id``. Within each scene the
        deduplication logic defined in ``_dedup_scene`` is applied.

        Args:
            frames: List of FrameMetadata objects extracted from the video.

        Returns:
            New list containing only the retained frames.
        """
        if not frames:
            self.logger.info("No frames provided to deduplicate.")
            return []

        # Group frames by scene_id while preserving order.
        scene_groups: Dict[int, List[FrameMetadata]] = {}
        for frame in frames:
            scene_groups.setdefault(frame.scene_id, []).append(frame)

        self.logger.info("Deduplicating %d frames across %d scenes.", len(frames), len(scene_groups))

        deduped_frames: List[FrameMetadata] = []
        for scene_id, scene_frames in sorted(scene_groups.items()):
            # Ensure deterministic ordering by timestamp.
            scene_frames.sort(key=lambda f: f.timestamp)
            self.logger.debug("Processing scene %d with %d frames.", scene_id, len(scene_frames))
            kept = self._dedup_scene(scene_frames)
            deduped_frames.extend(kept)
            self.logger.debug(
                "Scene %d reduced from %d to %d frames.", scene_id, len(scene_frames), len(kept)
            )

        self.logger.info(
            "Deduplication complete: %d frames reduced to %d.", len(frames), len(deduped_frames)
        )
        return deduped_frames


# Helper for external modules that may want a singleton with default settings.
_default_deduplicator = FrameDeduplicator()


def deduplicate_frames(frames: List[FrameMetadata], *, phash_threshold: int | None = None) -> List[FrameMetadata]:
    """
    Convenience function to deduplicate frames using the default deduplicator.

    Args:
        frames: List of FrameMetadata objects.
        phash_threshold: Optional override for the Hamming distance threshold.

    Returns:
        List of retained FrameMetadata objects.
    """
    if phash_threshold is not None:
        deduplicator = FrameDeduplicator(phash_threshold=phash_threshold)
    else:
        deduplicator = _default_deduplicator
    return deduplicator.dedup(frames)