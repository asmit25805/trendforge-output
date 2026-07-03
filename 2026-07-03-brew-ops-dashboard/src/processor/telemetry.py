from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List

import numpy as np
import pandas as pd

from src.core.models import MachineTelemetry

logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


class TelemetryProcessor:
    """
    Cleans, normalises, and enriches raw telemetry data.
    """

    def __init__(self) -> None:
        logger.info("TelemetryProcessor initialized.")

    def clean(self, records: List[MachineTelemetry]) -> pd.DataFrame:
        """
        Convert a list of MachineTelemetry objects into a cleaned DataFrame.
        """
        if not records:
            logger.warning("No telemetry records provided to clean.")
            return pd.DataFrame()

        df = pd.DataFrame([r.dict() for r in records])
        # Example cleaning steps
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
        df = df.dropna(subset=["temperature", "pressure", "flow_rate"])
        df["temperature"] = df["temperature"].astype(float)
        df["pressure"] = df["pressure"].astype(float)
        df["flow_rate"] = df["flow_rate"].astype(float)
        logger.debug("Cleaned telemetry DataFrame with %d rows.", len(df))
        return df
