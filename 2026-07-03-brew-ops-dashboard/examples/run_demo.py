from __future__ import annotations

import datetime
import json
import logging
import random
import sys
import time
from pathlib import Path
from typing import List

import pandas as pd

from src.core.engine import FailurePredictor, MaintenanceRecommender, PredictionError
from src.core.models import MachineTelemetry, FailurePrediction, MaintenanceTask
from src.ingest.collector import DataIngestor
from src.processor.telemetry import TelemetryProcessor

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)


def _exponential_backoff(
    func,
    *args,
    max_attempts: int = 5,
    base_delay: float = 0.5,
    cap_delay: float = 8.0,
    **kwargs,
):
    """Execute ``func`` with exponential back‑off on transient exceptions."""
    for attempt in range(max_attempts):
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Attempt %d/%d failed for %s: %s",
                attempt + 1,
                max_attempts,
                func.__name__,
                exc,
            )
            if attempt == max_attempts - 1:
                raise
            time.sleep(min(cap_delay, base_delay * (2 ** attempt)))


def _generate_synthetic_telemetry(num_machines: int = 5, records_per_machine: int = 10) -> List[MachineTelemetry]:
    """Create a list of realistic MachineTelemetry objects for demo purposes."""
    telemetry: List[MachineTelemetry] = []
    now = datetime.datetime.utcnow().replace(tzinfo=datetime.timezone.utc)

    for i in range(num_machines):
        machine_id = f"machine-{i+1:03d}"
        for r in range(records_per_machine):
            ts = now - datetime.timedelta(minutes=records_per_machine - r)
            temperature = random.uniform(78.0, 102.0)  # intentional out‑of‑range values to test cleaning
            pressure = random.uniform(-2.0, 18.0)
            flow = random.uniform(-1.0, 6.0)
            error_code = random.choice([None, 0, 1, 2]) if random.random() < 0.1 else None

            telemetry.append(
                MachineTelemetry(
                    machine_id=machine_id,
                    timestamp=ts,
                    temperature_c=temperature,
                    pressure_bar=pressure,
                    flow_rate_ml_s=flow,
                    error_code=error_code,
                )
            )
    return telemetry


def _telemetry_to_dataframe(telemetry: List[MachineTelemetry]) -> pd.DataFrame:
    """Convert a list of MachineTelemetry into a pandas DataFrame."""
    records = [t.model_dump() for t in telemetry]
    df = pd.DataFrame(records)
    # Ensure timestamp column is a datetime type for downstream processing
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df


def main() -> None:
    """Run a full demo: ingest, process, predict, and recommend maintenance."""
    logger.info("=== Brew‑Ops Dashboard Demo ===")

    # 1️⃣ Simulate ingestion – in a real deployment this would be MQTT/HTTP.
    logger.info("Generating synthetic telemetry...")
    raw_telemetry = _generate_synthetic_telemetry()

    # 2️⃣ Store raw telemetry using DataIngestor (no‑op store for demo).
    logger.info("Initialising DataIngestor (store is mocked for demo)...")
    ingestor = DataIngestor(
        influx_url="http://localhost:8086",
        influx_token="demo-token",
        influx_org="demo-org",
        influx_bucket="demo-bucket",
        max_retries=3,
    )

    # Monkey‑patch the store method to avoid external dependencies.
    def _noop_store(self, records: List[MachineTelemetry]) -> None:  # type: ignore[override]
        logger.debug("Mock store called with %d records", len(records))

    ingestor.store = _noop_store.__get__(ingestor, DataIngestor)  # bind method

    # Store the generated telemetry.
    _exponential_backoff(ingestor.store, raw_telemetry)

    # 3️⃣ Clean and feature‑engineer the telemetry.
    logger.info("Cleaning telemetry...")
    processor = TelemetryProcessor(lag_window=2, roll_window=4)

    cleaned = [processor.clean(rec) for rec in raw_telemetry]
    df_clean = _telemetry_to_dataframe(cleaned)
    logger.info("Creating features...")
    df_features = processor.feature_engineer(df_clean)

    # 4️⃣ Predict failures.
    logger.info("Running FailurePredictor...")
    predictor = FailurePredictor()
    # For demo we skip training and rely on a stubbed model inside the predictor.
    try:
        prediction: FailurePrediction = predictor.predict(df_features)
    except PredictionError as exc:
        logger.error("Prediction failed: %s", exc)
        sys.exit(1)

    logger.info(
        "Prediction for %s at %s – failure probability %.2f%%",
        prediction.machine_id,
        prediction.prediction_time.isoformat(),
        prediction.failure_prob * 100,
    )

    # 5️⃣ Recommend maintenance based on the prediction.
    logger.info("Generating maintenance recommendation...")
    recommender = MaintenanceRecommender()
    task: MaintenanceTask = recommender.recommend(prediction)

    # 6️⃣ Print a concise summary.
    summary = {
        "machine_id": task.machine_id,
        "task_type": task.task_type,
        "priority": task.priority,
        "scheduled_at": task.scheduled_at.isoformat(),
        "required_parts": task.required_parts,
    }
    logger.info("MaintenanceTask summary:\n%s", json.dumps(summary, indent=2))

    logger.info("=== Demo completed successfully ===")


if __name__ == "__main__":
    main()