import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, List

import yaml

from src.core.engine import PromptEngine
from src.core.models import (
    ConfigurationError,
    EvaluationError,
    OptimizationConfig,
    PromptCandidate,
    TrialResult,
)
from src.reporters.logger import get_logger


def _discover_config(start_dir: Path) -> Path:
    """
    Walk up from *start_dir* looking for ``optim-plan.yaml``.
    Returns the first match or raises ``ConfigurationError``.
    """
    current = start_dir.resolve()
    for _ in range(10):
        candidate = current / "optim-plan.yaml"
        if candidate.is_file():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    raise ConfigurationError("optim-plan.yaml not found in any parent directory")


def load_optimization_config(cfg_path: Path) -> OptimizationConfig:
    """
    Load a YAML configuration file and instantiate ``OptimizationConfig``.
    """
    try:
        with cfg_path.open("r", encoding="utf-8") as f:
            raw_cfg = yaml.safe_load(f) or {}
        return OptimizationConfig(**raw_cfg)
    except Exception as exc:
        raise ConfigurationError(f"Failed to parse configuration at {cfg_path}") from exc


def run_optim(
    config: OptimizationConfig,
    max_trials: int | None = None,
    json_log: Path | None = None,
    sqlite_log: Path | None = None,
) -> List[TrialResult]:
    """
    Execute the optimisation loop.

    Returns a list of ``TrialResult`` objects in the order they were produced.
    """
    logger = get_logger(__name__)

    # Apply optional override
    if max_trials is not None:
        config.max_trials = max_trials

    engine = PromptEngine(config)

    # Register a simple fallback driver if the user has not added any.
    # This ensures the example works out‑of‑the‑box.
    if not engine.registry._drivers:  # type: ignore[attr-defined]
        from src.plugins.registry import BaseLLMDriver, PluginRegistry

        class EchoDriver(BaseLLMDriver):
            """Echoes the ``seed`` and ``trial_index`` as a prompt."""

            def name(self) -> str:
                return "echo"

            def generate_prompt(self, context: dict[str, Any]) -> str:
                return f"seed={context.get('seed')}, trial={context.get('trial_index')}"

        engine.registry.register("echo", EchoDriver())

    results: List[TrialResult] = []

    trial_counter = 0
    while trial_counter < config.max_trials:
        logger.info("=== Trial %d / %d ===", trial_counter + 1, config.max_trials)

        # -----------------------------------------------------------------
        # Prompt generation
        # -----------------------------------------------------------------
        context: dict[str, Any] = {
            "seed": config.seed,
            "trial_index": trial_counter,
            "config": config.dict() if hasattr(config, "dict") else {},
        }

        try:
            prompt_str = engine.registry.generate(config.llm_name, context)
        except Exception as exc:
            logger.error("LLM generation failed on trial %d: %s", trial_counter, exc)
            raise ConfigurationError(f"Failed to generate prompt for trial {trial_counter}") from exc

        candidate = PromptCandidate.from_llm(
            prompt_str,
            {"source": config.llm_name, "trial_index": trial_counter},
        )

        # -----------------------------------------------------------------
        # Execute trial and evaluate
        # -----------------------------------------------------------------
        try:
            result = engine.run_trial(candidate)
        except EvaluationError as exc:
            logger.error("Evaluation failed on trial %d: %s", trial_counter, exc)
            # Record the failure with a sentinel score
            result = TrialResult(
                candidate_id=candidate.id,
                output=None,
                score=float("-inf"),
                metadata={"error_type": "evaluation", "exception": str(exc)},
            )
        except Exception as exc:
            logger.error("Unexpected error on trial %d: %s", trial_counter, exc)
            raise ConfigurationError(f"Fatal error during trial {trial_counter}") from exc

        # Persist the result
        engine.log_trial(result)
        results.append(result)

        logger.info(
            "Trial %d completed – score: %.4f", trial_counter, result.score
        )
        trial_counter += 1

    # Optionally write a consolidated JSON lines file for quick inspection
    if json_log is not None:
        try:
            json_log.parent.mkdir(parents=True, exist_ok=True)
            with json_log.open("w", encoding="utf-8") as f:
                for r in results:
                    json.dump(r.dict() if hasattr(r, "dict") else r.__dict__, f)
                    f.write("\n")
            logger.info("All trial results written to %s", json_log)
        except Exception as exc:
            logger.error("Failed to write JSON log: %s", exc)

    return results


def print_summary(results: List[TrialResult], top_n: int = 5) -> None:
    """
    Print a concise summary of the best *top_n* trials.
    """
    if not results:
        print("No results to display.")
        return

    # Sort descending by score; treat ``-inf`` as worst
    sorted_results = sorted(
        results,
        key=lambda r: r.score if r.score != float("-inf") else float("-inf"),
        reverse=True,
    )
    print("\n=== Top Trials ===")
    for idx, res in enumerate(sorted_results[:top_n], start=1):
        print(
            f"{idx}. Candidate {res.candidate_id[:8]}… – Score: {res.score:.4f}"
        )
        print(f"   Output: {res.output}")
        print(f"   Metadata: {res.metadata}\n")


def load_results_from_json(json_path: Path) -> List[TrialResult]:
    """
    Load ``TrialResult`` objects from a JSON‑lines file.
    """
    results: List[TrialResult] = []
    with json_path.open("r", encoding="utf-8") as f:
        for line in f:
            data = json.loads(line.strip())
            # Re‑construct a ``TrialResult`` – the model is a simple dataclass‑like
            # container, so we can unpack the dict directly.
            results.append(TrialResult(**data))
    return results


def main() -> None:
    """
    Command‑line entry point for the example script.
    """
    parser = argparse.ArgumentParser(
        description="Run a prompt‑optimus optimisation experiment and view results."
    )
    parser.add_argument(
        "config",
        nargs="?",
        type=Path,
        help="Path to an optimisation YAML file. If omitted, the script searches upward.",
    )
    parser.add_argument(
        "--max-trials",
        type=int,
        default=None,
        help="Override the max_trials value from the configuration file.",
    )
    parser.add_argument(
        "--json-log",
        type=Path,
        default=Path("logs/trials.jsonl"),
        help="Path where a JSON‑lines log of all trials will be written.",
    )
    parser.add_argument(
        "--sqlite-log",
        type=Path,
        default=Path("logs/trials.sqlite"),
        help="Path for the SQLite database used by the logger.",
    )
    args = parser.parse_args()

    logger = get_logger(__name__)

    try:
        cfg_path = args.config or _discover_config(Path.cwd())
        logger.info("Using configuration file: %s", cfg_path)
        config = load_optimization_config(cfg_path)
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)

    try:
        results = run_optim(
            config,
            max_trials=args.max_trials,
            json_log=args.json_log,
            sqlite_log=args.sqlite_log,
        )
    except ConfigurationError as exc:
        logger.error("Run failed: %s", exc)
        sys.exit(1)

    print_summary(results)

    # Demonstrate loading from the persisted JSON file
    if args.json_log.is_file():
        loaded = load_results_from_json(args.json_log)
        logger.info("Loaded %d results from %s", len(loaded), args.json_log)


if __name__ == "__main__":
    main()