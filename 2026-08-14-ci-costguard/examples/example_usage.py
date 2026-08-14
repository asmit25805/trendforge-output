from __future__ import annotations

import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import Iterator

from src.core.alert import AlertDispatcher
from src.core.aggregator import CostAggregator
from src.core.budget import BudgetEnforcer
from src.core.parser import ProviderParser, register_parser, parse_file
from src.core.models import (
    AggregatedReport,
    AlertMessage,
    BudgetConfig,
    CIContext,
    TokenRecord,
)

# Configure a simple console logger for the example
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)


class DummyParser(ProviderParser):
    """Parse ``.dummylog`` files where each line is a JSON representation of a TokenRecord."""

    @staticmethod
    def supported_extensions() -> set[str]:
        return {".dummylog"}

    def parse(self, file_path: Path) -> Iterator[TokenRecord]:
        with file_path.open("r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    yield TokenRecord(
                        timestamp=data["timestamp"],
                        provider=data["provider"],
                        model=data["model"],
                        prompt_tokens=int(data["prompt_tokens"]),
                        completion_tokens=int(data["completion_tokens"]),
                        total_tokens=int(data["total_tokens"]),
                    )
                except Exception as exc:  # pylint: disable=broad-except
                    logger.warning(
                        "Failed to parse line %d in %s: %s", line_no, file_path, exc
                    )
                    continue


def _write_dummy_log(log_path: Path, records: list[dict]) -> None:
    """Write a list of record dictionaries as JSON‑lines to ``log_path``."""
    with log_path.open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec) + "\n")
    logger.info("Created dummy log at %s with %d entries", log_path, len(records))


def _create_budget_config(workspace: Path) -> None:
    """Create a minimal ``.ci-costguard.yaml`` file inside ``workspace``."""
    config = {
        "max_tokens": 1000,
        "max_cost_usd": 5.0,
        "grace_percentage": 0.05,
    }
    config_path = workspace / ".ci-costguard.yaml"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    logger.info("Wrote budget config to %s", config_path)


def _setup_example_workspace() -> Path:
    """Prepare a temporary workspace containing a config file and a dummy log."""
    workspace = Path(tempfile.mkdtemp(prefix="ci_costguard_example_"))
    logger.info("Created temporary workspace at %s", workspace)

    # Write budget configuration
    _create_budget_config(workspace)

    # Create a dummy log file
    dummy_log = workspace / "example.dummylog"
    dummy_records = [
        {
            "timestamp": "2023-01-01T00:00:00Z",
            "provider": "dummy",
            "model": "model-alpha",
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
        {
            "timestamp": "2023-01-01T00:01:00Z",
            "provider": "dummy",
            "model": "model-beta",
            "prompt_tokens": 20,
            "completion_tokens": 10,
            "total_tokens": 30,
        },
        {
            "timestamp": "2023-01-01T00:02:00Z",
            "provider": "dummy",
            "model": "model-alpha",
            "prompt_tokens": 5,
            "completion_tokens": 5,
            "total_tokens": 10,
        },
    ]
    _write_dummy_log(dummy_log, dummy_records)

    return workspace


def _display_report(report: AggregatedReport) -> None:
    """Pretty‑print the aggregated report to the console."""
    pretty = json.dumps(
        {
            "run_id": report.run_id,
            "total_tokens": report.total_tokens,
            "total_cost_usd": report.total_cost_usd,
            "provider_totals": report.provider_totals,
            "model_totals": report.model_totals,
        },
        indent=2,
    )
    logger.info("Aggregated Report:\n%s", pretty)


def main() -> int:
    """Run a full CI‑CostGuard cycle against a synthetic workspace."""
    # Register the dummy parser so that ``parse_file`` can locate it.
    register_parser(DummyParser())

    # Prepare a temporary workspace with config and logs.
    workspace = _setup_example_workspace()

    # Build a CIContext that mimics what a CI system would provide.
    context = CIContext(
        env={"CI": "true", "GITHUB_RUN_ID": "example-run"},
        workspace=workspace,
        run_id="example-run",
    )

    # Import the plugin lazily to avoid circular imports during registration.
    from src.ci.plugin import CIPlugin, CIPluginError

    plugin = CIPlugin()
    try:
        exit_code = plugin.run(context)
    except CIPluginError as exc:
        logger.error("CIPlugin failed with exit code %d: %s", exc.exit_code, exc)
        return exc.exit_code

    # The plugin writes the aggregated report as a JSON artifact.
    # By convention the artifact is named ``ci_costguard_report.json`` in the workspace.
    report_path = workspace / "ci_costguard_report.json"
    if report_path.is_file():
        try:
            data = json.loads(report_path.read_text(encoding="utf-8"))
            report = AggregatedReport(**data)  # type: ignore[arg-type]
            _display_report(report)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error("Failed to load report from %s: %s", report_path, exc)
    else:
        logger.warning("Report artifact not found at %s", report_path)

    # Demonstrate alert dispatching manually (the plugin already does this internally).
    alert = AlertMessage(
        title="Example usage completed",
        body="The CI‑CostGuard run finished with exit code %d." % exit_code,
        severity="info",
        run_id=context.run_id,
    )
    dispatcher = AlertDispatcher()
    dispatcher.dispatch(alert)

    logger.info("Example execution finished with exit code %d", exit_code)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())