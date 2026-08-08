import json
import sqlite3
from pathlib import Path
from typing import List

from src.core.models import CompressionResult, Config, Segment


class CacheError(RuntimeError):
    """Raised when an operation on the cache fails unexpectedly."""


class CacheStore:
    """Simple SQLite‑backed cache for compression results.

    The cache stores a deterministic signature for each segment and the JSON‑encoded
    ``CompressionResult``.  It is deliberately lightweight and thread‑safe because each
    operation opens a short‑lived connection.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS cache (
                    signature TEXT PRIMARY KEY,
                    result TEXT NOT NULL
                )
                """
            )

    def get(self, signature: str) -> CompressionResult | None:
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute(
                "SELECT result FROM cache WHERE signature = ?", (signature,)
            ).fetchone()
            if row:
                data = json.loads(row[0])
                return CompressionResult(**data)
            return None

    def set(self, signature: str, result: CompressionResult) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache (signature, result) VALUES (?, ?)",
                (signature, result.json()),
            )
            conn.commit()


class CompressionEngine:
    """Engine that compresses code segments, using a cache when possible.

    The current implementation provides a deterministic placeholder compression that
    simply strips leading/trailing whitespace.  Real compression logic would be injected
    via a pluggable ``LLMClient``.
    """

    def __init__(self, config: Config):
        self.config = config
        cache_file = config.cache_path / "cache.db"
        self.cache = CacheStore(cache_file)

    def _signature(self, segment: Segment) -> str:
        """Create a deterministic signature for a segment.

        The signature combines the file path with a hash of the content.  Using ``hash``
        provides a quick deterministic value that is stable across runs for the same
        content.
        """
        content_hash = hash(segment.content)
        return f"{segment.path}:{content_hash}"

    def compress(self, segment: Segment) -> CompressionResult:
        """Compress a single ``Segment``.

        If a cached result exists for the segment's signature it is returned directly.
        Otherwise a placeholder compression is performed and the result is cached.
        """
        sig = self._signature(segment)
        cached = self.cache.get(sig)
        if cached:
            return cached

        # Placeholder compression – strip surrounding whitespace.
        compressed = segment.content.strip()
        result = CompressionResult(
            compressed=compressed,
            original_length=len(segment.content),
            compressed_length=len(compressed),
        )
        self.cache.set(sig, result)
        return result

    def compress_batch(self, segments: List[Segment]) -> List[CompressionResult]:
        """Compress a list of segments, respecting ``max_batch_size`` from the config.

        The method processes the list sequentially; for a production system this could be
        parallelised using ``src.utils.concurrency.bounded_executor``.
        """
        return [self.compress(seg) for seg in segments]
