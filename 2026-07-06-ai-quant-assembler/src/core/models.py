import uuid
import json
import datetime
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, ClassVar

import polars as pl


class JobStatus(str, Enum):
    """Enumeration of possible job lifecycle states."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STALE = "stale"


@dataclass
class StrategySpec:
    """Specification of a generated trading strategy."""

    name: str
    expression: str
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


@dataclass
class MarketDataSlice:
    """Container for a slice of market data."""

    symbol: str
    start: datetime.datetime
    end: datetime.datetime
    data: pl.DataFrame


@dataclass
class BacktestResult:
    """Result of a backtest run."""

    equity_curve: pl.DataFrame
    metrics: Dict[str, Any]


@dataclass
class Alert:
    """Simple alert model used for notifications."""

    level: str
    message: str
    timestamp: datetime.datetime = field(default_factory=datetime.datetime.utcnow)


@dataclass
class Job:
    """Job metadata persisted in SQLite and used by the scheduler/engine."""

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: JobStatus = JobStatus.PENDING
    created_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    updated_at: datetime.datetime = field(default_factory=datetime.datetime.utcnow)
    spec: Optional[StrategySpec] = None
    result: Optional[BacktestResult] = None
