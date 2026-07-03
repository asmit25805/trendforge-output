from __future__ import annotations

import datetime as _dt
import logging
from typing import List, Dict, Any, Optional

import pandas as pd
import numpy as np
from prophet import Prophet
from xgboost import XGBClassifier

from src.core.models import FailurePrediction, MaintenanceTask, MachineTelemetry

logger = logging.getLogger(__name__)


class PredictionError(Exception):
    """Raised when model inference cannot be performed due to invalid input or internal failure."""
    pass


class FailurePredictor:
    """
    Predicts the probability of a coffee‑machine failure using a hybrid
    Prophet + XGBoost model.
    """

    def __init__(self) -> None:
        # Simple placeholder models; in a real system these would be trained
        self.prophet_model = Prophet()
        self.xgb_model = XGBClassifier(use_label_encoder=False, eval_metric="logloss")
        logger.info("FailurePredictor initialized with placeholder models.")

    def fit(self, telemetry: pd.DataFrame) -> None:
        """
        Fit the internal models on historical telemetry data.
        """
        if telemetry.empty:
            raise PredictionError("Telemetry data is empty; cannot fit models.")
        # Fit Prophet on the target time series (e.g., temperature)
        prophet_df = telemetry.rename(columns={"timestamp": "ds", "temperature": "y"})[["ds", "y"]]
        self.prophet_model.fit(prophet_df)
        # Fit XGBoost on engineered features
        X = telemetry.drop(columns=["machine_id", "timestamp"])
        y = (telemetry["temperature"] > 80).astype(int)  # dummy label
        self.xgb_model.fit(X, y)
        logger.info("Models fitted on telemetry data.")

    def predict(self, telemetry: pd.DataFrame) -> FailurePrediction:
        """
        Produce a failure prediction for the most recent telemetry record.
        """
        if telemetry.empty:
            raise PredictionError("No telemetry data provided for prediction.")
        latest = telemetry.iloc[-1]
        # Simple heuristic combining both models
        prophet_forecast = self.prophet_model.predict(
            pd.DataFrame({"ds": [latest["timestamp"]]})
        )["yhat"].iloc[0]
        xgb_prob = self.xgb_model.predict_proba(
            latest.drop(labels=["machine_id", "timestamp"]).to_frame().T
        )[0, 1]

        # Combine probabilities (placeholder logic)
        combined_prob = (prophet_forecast / 100.0 + xgb_prob) / 2.0
        combined_prob = max(0.0, min(1.0, combined_prob))

        prediction = FailurePrediction(
            machine_id=latest["machine_id"],
            prediction_time=_dt.datetime.utcnow(),
            failure_probability=combined_prob,
            risk_score=combined_prob * 100,
        )
        logger.debug("Generated prediction: %s", prediction)
        return prediction


class MaintenanceRecommender:
    """
    Generates a maintenance task based on a failure prediction.
    """

    def __init__(self, risk_threshold: float = 0.7) -> None:
        self.risk_threshold = risk_threshold
        logger.info("MaintenanceRecommender initialized with risk threshold %.2f", risk_threshold)

    def recommend(self, prediction: FailurePrediction) -> MaintenanceTask:
        """
        Return a MaintenanceTask if the prediction risk exceeds the threshold.
        """
        if prediction.failure_probability < self.risk_threshold:
            raise PredictionError(
                f"Failure probability {prediction.failure_probability:.2f} below threshold."
            )
        task = MaintenanceTask(
            machine_id=prediction.machine_id,
            task_id=f"task-{prediction.machine_id}-{int(_dt.datetime.utcnow().timestamp())}",
            scheduled_time=_dt.datetime.utcnow() + _dt.timedelta(hours=2),
            description="High failure risk detected; schedule preventive maintenance.",
            priority=int(prediction.failure_probability * 5),
        )
        logger.debug("Created maintenance task: %s", task)
        return task
