from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional

from sqlalchemy import Column, DateTime, String, create_engine, select
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from flowbridge.core.models import (
    PipelineSpec,
    RunStatus,
    RunState,
)

# ---------------------------------------------------------------------------
# Simple in‑memory SQLite setup for demonstration purposes
# ---------------------------------------------------------------------------

Base = declarative_base()

class PipelineRun(Base):
    __tablename__ = "pipeline_runs"
    id = Column(String, primary_key=True)
    pipeline_id = Column(String, nullable=False)
    state = Column(String, nullable=False)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)

engine = create_engine("sqlite:///:memory:", echo=False, future=True)
Base.metadata.create_all(engine)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

# ---------------------------------------------------------------------------
# Core engine implementation
# ---------------------------------------------------------------------------

@dataclass
class PipelineEngine:
    """Manages execution of a PipelineSpec.

    The engine stores run metadata in an SQLite database and provides a simple
    asynchronous execution model. In a real system this would be replaced by a
    more robust scheduler and persistence layer.
    """

    pipeline: PipelineSpec
    db: Session = field(default_factory=SessionLocal)

    async def run(self) -> RunStatus:
        """Execute the pipeline respecting the DAG order.

        Returns
        -------
        RunStatus
            Final status of the pipeline execution.
        """
        run_id = str(uuid.uuid4())
        now = datetime.utcnow()
        self.db.add(
            PipelineRun(
                id=run_id,
                pipeline_id=self.pipeline.id,
                state=RunState.RUNNING,
                started_at=now,
            )
        )
        self.db.commit()
        logger = logging.getLogger(__name__)
        logger.info("Starting pipeline %s", self.pipeline.id)
        # Very naive DAG execution: iterate nodes in the order they appear.
        for node in self.pipeline.nodes:
            await asyncio.sleep(0)  # placeholder for real async work
        finished = datetime.utcnow()
        self.db.execute(
            select(PipelineRun).where(PipelineRun.id == run_id)
        ).scalar_one().state = RunState.SUCCESS
        self.db.commit()
        return RunStatus(
            pipeline_id=self.pipeline.id,
            state=RunState.SUCCESS,
            started_at=now,
            finished_at=finished,
        )

# ---------------------------------------------------------------------------
# Convenience functions exported by the module
# ---------------------------------------------------------------------------

def run_pipeline(pipeline: PipelineSpec) -> RunStatus:
    """Create a :class:`PipelineEngine` and run the supplied pipeline.

    This helper is used by the CLI and tests.
    """
    engine = PipelineEngine(pipeline)
    return asyncio.run(engine.run())


def pipeline_status(pipeline_id: str) -> Optional[RunStatus]:
    """Query the SQLite store for the latest run status of *pipeline_id*.
    """
    with SessionLocal() as session:
        stmt = select(PipelineRun).where(PipelineRun.pipeline_id == pipeline_id).order_by(PipelineRun.started_at.desc())
        result = session.execute(stmt).scalars().first()
        if result is None:
            return None
        return RunStatus(
            pipeline_id=result.pipeline_id,
            state=RunState(result.state),
            started_at=result.started_at,
            finished_at=result.finished_at,
        )
