import json
import subprocess
from datetime import datetime
from typing import List

import pytest
import requests
from rich.console import Console

from src.core.models import FilePatch, Finding, RuntimeConfig, ScanResult
from src.engine.scanner import DiffScanner, run_scan

@pytest.fixture
def runtime_config() -> RuntimeConfig:
    """Provide a minimal RuntimeConfig for tests."""
    return RuntimeConfig(use_apparmor=False, use_landlock=False, use_seccomp=False)

@pytest.fixture
def dummy_diff(tmp_path: pathlib.Path) -> str:
    """Create a temporary git repository and return a diff string.
    """
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True)
    (repo_dir / "example.py").write_text("print('hello')\n")
    subprocess.run(["git", "add", "."], cwd=repo_dir, check=True)
    subprocess.run(["git", "commit", "-m", "initial"], cwd=repo_dir, check=True)
    (repo_dir / "example.py").write_text("print('hello world')\n")
    diff = subprocess.run(["git", "diff"], cwd=repo_dir, capture_output=True, text=True, check=True).stdout
    return diff

def test_scan_returns_scan_result(runtime_config, monkeypatch, tmp_path):
    # Mock the LLM endpoint to return a predictable payload
    def mock_post(url, json, timeout):
        class MockResponse:
            def raise_for_status(self):
                pass
            def json(self):
                return {"findings": [{"line": 1, "severity": "low", "title": "Test", "description": "desc"}]}
        return MockResponse()
    monkeypatch.setattr(requests, "post", mock_post)

    scanner = DiffScanner(runtime_config)
    # Use a dummy diff (no git repo needed for this unit test)
    scanner._git_diff = lambda base, head: "diff --git a/example.py b/example.py\n@@ -1 +1 @@\n-print('hello')\n+print('hello world')"
    result = run_scan(scanner, base="main", head="feature")
    assert isinstance(result, ScanResult)
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.title == "Test"
    assert finding.severity.value == "low"
