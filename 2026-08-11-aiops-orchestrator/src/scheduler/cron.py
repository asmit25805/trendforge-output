'''\
Cron scheduler – persistent cron jobs.
'''\

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, List

import aiosqlite
from croniter import croniter

from src.core.models import Event, EventBus

logger = logging.getLogger("aiops.scheduler")


@dataclass
class CronJob:
    """Definition of a cron job.

    *name* – identifier used for logging and event publishing.
    *schedule* – cron expression (e.g. "0 * * * *").
    *command* – callable executed when the job is due.
    """
    name: str
    schedule: str
    command: Callable[[], Any]


class Scheduler:
    """Runs cron jobs using a SQLite store for persistence.

    The scheduler stores the timestamp of the last execution for each job
    ensuring *exact‑once* semantics across restarts.
    """

    def __init__(self, event_bus: EventBus, db_path: Path = Path("scheduler.db")) -> None:
        self.event_bus = event_bus
        self.db_path = db_path
        self.jobs: List[CronJob] = []

    async def _init_db(self) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "CREATE TABLE IF NOT EXISTS job_runs (job TEXT PRIMARY KEY, last_run INTEGER)"
            )
            await db.commit()

    async def add_job(self, job: CronJob) -> None:
        self.jobs.append(job)
        logger.debug("Added cron job %s", job.name)

    async def _should_run(self, job: CronJob, now: datetime) -> bool:
        async with aiosqlite.connect(self.db_path) as db:
            cursor = await db.execute(
                "SELECT last_run FROM job_runs WHERE job = ?", (job.name,)
            )
            row = await cursor.fetchone()
            last_run_ts = row[0] if row else None
        itr = croniter(job.schedule, now)
        next_run = itr.get_next(datetime)
        if last_run_ts is not None:
            last_run = datetime.fromtimestamp(last_run_ts, tz=timezone.utc)
            if last_run >= next_run:
                return False
        return next_run <= now

    async def _record_run(self, job: CronJob, run_time: datetime) -> None:
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO job_runs (job, last_run) VALUES (?, ?)",
                (job.name, int(run_time.timestamp())),
            )
            await db.commit()

    async def start(self) -> None:
        await self._init_db()
        while True:
            now = datetime.now(timezone.utc)
            for job in self.jobs:
                if await self._should_run(job, now):
                    try:
                        result = job.command()
                        self.event_bus.publish(Event(name=job.name, payload={"result": result}))
                        await self._record_run(job, now)
                        logger.info("Executed cron job %s", job.name)
                    except Exception as exc:
                        logger.error("Cron job %s failed: %s", job.name, exc)
            await asyncio.sleep(60)


class CronSDK:
    """Helper class for plugins to schedule cron jobs.
    """

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler

    async def schedule(self, job: CronJob) -> None:
        await self.scheduler.add_job(job)
