from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from src.core.models import AggregatedReport, BudgetConfig

__all__ = ["BudgetEnforcer", "BudgetConfig"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _BudgetThresholds:
    """Internal representation of computed budget thresholds for a run."""

    hard_tokens: int
    soft_tokens: Optional[int] = None

    @classmethod
    def from_config(cls, config: BudgetConfig) -> "_BudgetThresholds":
        return cls(hard_tokens=config.hard_limit_tokens, soft_tokens=config.soft_limit_tokens)


class BudgetEnforcer:
    """Enforces token budgets against an :class:`AggregatedReport`.

    The ``enforce`` method returns ``True`` if the report is within the hard limit
    and ``False`` otherwise. It also logs a warning when the soft limit is
    exceeded.
    """

    def enforce(self, report: AggregatedReport, config: BudgetConfig) -> bool:
        thresholds = _BudgetThresholds.from_config(config)
        logger.debug(
            "Enforcing budget: hard=%s, soft=%s against total=%s",
            thresholds.hard_tokens,
            thresholds.soft_tokens,
            report.total_tokens,
        )
        if report.total_tokens > thresholds.hard_tokens:
            logger.error(
                "Hard token limit exceeded: %s > %s", report.total_tokens, thresholds.hard_tokens
            )
            return False
        if thresholds.soft_tokens is not None and report.total_tokens > thresholds.soft_tokens:
            logger.warning(
                "Soft token limit exceeded: %s > %s", report.total_tokens, thresholds.soft_tokens
            )
        return True
