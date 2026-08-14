from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from src.core.models import AggregatedReport, TokenRecord

logger = logging.getLogger(__name__)


class CostAggregator:
    """Collects :class:`TokenRecord` objects and produces an :class:`AggregatedReport`.

    The aggregator groups records by provider and model, summing prompt and
    completion tokens. ``generate_report`` returns a single ``AggregatedReport``
    that represents the overall usage for the CI run.
    """

    def __init__(self) -> None:
        self._records: List[TokenRecord] = []
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None

    def add_record(self, record: TokenRecord) -> None:
        """Add a single :class:`TokenRecord` to the aggregation.

        The method updates the overall start/end timestamps based on the record's
        ``timestamp`` field.
        """
        self._records.append(record)
        ts = record.timestamp
        if self._start_time is None or ts < self._start_time:
            self._start_time = ts
        if self._end_time is None or ts > self._end_time:
            self._end_time = ts
        logger.debug("Added TokenRecord %s", record.json())

    def generate_report(self) -> AggregatedReport:
        """Create an :class:`AggregatedReport` from the collected records.

        If no records have been added, a ``ValueError`` is raised.
        """
        if not self._records:
            raise ValueError("No TokenRecord objects have been added to the aggregator")

        # Group by provider and model – for simplicity we produce a single report
        # that aggregates across all providers/models.
        total_prompt = sum(r.prompt_tokens for r in self._records)
        total_completion = sum(r.completion_tokens for r in self._records)
        total = total_prompt + total_completion

        # Use the provider/model of the first record for identification; callers
        # can extend this to produce multiple reports if needed.
        first = self._records[0]
        report = AggregatedReport(
            provider=first.provider,
            model=first.model,
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            total_tokens=total,
            start_time=self._start_time or datetime.utcnow(),
            end_time=self._end_time or datetime.utcnow(),
        )
        logger.info("Generated AggregatedReport: %s", report.json())
        return report


__all__ = ["CostAggregator"]
