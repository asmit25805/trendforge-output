import logging
from datetime import datetime
from typing import List, Optional

import polars as pl
from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from src.core.engine import PipelineEngine, ResultCache
from src.core.models import Job, JobStatus
from src.jobs.scheduler import JobScheduler

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

api_router = APIRouter()


class SubmitJobRequest(BaseModel):
    """Payload for creating a new back‑test job."""

    symbol: str = Field(..., description="Ticker symbol, e.g. '600519.XSHG'")
    start: datetime = Field(..., description="Start of the back‑test period")
    end: datetime = Field(..., description="End of the back‑test period")
    prompt: str = Field(..., description="Natural‑language description of the desired strategy")

    @validator("end")
    def end_must_be_after_start(cls, v, values):
        if "start" in values and v <= values["start"]:
            raise ValueError("end must be after start")
        return v


@api_router.post("/jobs", response_model=Job, status_code=status.HTTP_202_ACCEPTED)
async def submit_job(request: SubmitJobRequest):
    """Create a new job and schedule it for execution."""
    scheduler = JobScheduler()
    job = scheduler.create_job(
        symbol=request.symbol,
        start=request.start,
        end=request.end,
        prompt=request.prompt,
    )
    return job


@api_router.get("/jobs/{job_id}", response_model=Job)
async def get_job(job_id: str):
    scheduler = JobScheduler()
    job = scheduler.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@api_router.get("/jobs/{job_id}/result", response_model=Dict[str, Any])
async def get_result(job_id: str):
    cache = ResultCache()
    result = cache.load(job_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not available")
    return result
