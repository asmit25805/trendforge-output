import json
import sqlite3
from pathlib import Path
from typing import Any, Dict

import httpx
import pytest
from pydantic import ValidationError

from flowbridge.core.models import ActionSpec, Credential, CredentialType, AuthType
from flowbridge.execution.executor import ActionExecutor, execute_action, _DB_PATH, _record_run

@pytest.fixture
def temp_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temporary SQLite database for the executor tests.

    The fixture patches the module‑level ``_DB_PATH`` constant so that the
    executor writes to a temporary file instead of the production location.
    """
    db_file = tmp_path / "test_executor.db"
    monkeypatch.setattr("flowbridge.execution.executor._DB_PATH", db_file)
    # Re‑initialise the DB schema for the temporary file
    with sqlite3.connect(db_file) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                action_id TEXT NOT NULL,
                status TEXT NOT NULL,
                started_at TEXT,
                finished_at TEXT,
                result TEXT
            )
            """
        )
        conn.commit()
    return db_file

def test_execute_action_success(temp_db_path: Path):
    """Execute a dummy action and verify a successful run is recorded."""
    # Mock a simple HTTP endpoint using httpx's MockTransport
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    httpx._client = client  # monkey‑patch httpx globally for this test

    action = ActionSpec(id="test_action", name="https://example.com/api", parameters={})
    result = execute_action(action, params={"foo": "bar"})
    assert result.status == "success"
    assert result.result == {"ok": True}

    # Verify the run was persisted
    with sqlite3.connect(temp_db_path) as conn:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (result.run_id,)).fetchone()
        assert row is not None
        assert row[0] == "success"

def test_execute_action_failure(temp_db_path: Path):
    """Simulate a failing HTTP request and ensure the executor records a failure."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"error": "boom"})

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    httpx._client = client

    action = ActionSpec(id="fail_action", name="https://example.com/fail", parameters={})
    result = execute_action(action, params={})
    assert result.status == "failed"
    assert "error" in result.result

    with sqlite3.connect(temp_db_path) as conn:
        row = conn.execute("SELECT status FROM runs WHERE id = ?", (result.run_id,)).fetchone()
        assert row is not None
        assert row[0] == "failed"
