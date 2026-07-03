import datetime
from typing import List

import pandas as pd
import pytest
from unittest.mock import MagicMock

from src.core.engine import FailurePredictor, MaintenanceRecommender, PredictionError
from src.core.models import FailurePrediction, MaintenanceTask, MachineTelemetry


@pytest.fixture
def sample_telemetry_df() -> pd.DataFrame:
    """Create a DataFrame with a single well‑formed telemetry record."""
    data = {
        "machine_id": ["machine-1"],
        "timestamp": [datetime.datetime.utcnow()],
        "temperature": [75.0],
        "pressure": [1.2],
        "flow_rate": [0.8],
        "voltage": [230.0],
        "current": [5.0],
    }
    return pd.DataFrame(data)


def test_failure_predictor_predict(sample_telemetry_df: pd.DataFrame) -> None:
    predictor = FailurePredictor()
    # Fit with the sample data to initialise internal models
    predictor.fit(sample_telemetry_df)

    prediction = predictor.predict(sample_telemetry_df)

    assert isinstance(prediction, FailurePrediction)
    assert 0.0 <= prediction.failure_probability <= 1.0
    assert prediction.machine_id == "machine-1"


def test_maintenance_recommender_above_threshold(sample_telemetry_df: pd.DataFrame) -> None:
    predictor = FailurePredictor()
    predictor.fit(sample_telemetry_df)
    prediction = predictor.predict(sample_telemetry_df)

    # Force a high probability to trigger recommendation
    prediction.failure_probability = 0.9
    recommender = MaintenanceRecommender(risk_threshold=0.5)

    task = recommender.recommend(prediction)

    assert isinstance(task, MaintenanceTask)
    assert task.machine_id == prediction.machine_id
    assert task.priority >= 1


def test_maintenance_recommender_below_threshold(sample_telemetry_df: pd.DataFrame) -> None:
    predictor = FailurePredictor()
    predictor.fit(sample_telemetry_df)
    prediction = predictor.predict(sample_telemetry_df)

    # Ensure low probability does not raise a task
    prediction.failure_probability = 0.1
    recommender = MaintenanceRecommender(risk_threshold=0.5)

    with pytest.raises(PredictionError):
        recommender.recommend(prediction)
