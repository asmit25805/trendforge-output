from __future__ import annotations

import datetime
import logging
from pathlib import Path
from typing import List

import networkx as nx

from src.core.models import (
    ExperimentConfig,
    RunResult,
    RunStatus,
    StepSpec,
    save_checkpoint,
)
from src.core.plugin_manager import FatalError, TransientError, PluginManager

logger = logging.getLogger(__name__)


class Engine:
    """Coordinates the full experiment lifecycle – loading configuration,
    resolving step order, executing plugins, and persisting results.
    """

    def __init__(self, plugin_manager: PluginManager | None = None):
        self.plugin_manager = plugin_manager or PluginManager()

    def _build_dag(self, config: ExperimentConfig) -> nx.DiGraph:
        """Create a directed acyclic graph (DAG) of steps based on dependencies."""
        dag = nx.DiGraph()
        for step in config.steps:
            dag.add_node(step.name, spec=step)
            for dep in step.depends_on:
                dag.add_edge(dep, step.name)
        if not nx.is_directed_acyclic_graph(dag):
            raise ValueError("Experiment steps contain cycles")
        return dag

    def run(self, config: ExperimentConfig, checkpoint_dir: Path | str = ".labbench") -> List[RunResult]:
        """Execute the experiment defined by *config*.

        Returns a list of :class:`RunResult` objects, one per executed step.
        """
        dag = self._build_dag(config)
        results: List[RunResult] = []
        for step_name in nx.topological_sort(dag):
            step: StepSpec = dag.nodes[step_name]["spec"]
            start = datetime.datetime.utcnow()
            try:
                logger.info("Running step %s (plugin %s)", step.name, step.plugin_id)
                output = self.plugin_manager.execute(step.plugin_id, step.params)
                status = RunStatus.SUCCESS
                error_msg = None
            except FatalError as exc:
                logger.error("Fatal error in step %s: %s", step.name, exc)
                output = None
                status = RunStatus.FAILED
                error_msg = str(exc)
                # Stop further execution on fatal error
                break
            except TransientError as exc:
                logger.warning("Transient error in step %s: %s", step.name, exc)
                output = None
                status = RunStatus.FAILED
                error_msg = str(exc)
                break
            end = datetime.datetime.utcnow()
            result = RunResult(
                experiment_id=config.id,
                step_name=step.name,
                status=status,
                start_time=start,
                end_time=end,
                output=output,
                error=error_msg,
            )
            save_checkpoint(result, checkpoint_dir)
            results.append(result)
        return results
