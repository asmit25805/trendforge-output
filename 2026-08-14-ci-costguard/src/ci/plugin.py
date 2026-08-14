from __future__ import annotations

import json
import logging
import sys
import traceback
from dataclasses import asdict
from pathlib import Path
from typing import Iterable, List

import yaml

from src.core.aggregator import CostAggregator
from src.core.alert import AlertDispatcher, AlertMessage
from src.core.budget import BudgetEnforcer, BudgetConfig
from src.core.parser import parse_file, register_parser, ProviderParser
from src.core.models import CIContext, TokenRecord

logger = logging.getLogger(__name__)


def run(ci_context: CIContext, log_paths: Iterable[Path], budget_cfg: BudgetConfig) -> int:
    """Entry point used by CI pipelines.

    * ``ci_context`` – Information about the CI run.
    * ``log_paths`` – Iterable of paths to provider log files.
    * ``budget_cfg`` – Token budget configuration.

    The function returns ``0`` on success and ``1`` if the hard budget limit is
    exceeded.
    """
    try:
        aggregator = CostAggregator()
        for path in log_paths:
            for record in parse_file(path):
                if isinstance(record, TokenRecord):
                    aggregator.add_record(record)
        report = aggregator.generate_report()
        logger.info("Aggregated token usage: %s", report.json())

        enforcer = BudgetEnforcer()
        if not enforcer.enforce(report, budget_cfg):
            dispatcher = AlertDispatcher()
            alert = AlertMessage(
                title="Token budget exceeded",
                body=f"Report: {report.json()}",
                severity="error",
            )
            dispatcher.dispatch(alert)
            dispatcher.close()
            return 1
        return 0
    except Exception as exc:
        logger.error("Unexpected error in CI plugin: %s", exc)
        traceback.print_exc(file=sys.stderr)
        return 1
