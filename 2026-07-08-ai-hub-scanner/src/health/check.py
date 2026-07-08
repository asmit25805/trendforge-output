from __future__ import annotations

import logging
from datetime import datetime
from typing import List, Optional

import httpx
from fastapi import FastAPI, HTTPException, Query, status
from pydantic import BaseModel, Field, ValidationError

from src.core.models import Leaderboard, RepositoryInfo, ToolEntry
from src.cache.store import CacheStore

logger = logging.getLogger(__name__)
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
logger.setLevel(logging.INFO)

app = FastAPI(title="ai-hub-scanner health endpoint")
cache = CacheStore()


class HealthResponse(BaseModel):
    status: str = Field(..., description="Overall health status")
    last_run: Optional[datetime] = Field(None, description="Timestamp of the last aggregation run")
    repo_count: int = Field(0, description="Number of repositories scanned in the last run")
    error_count: int = Field(0, description="Number of errors encountered during the last run")


@app.get("/health", response_model=HealthResponse)
async def health_endpoint():
    """Return a simple health check payload.

    The endpoint reads the cached leaderboard (if any) and reports basic metrics.
    """
    leaderboard: Optional[Leaderboard] = cache.get_leaderboard()
    if leaderboard is None:
        return HealthResponse(status="no_data", repo_count=0, error_count=0)
    return HealthResponse(
        status="ok",
        last_run=leaderboard.generated_at,
        repo_count=len(leaderboard.entries),
        error_count=0,
    )
