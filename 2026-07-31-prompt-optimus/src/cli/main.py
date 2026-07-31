import sys
import time
from pathlib import Path
from typing import Any

import click
import yaml

from src.core.engine import PromptEngine, run_optim
from src.core.models import ConfigurationError, OptimizationConfig, PromptCandidate, EvaluationError
from src.reporters.logger import get_logger


def _discover_config(start_dir: Path) -> Path:
    """Search ``start_dir`` and its parents for a ``optimisation.yaml`` file.

    The function returns the first matching file path. If none is found, a
    ``ConfigurationError`` is raised.
    """
    current = start_dir.resolve()
    for parent in [current, *current.parents]:
        candidate = parent / "optimisation.yaml"
        if candidate.is_file():
            return candidate
    raise ConfigurationError("No optimisation.yaml file found in the current directory or any parent.")


@click.command()
@click.argument("config_path", required=False, type=click.Path(exists=True, path_type=Path))
def main(config_path: Path | None = None) -> None:
    """Entry point for the ``prompt_optimus`` CLI.

    If ``CONFIG_PATH`` is omitted, the command searches upward from the current
    working directory for a file named ``optimisation.yaml``.
    """
    logger = get_logger()
    try:
        if config_path is None:
            config_path = _discover_config(Path.cwd())
        logger.info("Running optimisation using config: %s", config_path)
        run_optim(config_path)
        logger.info("Optimisation completed successfully.")
    except ConfigurationError as exc:
        logger.error("Configuration error: %s", exc)
        sys.exit(1)
    except Exception as exc:
        logger.exception("Unexpected error: %s", exc)
        sys.exit(1)

if __name__ == "__main__":
    main()
