from __future__ import annotations

import datetime
import json
import logging
from typing import List, Optional

import pandas as pd
import streamlit as st

from src.core.engine import FailurePredictor, MaintenanceRecommender, PredictionError
from src.core.models import FailurePrediction, MachineTelemetry, MaintenanceTask
from src.ingest.collector import DataIngestor

logger = logging.getLogger(__name__)


class StreamlitApp:
    """
    Simple Streamlit dashboard that displays the latest telemetry,
    failure prediction, and any recommended maintenance tasks.
    """

    def __init__(self) -> None:
        self.ingestor = DataIngestor()
        self.predictor = FailurePredictor()
        self.recommender = MaintenanceRecommender()
        logger.info("StreamlitApp initialized.")

    def run(self) -> None:
        st.title("Brew Ops Dashboard")
        st.header("Live Machine Telemetry")

        telemetry_df = self.ingestor.get_latest_telemetry()
        if telemetry_df.empty:
            st.warning("No telemetry data available.")
            return

        st.dataframe(telemetry_df)

        try:
            prediction = self.predictor.predict(telemetry_df)
            st.subheader("Failure Prediction")
            st.json(prediction.dict())
        except PredictionError as exc:
            st.error(f"Prediction error: {exc}")
            return

        try:
            task = self.recommender.recommend(prediction)
            st.subheader("Recommended Maintenance Task")
            st.json(task.dict())
        except PredictionError as exc:
            st.info(f"No maintenance task generated: {exc}")
