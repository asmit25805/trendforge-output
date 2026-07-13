import json
import logging
import os
import sqlite3
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __name__ as package_name
from ..core.models import IllustrationRequest, IllustrationResult, QAReport
from ..tools import emit_event, register_event_handler, _build_pydantic_model

logger = logging.getLogger(package_name)
handler = logging.StreamHandler()
formatter = logging.Formatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s", "%Y-%m-%d %H:%M:%S"
)
handler.setFormatter(formatter)
logger.addHandler(handler)
logger.setLevel(logging.INFO)

class MemoryStore:
    """Simple SQLite‑backed store for persisting requests and results.

    This implementation is intentionally lightweight for demonstration
    purposes. Production systems may replace it with a more robust solution.
    """

    def __init__(self, db_path: Path | str = ":memory:"):
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS illustration_results (
                request_id TEXT PRIMARY KEY,
                result_json TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        self.conn.commit()

    def save_result(self, result: IllustrationResult) -> None:
        payload = json.dumps(result.dict())
        self.conn.execute(
            "INSERT OR REPLACE INTO illustration_results (request_id, result_json) VALUES (?, ?)",
            (result.request_id, payload),
        )
        self.conn.commit()
        emit_event("result_saved", result)

    def get_result(self, request_id: str) -> Optional[IllustrationResult]:
        cur = self.conn.execute(
            "SELECT result_json FROM illustration_results WHERE request_id = ?", (request_id,)
        )
        row = cur.fetchone()
        if row:
            data = json.loads(row[0])
            return IllustrationResult(**data)
        return None
