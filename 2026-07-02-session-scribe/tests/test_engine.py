import os
import json
import time
import uuid
import shutil
from datetime import datetime
from pathlib import Path
from typing import List

import pytest

from src.core.engine import ArchiveEngine
from src.core.models import Document, SearchResult, _read_secure, _write_secure, _logger, _open_secure
from src.redaction.redactor import Redactor
from src.summarization.summarizer import Summarizer
from src.indexing.bm25 import BM25Index


@pytest.fixture
def temp_project(tmp_path: Path):
    """
    Create an isolated project directory with a .scribe folder.
    """
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / ".scribe").mkdir()
    # Ensure the engine works relative to this directory
    old_cwd = os.getcwd()
    os.chdir(project_dir)
    yield project_dir
    os.chdir(old_cwd)


@pytest.fixture
def transcript_file(temp_project: Path):
    """
    Create a transcript file for a given session id.
    """
    session_id = "session123"
    transcript_path = temp_project / f"{session_id}.txt"
    # Write initial content
    transcript_path.write_text(
        "User: Hello\n"
        "Assistant: Hi there!\n"
        "User: My API key is secret-12345\n"
        "Assistant: Got it.\n"
    )
    return session_id, transcript_path


def read_state(temp_project: Path) -> dict:
    state_path = temp_project / ".scribe" / "state.json"
    if not state_path.is_file():
        return {}
    with open(state_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_index(temp_project: Path) -> dict:
    index_path = temp_project / ".scribe" / "bm25_index.json"
    if not index_path.is_file():
        return {}
    with open(index_path, "r", encoding="utf-8") as f:
        return json.load(f)


def read_summary(temp_project: Path) -> str:
    summary_path = temp_project / ".scribe" / "context.md"
    if not summary_path.is_file():
        return ""
    return summary_path.read_text(encoding="utf-8")


def test_process_session_incremental_read_and_state_update(
    temp_project: Path, transcript_file
):
    """
    Verify that ArchiveEngine processes only new bytes and updates CaptureState.
    """
    session_id, transcript_path = transcript_file

    engine = ArchiveEngine()
    # First run processes the whole file
    engine.process_session(session_id)

    state = read_state(temp_project)
    assert session_id in state["session_offsets"]
    first_offset = state["session_offsets"][session_id]

    # Append new lines to the transcript
    new_lines = [
        "User: Another secret token: token-abcde\n",
        "Assistant: Noted.\n",
    ]
    with open(transcript_path, "a", encoding="utf-8") as f:
        f.writelines(new_lines)

    # Second run should only read the appended bytes
    engine.process_session(session_id)

    state_after = read_state(temp_project)
    second_offset = state_after["session_offsets"][session_id]
    assert second_offset > first_offset
    # Ensure the offset matches the file size
    assert second_offset == os.path.getsize(transcript_path)


def test_redaction_flow_removes_secrets(temp_project: Path, transcript_file):
    """
    Ensure that Redactor strips configured secret patterns from the transcript.
    """
    session_id, _ = transcript_file

    # Create a simple redaction rule file
    rules_path = temp_project / ".scribe" / "redaction_rules.json"
    rules_path.write_text(
        json.dumps(
            {
                "patterns": [
                    {"regex": r"secret-\\d+", "replace": "[REDACTED]"},
                    {"regex": r"token-\\w+", "replace": "[REDACTED]"},
                ]
            }
        )
    )

    engine = ArchiveEngine()
    engine.process_session(session_id)

    # Load the BM25 index and verify that redacted text appears
    index_data = read_index(temp_project)
    docs: List[dict] = index_data.get("documents", [])
    texts = [doc["text"] for doc in docs]

    assert any("[REDACTED]" in txt for txt in texts)
    # Original secret strings must not be present
    assert not any("secret-12345" in txt for txt in texts)
    assert not any("token-abcde" in txt for txt in texts)


def test_index_updates_and_search_returns_expected_results(temp_project: Path, transcript_file):
    """
    Confirm that new documents are added to the BM25 index and searchable.
    """
    session_id, _ = transcript_file
    engine = ArchiveEngine()
    engine.process_session(session_id)

    # Perform a search for a term that appears in the transcript
    results: List[SearchResult] = engine.search("assistant")
    assert isinstance(results, list)
    assert len(results) > 0
    for result in results:
        assert isinstance(result, SearchResult)
        assert isinstance(result.document, Document)
        assert "Assistant" in result.document.text


def test_summary_generation_creates_context_file(temp_project: Path, transcript_file):
    """
    Verify that Summarizer produces a context.md file with top sentences.
    """
    session_id, _ = transcript_file
    engine = ArchiveEngine()
    engine.process_session(session_id)

    summary = read_summary(temp_project)
    assert summary.strip() != ""
    # The summary should contain at least one line from the original transcript
    assert any("Assistant:" in line for line in summary.splitlines())


def test_process_session_retries_on_transient_read_error(monkeypatch, temp_project: Path, transcript_file):
    """
    Simulate a transient OSError during secure read and ensure ArchiveEngine retries.
    """
    session_id, _ = transcript_file

    call_count = {"reads": 0}

    original_read = _read_secure

    def flaky_read(fd, length):
        call_count["reads"] += 1
        if call_count["reads"] < 3:
            raise OSError("Transient read error")
        return original_read(fd, length)

    monkeypatch.setattr("src.core.models._read_secure", flaky_read)

    start = time.time()
    engine = ArchiveEngine()
    engine.process_session(session_id)
    duration = time.time() - start

    # Ensure that at least three read attempts were made (2 failures + 1 success)
    assert call_count["reads"] >= 3
    # The retry backoff should not cause an excessive delay (allowing up to 2 seconds)
    assert duration < 2.0

    # Verify that processing succeeded despite the transient error
    state = read_state(temp_project)
    assert session_id in state["session_offsets"]


def test_process_session_fatal_error_aborts_cli(monkeypatch, temp_project: Path, transcript_file, capsys):
    """
    Force a fatal error (e.g., inability to write the .scribe directory) and verify that the CLI exits with a clear message.
    """
    session_id, _ = transcript_file

    # Remove write permission from the .scribe directory to trigger a fatal error
    scribe_dir = temp_project / ".scribe"
    scribe_dir.chmod(0o500)  # read/execute only

    # Patch the logger to capture the fatal message
    messages = []

    def capture(msg, *args, **kwargs):
        messages.append(msg % args if args else msg)

    monkeypatch.setattr(_logger, "error", capture)

    engine = ArchiveEngine()
    with pytest.raises(SystemExit) as excinfo:
        engine.process_session(session_id)

    # Restore permissions for cleanup
    scribe_dir.chmod(0o700)

    assert excinfo.value.code != 0
    # The error log should contain a clear description of the failure
    assert any("unable to write" in m.lower() for m in messages) or any(
        "fatal" in m.lower() for m in messages
    )