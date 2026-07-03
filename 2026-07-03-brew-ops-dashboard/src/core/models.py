from __future__ import annotations

import datetime as _dt
from typing import List, Optional, Sequence, Dict, Any

import pandas as pd
from pydantic import BaseModel, Field, validator, root_validator


class MachineTelemetry(BaseModel):
    """
    Raw telemetry record emitted by a coffee machine.
    """

    machine_id: str = Field(..., description="Unique identifier of the coffee machine")
    timestamp: _dt.datetime = Field(..., description="Timestamp of the telemetry reading")
    temperature: float = Field(..., description="Current temperature in Celsius")
    pressure: float = Field(..., description="Current pressure in bar")
    flow_rate: float = Field(..., description="Water flow rate in ml/s")
    voltage: Optional[float] = Field(None, description="Supply voltage")
    current: Optional[float] = Field(None, description="Supply current")


class FailurePrediction(BaseModel):
    """
    Result of a failure risk prediction for a specific machine.
    """

    machine_id: str = Field(..., description="Identifier of the machine")
    prediction_time: _dt.datetime = Field(..., description="Time when the prediction was made")
    failure_probability: float = Field(..., ge=0.0, le=1.0, description="Probability of failure")
    risk_score: float = Field(..., description="Derived risk score used for recommendation")


class MaintenanceTask(BaseModel):
    """
    Recommended maintenance action derived from a failure prediction.
    """

    machine_id: str = Field(..., description="Identifier of the machine")
    task_id: str = Field(..., description="Unique identifier for the maintenance task")
    scheduled_time: _dt.datetime = Field(..., description="When the maintenance should be performed")
    description: str = Field(..., description="Human‑readable description of the task")
    priority: int = Field(..., ge=1, le=5, description="Priority level (1 = low, 5 = critical)")
