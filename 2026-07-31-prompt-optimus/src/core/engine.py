from __future__ import annotations

import json
import logging
import math
import random
import time
import uuid
from pathlib import Path
from typing import Any, Callable, List, Mapping, Sequence

import sqlalchemy as sa
import yaml
from pydantic import ValidationError

from src.core.models import (
    ConfigurationError,
    EvaluationError,
    OptimizationConfig,
    PromptCandidate,
    TrialResult,
)

logger = logging.getLogger(__name__)


def _load_config(path: Path) -> OptimizationConfig:
    """Load and validate a YAML optimisation manifest.

    Parameters
    ----------
    path: Path
        Path to the YAML file.

    Returns
    -------
    OptimizationConfig
        Validated configuration object.
    """
    try:
        raw = yaml.safe_load(path.read_text())
        return OptimizationConfig(**raw)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigurationError(f"Failed to parse configuration: {exc}") from exc


def _exponential_backoff(attempt: int, factor: float = 0.5, cap: float = 30.0) -> float:
    """Calculate a back‑off delay for retry logic.

    The delay grows exponentially with the number of attempts but is capped
    to avoid excessively long sleeps.
    """
    delay = min(factor * (2 ** attempt), cap)
    jitter = random.uniform(0, delay * 0.1)
    return delay + jitter


def _safe_fallback_prompt(candidate: PromptCandidate) -> PromptCandidate:
    """Return a minimal fallback prompt if generation failed.

    This ensures the optimisation loop can continue even when a driver
    raises an unexpected exception.
    """
    fallback = replace(candidate, prompt="[fallback prompt]", metadata={})
    return fallback


class PromptEngine:
    """Core engine that runs the optimisation loop.

    It coordinates loading the configuration, retrieving the appropriate LLM
    driver, generating candidates, evaluating them, and persisting results.
    """

    def __init__(self, config: OptimizationConfig, logger: logging.Logger | None = None):
        self.config = config
        self.logger = logger or logging.getLogger(__name__)
        from src.plugins.registry import PluginRegistry

        self.registry = PluginRegistry.get_instance()
        self.driver = self.registry.get_driver(config.driver)

    def _run_trial(self, trial_num: int) -> TrialResult:
        # Generate a prompt candidate
        try:
            candidate = self.driver.generate_prompt(trial_num)
        except Exception as exc:
            self.logger.warning("Driver generation failed (trial %s): %s", trial_num, exc)
            candidate = PromptCandidate(prompt="[error]", metadata={})
            candidate = _safe_fallback_prompt(candidate)

        # Evaluate metrics – placeholder implementation
        metrics: Dict[str, float] = {}
        success = True
        error_msg = None
        for metric_name in self.config.metrics:
            try:
                # In a real implementation each metric would be a callable.
                # Here we simulate a metric by returning a random float.
                metrics[metric_name] = random.random()
            except Exception as exc:
                success = False
                error_msg = str(exc)
                break

        return TrialResult(
            candidate_id=candidate.id,
            metrics=metrics,
            success=success,
            error=error_msg,
        )

    def run(self) -> List[TrialResult]:
        results: List[TrialResult] = []
        for i in range(self.config.max_trials):
            attempt = 0
            while True:
                try:
                    result = self._run_trial(i)
                    results.append(result)
                    break
                except EvaluationError as exc:
                    self.logger.error("Evaluation failed on trial %s: %s", i, exc)
                    if attempt >= 5:
                        raise
                    delay = _exponential_backoff(attempt, self.config.backoff_factor)
                    self.logger.info("Retrying after %.2f seconds", delay)
                    time.sleep(delay)
                    attempt += 1
        return results


def run_optim(config_path: Path) -> None:
    """Convenient entry‑point used by the CLI.

    It loads the configuration, creates a ``PromptEngine`` instance and runs
    the optimisation loop, persisting the results to JSON files under a
    ``results/`` directory.
    """
    config = _load_config(config_path)
    engine = PromptEngine(config)
    results = engine.run()

    output_dir = Path("results")
    output_dir.mkdir(exist_ok=True)
    for res in results:
        out_path = output_dir / f"{res.candidate_id}.json"
        out_path.write_text(json.dumps(res.as_dict(), indent=2))
