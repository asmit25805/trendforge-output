import abc
import json
import logging
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import requests

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

API_BASE = "http://localhost:8000/api"
DB_PATH = Path("./run_pipeline.db")
ARTIFACTS_DIR = Path("./artifacts")
ARTIFACTS_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("run_pipeline")

# --------------------------------------------------------------------------- #
# Data models – mirrors the FastAPI request/response schemas
# --------------------------------------------------------------------------- #


@dataclass
class PipelineRunRequest:
    symbols: list[str]
    start: str  # ISO‑8601 datetime string
    end: str
    strategy_prompt: str


@dataclass
class PipelineRunResponse:
    job_id: str


@dataclass
class JobStatusResponse:
    stage: str
    percent: int
    status: str
    error: Optional[str] = None
    download_url: Optional[str] = None


# --------------------------------------------------------------------------- #
# Persistence layer – simple SQLite store for historic runs
# --------------------------------------------------------------------------- #


class RunStore:
    """SQLite‑backed store that records job lifecycle for the example script."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._conn = sqlite3.connect(str(self._db_path))
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS runs (
                job_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                artifact_path TEXT
            )
            """
        )
        self._conn.commit()

    def insert(self, job_id: str, status: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO runs (job_id, status, created_at)
            VALUES (?, ?, ?)
            """,
            (job_id, status, now),
        )
        self._conn.commit()

    def update(
        self,
        job_id: str,
        status: str,
        completed_at: Optional[datetime] = None,
        artifact_path: Optional[Path] = None,
    ) -> None:
        params: list[Any] = [status]
        sql = "UPDATE runs SET status = ?"
        if completed_at:
            sql += ", completed_at = ?"
            params.append(completed_at.isoformat())
        if artifact_path:
            sql += ", artifact_path = ?"
            params.append(str(artifact_path))
        sql += " WHERE job_id = ?"
        params.append(job_id)
        self._conn.execute(sql, tuple(params))
        self._conn.commit()

    def fetch(self, job_id: str) -> Optional[Dict[str, Any]]:
        cur = self._conn.execute(
            "SELECT job_id, status, created_at, completed_at, artifact_path FROM runs WHERE job_id = ?",
            (job_id,),
        )
        row = cur.fetchone()
        if row:
            return {
                "job_id": row[0],
                "status": row[1],
                "created_at": row[2],
                "completed_at": row[3],
                "artifact_path": row[4],
            }
        return None


# --------------------------------------------------------------------------- #
# Abstract agent definition – enables alternative implementations
# --------------------------------------------------------------------------- #


class Agent(abc.ABC):
    """Base class for agents that drive the pipeline via the HTTP API."""

    @abc.abstractmethod
    def run(self) -> None:
        """Execute the full lifecycle: submit, poll, download."""
        ...


# --------------------------------------------------------------------------- #
# Concrete implementation used by the example script
# --------------------------------------------------------------------------- #


class PipelineRunner(Agent):
    """Runs a pipeline job, polls until terminal, and stores the artefact."""

    def __init__(
        self,
        request: PipelineRunRequest,
        store: RunStore,
        max_poll_seconds: int = 300,
        poll_interval: int = 5,
    ) -> None:
        self.request = request
        self.store = store
        self.max_poll_seconds = max_poll_seconds
        self.poll_interval = poll_interval

    def _post_run(self) -> str:
        url = f"{API_BASE}/pipeline/run"
        logger.info("Submitting pipeline job to %s", url)
        resp = requests.post(url, json=asdict(self.request), timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to start job: {resp.status_code} {resp.text}")
        data = resp.json()
        job_id = data.get("job_id")
        if not job_id:
            raise RuntimeError("Response missing job_id")
        logger.info("Job created with id %s", job_id)
        self.store.insert(job_id, "pending")
        return job_id

    def _poll_status(self, job_id: str) -> JobStatusResponse:
        url = f"{API_BASE}/jobs/{job_id}"
        logger.debug("Polling status at %s", url)
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            raise RuntimeError(f"Status poll failed: {resp.status_code} {resp.text}")
        payload = resp.json()
        return JobStatusResponse(**payload)

    def _download_artifact(self, job_id: str, download_url: str) -> Path:
        logger.info("Downloading artefact for job %s from %s", job_id, download_url)
        resp = requests.get(download_url, stream=True, timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Failed to download artefact: {resp.status_code}")
        dest = ARTIFACTS_DIR / f"{job_id}.zip"
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        logger.info("Artefact saved to %s", dest)
        return dest

    def _exponential_backoff(self, attempt: int) -> float:
        base = 1.0
        jitter = 0.1 * attempt
        return base * (2 ** attempt) + jitter

    def run(self) -> None:
        try:
            job_id = self._post_run()
        except Exception as exc:
            logger.error("Job submission failed: %s", exc)
            return

        deadline = datetime.now(timezone.utc) + timedelta(seconds=self.max_poll_seconds)
        attempt = 0
        while datetime.now(timezone.utc) < deadline:
            try:
                status_resp = self._poll_status(job_id)
            except Exception as exc:
                logger.warning("Transient poll error: %s", exc)
                backoff = self._exponential_backoff(attempt)
                logger.info("Retrying poll after %.1f seconds", backoff)
                time.sleep(backoff)
                attempt += 1
                continue

            self.store.update(job_id, status_resp.status)

            logger.info(
                "Job %s – stage: %s, %d%% complete, status: %s",
                job_id,
                status_resp.stage,
                status_resp.percent,
                status_resp.status,
            )

            if status_resp.status in ("success", "failed"):
                if status_resp.status == "success" and status_resp.download_url:
                    try:
                        artifact_path = self._download_artifact(job_id, status_resp.download_url)
                        self.store.update(job_id, "success", completed_at=datetime.now(timezone.utc), artifact_path=artifact_path)
                    except Exception as exc:
                        logger.error("Download failed: %s", exc)
                        self.store.update(job_id, "failed", completed_at=datetime.now(timezone.utc))
                else:
                    self.store.update(job_id, status_resp.status, completed_at=datetime.now(timezone.utc))
                break

            time.sleep(self.poll_interval)

        else:
            logger.error("Polling timed out after %d seconds", self.max_poll_seconds)
            self.store.update(job_id, "failed", completed_at=datetime.now(timezone.utc))


# --------------------------------------------------------------------------- #
# Helper to build a request from CLI arguments (simple static example)
# --------------------------------------------------------------------------- #


def build_example_request() -> PipelineRunRequest:
    now = datetime.now(timezone.utc)
    start = (now - timedelta(days=30)).replace(hour=0, minute=0, second=0, microsecond=0)
    end = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return PipelineRunRequest(
        symbols=["000001.SZ", "600000.SH"],
        start=start.isoformat(),
        end=end.isoformat(),
        strategy_prompt=(
            "Generate a simple mean‑reversion strategy: buy when close is below the 20‑day SMA, "
            "sell when above the 20‑day SMA. Use a fixed position size of 100 shares."
        ),
    )


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


def main() -> None:
    store = RunStore(DB_PATH)
    request = build_example_request()
    runner = PipelineRunner(request=request, store=store)
    runner.run()


if __name__ == "__main__":
    main()