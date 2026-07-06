import json
import logging
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from src.core.models import Job, JobStatus

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class JobScheduler:
    """Lightweight SQLite‑backed job queue.

    The scheduler creates a ``jobs.db`` file in the current working directory.
    It stores a JSON representation of each :class:`~src.core.models.Job`.
    """

    _db_path = Path("./jobs.db")
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._ensure_db()

    def _ensure_db(self) -> None:
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS jobs (
                        id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL
                    )
                    """
                )
                conn.commit()
            finally:
                conn.close()

    def _persist(self, job: Job) -> None:
        payload = json.dumps({
            "id": job.id,
            "status": job.status.value,
            "created_at": job.created_at.isoformat(),
            "updated_at": job.updated_at.isoformat(),
            "spec": job.spec.__dict__ if job.spec else None,
            "result": None,
        })
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO jobs (id, payload) VALUES (?, ?)",
                    (job.id, payload),
                )
                conn.commit()
            finally:
                conn.close()

    def create_job(self, *, symbol: str, start: datetime, end: datetime, prompt: str) -> Job:
        """Create a new job record and schedule it for execution.

        The actual pipeline execution is delegated to :class:`PipelineEngine`
        which runs in a background thread.
        """
        spec = None  # The strategy will be generated later by the engine.
        job = Job(status=JobStatus.PENDING, spec=spec)
        self._persist(job)
        # Fire‑and‑forget execution
        from src.core.engine import PipelineEngine
        engine = PipelineEngine()
        threading.Thread(target=engine.run_job, args=(job.id, symbol, start, end, prompt), daemon=True).start()
        return job

    def get_job(self, job_id: str) -> Optional[Job]:
        """Retrieve a job by its identifier."""
        with self._lock:
            conn = sqlite3.connect(self._db_path)
            try:
                cur = conn.execute("SELECT payload FROM jobs WHERE id = ?", (job_id,))
                row = cur.fetchone()
                if not row:
                    return None
                data = json.loads(row[0])
                job = Job(
                    id=data["id"],
                    status=JobStatus(data["status"]),
                    created_at=datetime.fromisoformat(data["created_at"]),
                    updated_at=datetime.fromisoformat(data["updated_at"]),
                    spec=None,
                    result=None,
                )
                return job
            finally:
                conn.close()
