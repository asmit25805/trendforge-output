import os
import shutil
import tempfile
from datetime import datetime, timedelta

import polars as pl
import pytest

from src.core.engine import PipelineEngine, ResultCache
from src.core.models import Job, JobStatus, StrategySpec
from src.jobs.scheduler import JobScheduler
from src.plugins.manager import PluginManager, DataProviderPlugin


class DummyPlugin(DataProviderPlugin):
    """Simple plugin that returns a deterministic DataFrame."""

    def fetch(self, symbol: str, start: datetime, end: datetime) -> pl.DataFrame:
        dates = pl.date_range(start, end, interval="1d", eager=True)
        df = pl.DataFrame(
            {
                "open": [1.0] * len(dates),
                "high": [2.0] * len(dates),
                "low": [0.5] * len(dates),
                "close": [1.5] * len(dates),
                "volume": [1000] * len(dates),
            },
            schema={
                "open": pl.Float64,
                "high": pl.Float64,
                "low": pl.Float64,
                "close": pl.Float64,
                "volume": pl.Int64,
            },
        )
        df = df.with_columns(pl.Series("date", dates))
        return df

    def capabilities(self) -> set[str]:
        return {"daily"}


class FlakyPlugin(DataProviderPlugin):
    """Plugin that fails twice before succeeding, simulating a transient error."""

    def __init__(self) -> None:
        self._attempt = 0

    def fetch(self, symbol: str, start: datetime, end: datetime) -> pl.DataFrame:
        self._attempt += 1
        if self._attempt < 3:
            raise RuntimeError("Transient network glitch")
        return DummyPlugin().fetch(symbol, start, end)

    def capabilities(self) -> set[str]:
        return {"daily"}


@pytest.fixture(autouse=True)
def clean_environment():
    """Remove any persisted SQLite DB and cache files before each test."""
    db_path = Path("./jobs.db")
    if db_path.is_file():
        db_path.unlink()
    cache_dir = Path("./cache")
    if cache_dir.is_dir():
        shutil.rmtree(cache_dir)
    yield
    if db_path.is_file():
        db_path.unlink()
    if cache_dir.is_dir():
        shutil.rmtree(cache_dir)


def _create_engine_with_plugins(plugins: dict[str, type[DataProviderPlugin]]) -> tuple[PipelineEngine, JobScheduler]:
    scheduler = JobScheduler()
    plugin_manager = PluginManager()
    cache = ResultCache()
    engine = PipelineEngine(scheduler=scheduler, plugin_manager=plugin_manager, cache=cache)

    for name, cls in plugins.items():
        plugin_manager.register(name=name, entry_point=f"{cls.__module__}.{cls.__name__}", plugin_cls=cls)

    return engine, scheduler


def _submit_job(scheduler: JobScheduler, payload: dict) -> str:
    return scheduler.create(job_type="pipeline", payload=payload)


def test_engine_successful_job_completes():
    engine, scheduler = _create_engine_with_plugins({"dummy": DummyPlugin})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["dummy"],
    }
    job_id = _submit_job(scheduler, payload)

    engine.run_job(job_id)

    job_row = scheduler._conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job_row is not None
    assert job_row["status"] == JobStatus.SUCCESS.value


def test_engine_stores_backtest_result():
    engine, scheduler = _create_engine_with_plugins({"dummy": DummyPlugin})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["dummy"],
    }
    job_id = _submit_job(scheduler, payload)

    engine.run_job(job_id)

    cache = ResultCache()
    df = cache.load(job_id)
    assert isinstance(df, pl.DataFrame)
    assert set(df.columns) >= {"equity", "drawdown"}
    assert len(df) > 0


def test_engine_progress_reporting():
    engine, scheduler = _create_engine_with_plugins({"dummy": DummyPlugin})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["dummy"],
    }
    job_id = _submit_job(scheduler, payload)

    # Run in a separate thread to allow progress polling while job executes
    import threading

    thread = threading.Thread(target=engine.run_job, args=(job_id,))
    thread.start()

    # Poll a few times; the engine should report intermediate stages before completion
    for _ in range(5):
        progress = engine.track_progress(job_id)
        assert "stage" in progress
        assert "percent" in progress
        assert 0 <= progress["percent"] <= 100
        if progress["percent"] == 100:
            break

    thread.join()
    final_progress = engine.track_progress(job_id)
    assert final_progress["percent"] == 100
    assert final_progress["stage"].lower() in {"completed", "success"}


def test_engine_fatal_error_marks_failed():
    class FatalPlugin(DataProviderPlugin):
        def fetch(self, symbol: str, start: datetime, end: datetime) -> pl.DataFrame:
            raise ValueError("Missing mandatory column")

        def capabilities(self) -> set[str]:
            return {"daily"}

    engine, scheduler = _create_engine_with_plugins({"fatal": FatalPlugin})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["fatal"],
    }
    job_id = _submit_job(scheduler, payload)

    engine.run_job(job_id)

    job_row = scheduler._conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job_row is not None
    assert job_row["status"] == JobStatus.FAILED.value


def test_engine_unknown_plugin_raises_error():
    engine, scheduler = _create_engine_with_plugins({})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["nonexistent"],
    }
    job_id = _submit_job(scheduler, payload)

    with pytest.raises(RuntimeError):
        engine.run_job(job_id)


def test_engine_retries_on_transient_error():
    engine, scheduler = _create_engine_with_plugins({"flaky": FlakyPlugin})
    payload = {
        "symbols": ["000001.SZ"],
        "start": (datetime.utcnow() - timedelta(days=5)).isoformat(),
        "end": datetime.utcnow().isoformat(),
        "strategy": {
            "name": "test",
            "description": "",
            "entry_rule": "close > 1",
            "exit_rule": "close < 1",
            "parameters": {},
        },
        "plugins": ["flaky"],
    }
    job_id = _submit_job(scheduler, payload)

    engine.run_job(job_id)

    job_row = scheduler._conn.execute("SELECT status FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job_row is not None
    assert job_row["status"] == JobStatus.SUCCESS.value
    # Verify that the flaky plugin succeeded after retries
    cache = ResultCache()
    df = cache.load(job_id)
    assert isinstance(df, pl.DataFrame)
    assert "equity" in df.columns