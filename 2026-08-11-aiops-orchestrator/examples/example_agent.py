import asyncio
import logging
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, Any

import aiohttp.web

from src.core.models import Event, EventBus, logger as core_logger
from src.scheduler.cron import Scheduler, CronJob

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

_DB_FILE = Path(".example_agent.db")
_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS task_runs (
    id TEXT PRIMARY KEY,
    start_ts TEXT NOT NULL,
    duration REAL NOT NULL,
    result TEXT NOT NULL
);
"""

# --------------------------------------------------------------------------- #
# Data structures
# --------------------------------------------------------------------------- #

@dataclass(frozen=True, slots=True)
class ExampleTaskRecord:
    """Immutable record of a single task execution."""
    id: str
    start: datetime
    duration: float
    result: str

    def as_tuple(self) -> tuple:
        """Return a tuple suitable for SQLite insertion."""
        return (self.id, self.start.isoformat(), self.duration, self.result)


# --------------------------------------------------------------------------- #
# Internal helpers
# --------------------------------------------------------------------------- #

def _init_db(db_path: Path = _DB_FILE) -> None:
    """Create the SQLite database and required table if they do not exist."""
    core_logger.debug("Initialising SQLite database at %s", db_path)
    with sqlite3.connect(db_path) as conn:
        conn.executescript(_TABLE_SCHEMA)


def _store_record(record: ExampleTaskRecord, db_path: Path = _DB_FILE) -> None:
    """Persist a task record to the SQLite database."""
    core_logger.debug(
        "Storing task record %s (duration=%.3f)", record.id, record.duration
    )
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO task_runs (id, start_ts, duration, result) VALUES (?, ?, ?, ?)",
            record.as_tuple(),
        )
        conn.commit()


def _publish_completion(event_bus: EventBus, record: ExampleTaskRecord) -> None:
    """Publish an Event signalling the task has finished."""
    event = Event(
        type="example_task_completed",
        payload={
            "task_id": record.id,
            "start": record.start.isoformat(),
            "duration": record.duration,
            "result": record.result,
        },
        origin="example_agent",
    )
    core_logger.debug("Publishing completion event for task %s", record.id)
    # EventBus.publish is async; fire‑and‑forget in a background task.
    asyncio.create_task(event_bus.publish(event))


# --------------------------------------------------------------------------- #
# Core task implementation
# --------------------------------------------------------------------------- #

def example_task_handler() -> None:
    """
    Execute the example task.

    The function is intended to be referenced by a CronJob via its dotted
    path ``examples.example_agent:example_task_handler``. It records its
    execution duration, stores a result in SQLite, and emits an Event on the
    central EventBus.
    """
    start_ts = datetime.now(timezone.utc)
    task_id = str(uuid.uuid4())
    core_logger.info("Starting example task %s at %s", task_id, start_ts.isoformat())

    # Simulated workload – compute a deterministic hash.
    total = 0
    for i in range(1_000_0):
        total += i * i
    result = f"sum_of_squares={total}"

    end_ts = datetime.now(timezone.utc)
    duration = (end_ts - start_ts).total_seconds()
    record = ExampleTaskRecord(
        id=task_id,
        start=start_ts,
        duration=duration,
        result=result,
    )

    _store_record(record)
    _publish_completion(_global_event_bus, record)

    core_logger.info(
        "Example task %s completed in %.3f s with result: %s",
        task_id,
        duration,
        result,
    )


# --------------------------------------------------------------------------- #
# HTTP endpoint
# --------------------------------------------------------------------------- #

async def example_status_endpoint(request: aiohttp.web.Request) -> aiohttp.web.Response:
    """
    Return a JSON payload describing the last ten task executions.

    The endpoint is registered under ``/api/plugins/example/status``.
    """
    core_logger.debug("Received status request from %s", request.remote)
    rows = []
    with sqlite3.connect(_DB_FILE) as conn:
        cursor = conn.execute(
            "SELECT id, start_ts, duration, result FROM task_runs ORDER BY start_ts DESC LIMIT 10"
        )
        rows = cursor.fetchall()

    history = [
        {
            "task_id": r[0],
            "start": r[1],
            "duration": r[2],
            "result": r[3],
        }
        for r in rows
    ]
    return aiohttp.web.json_response({"history": history})


# --------------------------------------------------------------------------- #
# Global state (populated by ``setup``)
# --------------------------------------------------------------------------- #

_global_event_bus: EventBus = EventBus()
_global_scheduler: Scheduler = Scheduler(event_bus=_global_event_bus)
_global_register_route: Callable[[str, Callable[[aiohttp.web.Request], Any]], None] = (
    lambda *_: None
)


# --------------------------------------------------------------------------- #
# Public API – registration helper
# --------------------------------------------------------------------------- #

def setup(
    event_bus: EventBus,
    scheduler: Scheduler,
    register_route: Callable[[str, Callable[[aiohttp.web.Request], Any]], None],
    dry_run: bool = False,
) -> None:
    """
    Initialise the example agent.

    This function registers a custom HTTP endpoint and a recurring CronJob.
    It must be called by the Engine after core components have been created.
    """
    global _global_event_bus, _global_scheduler, _global_register_route

    _global_event_bus = event_bus
    _global_scheduler = scheduler
    _global_register_route = register_route

    core_logger.info("Setting up ExampleAgent (dry_run=%s)", dry_run)

    # Ensure the SQLite database exists.
    _init_db()

    # Register the HTTP endpoint under a namespaced prefix.
    register_route("example", example_status_endpoint)

    # Create a CronJob that runs every minute.
    job = CronJob(
        id=str(uuid.uuid4()),
        name="example_task",
        schedule="* * * * *",  # every minute
        handler="examples.example_agent:example_task_handler",
        owner="core",
        retries=3,
        next_run=datetime.now(timezone.utc),
    )
    scheduler.schedule(job)

    core_logger.info(
        "ExampleAgent registration complete – endpoint '/api/plugins/example' and cron job scheduled."
    )