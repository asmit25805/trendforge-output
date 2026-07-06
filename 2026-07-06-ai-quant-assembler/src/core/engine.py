import datetime
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import httpx
import openai
import polars as pl

from src.core.models import Job, JobStatus, StrategySpec, MarketDataSlice, BacktestResult
from src.jobs.scheduler import JobScheduler
from src.ai.strategy_generator import StrategyGenerator

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ResultCache:
    """Simple file‑based cache for back‑test results.

    Results are stored as Parquet files under a ``cache/`` directory keyed by
    the job identifier.
    """

    def __init__(self, base_dir: Path = Path("./cache")) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, job_id: str) -> Path:
        return self.base_dir / f"{job_id}.parquet"

    def save(self, job_id: str, df: pl.DataFrame) -> None:
        self._path(job_id).write_parquet(df)
        logger.debug("Saved result for %s", job_id)

    def load(self, job_id: str) -> Optional[Dict[str, Any]]:
        p = self._path(job_id)
        if not p.is_file():
            return None
        df = pl.read_parquet(p)
        return {"equity_curve": df.to_dict(as_series=False)}


class PipelineEngine:
    """Orchestrates data fetching, strategy generation and back‑testing.

    The engine is deliberately synchronous; the surrounding ``JobScheduler``
    runs each job in its own thread.
    """

    def __init__(self) -> None:
        self.plugin_registry = None  # Filled lazily via PluginRegistry if needed
        self.strategy_generator = StrategyGenerator()
        self.result_cache = ResultCache()

    def run_job(self, job_id: str, symbol: str, start: datetime.datetime, end: datetime.datetime, prompt: str) -> None:
        logger.info("Running job %s for %s", job_id, symbol)
        # 1. Generate strategy
        spec = self.strategy_generator.generate(prompt)
        # 2. Fetch market data (simplified – use a dummy DataFrame)
        dates = pl.date_range(start, end, interval="1d", eager=True)
        prices = pl.Series("price", [100 + i * 0.1 for i in range(len(dates))])
        data = pl.DataFrame([dates, prices]).rename({"date": "timestamp"})
        market_slice = MarketDataSlice(symbol=symbol, start=start, end=end, data=data)
        # 3. Back‑test – very naive cumulative return
        equity = (data["price"] / data["price"][0]).alias("equity")
        equity_curve = pl.DataFrame({"timestamp": data["timestamp"], "equity": equity})
        result = BacktestResult(equity_curve=equity_curve, metrics={"cagr": equity[-1] - 1})
        # 4. Persist result
        self.result_cache.save(job_id, equity_curve)
        # 5. Update job status in SQLite (handled by JobScheduler directly)
        scheduler = JobScheduler()
        job = scheduler.get_job(job_id)
        if job:
            job.status = JobStatus.SUCCESS
            job.result = result
            scheduler._persist(job)
        logger.info("Job %s completed successfully", job_id)

    def run_pipeline(self, symbol: str, start: datetime.datetime, end: datetime.datetime, prompt: str) -> Tuple[str, ResultCache]:
        """Convenient helper used by the FastAPI endpoint.

        Returns the generated job identifier and a reference to the cache so the
        caller can retrieve the result later.
        """
        scheduler = JobScheduler()
        job = scheduler.create_job(symbol=symbol, start=start, end=end, prompt=prompt)
        return job.id, self.result_cache
