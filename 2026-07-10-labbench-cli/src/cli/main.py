from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import List

from rich.console import Console
from rich.table import Table
from rich.traceback import install as install_rich_traceback

from src.core.engine import Engine
from src.core.models import ExperimentConfig, load_experiment_config, RunResult, RunStatus

install_rich_traceback()
logger = logging.getLogger(__name__)
console = Console()


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="labbench",
        description="Run LabBench experiments",
    )
    parser.add_argument(
        "config",
        type=Path,
        help="Path to experiment YAML or JSON file",
    )
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory containing plugin executables (default: current working directory)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    return parser.parse_args(argv)


def _display_results(results: List[RunResult]) -> None:
    table = Table(title="Experiment Results")
    table.add_column("Step")
    table.add_column("Status")
    table.add_column("Duration")
    for res in results:
        duration = (res.end_time - res.start_time).total_seconds()
        table.add_row(res.step_name, res.status.value, f"{duration:.2f}s")
    console.print(table)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING)
    try:
        config: ExperimentConfig = load_experiment_config(args.config)
    except Exception as exc:
        logger.error("Failed to load experiment config: %s", exc)
        return 1
    engine = Engine()
    results = engine.run(config, checkpoint_dir=args.plugins_dir / ".labbench")
    _display_results(results)
    return 0


if __name__ == "__main__":
    sys.exit(main())
