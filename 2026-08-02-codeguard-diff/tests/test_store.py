import os
import sqlite3
from datetime import datetime, timezone
from typing import List

import pytest

from src.core.models import FilePatch, Finding, ScanResult, RuntimeConfig, Severity, FindingStatus
from src.store.sqlite import FindingsStore, initialize_db, FINDINGS_PAGE_MAX

@pytest.fixture
def in_memory_store() -> FindingsStore:
    """Create a FindingsStore backed by an in‑memory SQLite database."""
    conn = initialize_db(":memory:")
    return FindingsStore(conn)

def test_save_and_list_findings(in_memory_store: FindingsStore):
    cfg = RuntimeConfig(use_apparmor=False, use_landlock=False, use_seccomp=False)
    patch = FilePatch(file_path=Path("example.py"), added_lines=[1], removed_lines=[0], diff="+print('hi')")
    finding = Finding(
        file_path=Path("example.py"),
        line=1,
        severity=Severity.LOW,
        title="Test finding",
        description="A test finding",
        status=FindingStatus.OPEN,
    )
    result = ScanResult(patches=[patch], findings=[finding], runtime_config=cfg)
    in_memory_store.save_scan_result(result)
    retrieved = in_memory_store.list_findings(limit=FINDINGS_PAGE_MAX)
    assert len(retrieved) == 1
    assert retrieved[0].title == "Test finding"
