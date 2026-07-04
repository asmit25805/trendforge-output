import re
from pathlib import Path
import time

import pytest

from src.core.models import MemoryEntry
from src.memory.store import MemoryStore, _sanitize_filename


def _normalized(title: str) -> str:
    """Replicate the internal normalization used for title similarity."""
    return re.sub(r"\s+", " ", title.strip().lower())


def test_write_and_read_persists_entry(tmp_path: Path) -> None:
    store = MemoryStore(base_path=tmp_path)
    entry = MemoryEntry(title="Test Entry", content="Some content", timestamp=time.time())
    store.write(entry)
    # Read back using the original title (case‑insensitive, whitespace‑normalized)
    read_entry = store.read(entry.title)
    assert read_entry is not None
    assert _normalized(read_entry.title) == _normalized(entry.title)
    assert read_entry.content == entry.content


def test_sanitize_filename_removes_invalid_chars():
    unsafe = "My / Invalid : Title?*"
    safe = _sanitize_filename(unsafe)
    assert "/" not in safe and ":" not in safe and "?" not in safe and "*" not in safe
    # The sanitized name should still contain the alphanumeric characters
    for ch in "My Invalid Title":
        assert ch in safe
