import json
import logging
import os
import pathlib
import re
from typing import Dict, List, Tuple, Optional

from src.core.models import MemoryEntry

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------


def _sanitize_filename(name: str) -> str:
    """Return a filesystem‑safe filename derived from *name*.

    All characters that are not alphanumeric, a hyphen, underscore or dot are
    replaced with an underscore. Leading/trailing whitespace is stripped and
    spaces are converted to underscores.
    """
    # Normalise whitespace and strip
    name = name.strip().replace(" ", "_")
    # Replace any unsafe character with an underscore
    return re.sub(r"[^A-Za-z0-9_\-\.]+", "_", name)


class MemoryStore:
    """Append‑only store for :class:`MemoryEntry` objects.

    The store writes each entry to a JSON file whose name is derived from the
    entry's title. Title‑based deduplication is performed by normalising the
    title (lower‑case, collapsed whitespace) before checking for an existing
    file.
    """

    def __init__(self, base_path: pathlib.Path):
        self.base_path = pathlib.Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        logger.debug("MemoryStore initialised at %s", self.base_path)

    def _entry_path(self, title: str) -> pathlib.Path:
        safe_name = _sanitize_filename(title) + ".json"
        return self.base_path / safe_name

    def _normalize(self, title: str) -> str:
        return re.sub(r"\s+", " ", title.strip().lower())

    def write(self, entry: MemoryEntry) -> None:
        """Write *entry* to disk, overwriting any existing entry with the same
        normalised title.
        """
        path = self._entry_path(entry.title)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(entry.dict(), f, ensure_ascii=False, indent=2)
        logger.info("MemoryEntry written to %s", path)

    def read(self, title: str) -> Optional[MemoryEntry]:
        """Read an entry by *title* (case‑insensitive, whitespace‑normalised).

        Returns ``None`` if no matching file is found.
        """
        path = self._entry_path(title)
        if not path.is_file():
            logger.warning("MemoryEntry not found for title %s", title)
            return None
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return MemoryEntry(**data)
