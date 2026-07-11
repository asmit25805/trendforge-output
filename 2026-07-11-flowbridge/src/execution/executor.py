from __future__ import annotations

import json
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import httpx
from pydantic import ValidationError
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from flowbridge.core.models import ActionSpec, Credential, CredentialType, AuthType

# ---------------------------------------------------------------------------
# Simple SQLite helper – in a real project this would be abstracted
# ---------------------------------------------------------------------------

_DB_PATH = Path("./executor_runs.db")
_DB_LOCK = threading.Lock()

def _init_db() -> None:
    with _DB_LOCK, sqlite3.connect(_DB_PATH) as conn:
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

_init_db()

# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class ActionResult:
    run_id: str
    action_id: str
    status: str
    started_at: datetime
    finished_at: datetime
    result: Optional[Dict[str, Any]] = None

# ---------------------------------------------------------------------------
# Core executor
# ---------------------------------------------------------------------------

class ActionExecutor:
    """Executes a single action using HTTP calls.

    The executor retrieves credentials from the :class:`CredentialVault` (not
    implemented here) and performs the request with exponential back‑off.
    """

    def __init__(self, credential: Optional[Credential] = None):
        self.credential = credential
        self.logger = logging.getLogger(__name__)

    @retry(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
    )
    def _call_provider(self, url: str, payload: Dict[str, Any]) -> httpx.Response:
        headers = {}
        if self.credential:
            if self.credential.type == CredentialType.API_KEY:
                headers["Authorization"] = f"Bearer {self.credential.value}"
            elif self.credential.type == CredentialType.USER_PASS:
                headers["Authorization"] = f"Basic {self.credential.value}"
        self.logger.debug("Calling %s with payload %s", url, payload)
        return httpx.post(url, json=payload, headers=headers, timeout=10)

    def execute(self, action: ActionSpec, params: Dict[str, Any]) -> ActionResult:
        run_id = str(uuid.uuid4())
        started = datetime.utcnow()
        try:
            response = self._call_provider(action.name, params)
            response.raise_for_status()
            result_data = response.json()
            status = "success"
        except Exception as exc:
            self.logger.exception("Action %s failed: %s", action.id, exc)
            result_data = {"error": str(exc)}
            status = "failed"
        finished = datetime.utcnow()
        result = ActionResult(
            run_id=run_id,
            action_id=action.id,
            status=status,
            started_at=started,
            finished_at=finished,
            result=result_data,
        )
        _record_run(result)
        return result

# ---------------------------------------------------------------------------
# Helper to persist a run record
# ---------------------------------------------------------------------------

def _record_run(result: ActionResult) -> None:
    with _DB_LOCK, sqlite3.connect(_DB_PATH) as conn:
        conn.execute(
            "INSERT INTO runs (id, action_id, status, started_at, finished_at, result) VALUES (?, ?, ?, ?, ?, ?)",
            (
                result.run_id,
                result.action_id,
                result.status,
                result.started_at.isoformat(),
                result.finished_at.isoformat(),
                json.dumps(result.result) if result.result is not None else None,
            ),
        )
        conn.commit()

# ---------------------------------------------------------------------------
# Convenience function used by tests and CLI
# ---------------------------------------------------------------------------

def execute_action(action: ActionSpec, params: Dict[str, Any], credential: Optional[Credential] = None) -> ActionResult:
    executor = ActionExecutor(credential)
    return executor.execute(action, params)
