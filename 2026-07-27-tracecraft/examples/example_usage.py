from __future__ import annotations

import json
import logging
import tempfile
from pathlib import Path
from typing import List

from src.core.engine import AgentLoop, LLMUnavailable
from src.core.models import BenchmarkScenario, BenchmarkResult, SkillSpec, TraceRecord
from src.skills.registry import DuplicateSkillError, SkillNotFound, SkillRegistry, load_skills_from_path
from src.validation.trace import TraceValidator
from src.benchmark.runner import BenchmarkSuite

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


def _create_demo_skill(dir_path: Path) -> Path:
    """Write a minimal skill manifest to *dir_path* and return its file path."""
    skill_data = {
        "name": "demo-skill",
        "version": "0.1.0",
        "description": "A trivial skill used for the example script.",
        "system_prompt": "You are a helpful assistant that can execute shell commands.",
        "parameters": {},
    }
    manifest_path = dir_path / "demo-skill.json"
    manifest_path.write_text(json.dumps(skill_data, indent=2))
    return manifest_path


def _load_registry(skills_root: Path) -> SkillRegistry:
    """Create a SkillRegistry and load all skill manifests under *skills_root*."""
    registry = SkillRegistry()
    registry.load_from_path(skills_root)
    return registry


def _run_agent(
    registry: SkillRegistry, task: str, skill_name: str, skill_version: str
) -> TraceRecord:
    """Resolve a skill from *registry* and execute *task* with an AgentLoop."""
    try:
        skill_spec: SkillSpec = registry.resolve(skill_name, skill_version)
    except SkillNotFound as exc:
        log.error("Skill resolution failed: %s", exc)
        raise

    agent = AgentLoop(skill_spec=skill_spec, docker_client=None)
    try:
        trace: TraceRecord = agent.run(task=task, skill=skill_name, skill_version=skill_version)
    except LLMUnavailable as exc:
        log.error("LLM unavailable after retries: %s", exc)
        raise
    return trace


def _validate_trace(trace: TraceRecord, scenario: BenchmarkScenario) -> BenchmarkResult:
    """Validate *trace* against *scenario* and return a BenchmarkResult."""
    validator = TraceValidator()
    result: BenchmarkResult = validator.validate(trace, scenario)
    return result


def _run_benchmark_suite(
    agent: AgentLoop, scenarios: List[BenchmarkScenario], db_path: Path
) -> List[BenchmarkResult]:
    """Execute *scenarios* with *agent* and store results in a SQLite DB at *db_path*."""
    suite = BenchmarkSuite(db_path=db_path)
    results: List[BenchmarkResult] = suite.run_all(agent=agent, scenarios=scenarios)
    suite.export_report(results, format="json")
    return results


def main() -> None:
    """Demonstrate loading a skill, running an agent, validating a trace, and benchmarking."""
    # --------------------------------------------------------------------- #
    # 1. Prepare a temporary skill directory and load the registry.
    # --------------------------------------------------------------------- #
    with tempfile.TemporaryDirectory() as tmp_dir:
        skills_dir = Path(tmp_dir) / "skills"
        skills_dir.mkdir(parents=True, exist_ok=True)
        _create_demo_skill(skills_dir)

        registry = _load_registry(skills_dir)

        # --------------------------------------------------------------------- #
        # 2. Run the agent on a simple task.
        # --------------------------------------------------------------------- #
        task_description = "Print the word hello using the shell."
        trace = _run_agent(
            registry,
            task=task_description,
            skill_name="demo-skill",
            skill_version="0.1.0",
        )
        log.info("TraceRecord created with run_id=%s", trace.run_id)

        # --------------------------------------------------------------------- #
        # 3. Load a benchmark scenario and validate the trace.
        # --------------------------------------------------------------------- #
        # For the example we assume a scenario directory exists at ./benchmarks/example.
        scenario_dir = Path(__file__).parent.parent / "benchmarks" / "example"
        if scenario_dir.is_dir():
            # The BenchmarkSuite can also load scenarios; we reuse that logic.
            suite = BenchmarkSuite(db_path=Path("example_benchmark.db"))
            scenarios = suite.load_scenarios(scenario_dir)
            if scenarios:
                scenario = scenarios[0]
                validation_result = _validate_trace(trace, scenario)
                log.info(
                    "Validation completed for scenario %s: issues=%s",
                    validation_result.scenario_id,
                    validation_result.issues,
                )
        else:
            log.warning("Benchmark scenario directory %s not found; skipping validation.", scenario_dir)

        # --------------------------------------------------------------------- #
        # 4. Run a full benchmark suite over all discovered scenarios.
        # --------------------------------------------------------------------- #
        benchmarks_root = Path(__file__).parent.parent / "benchmarks"
        if benchmarks_root.is_dir():
            suite = BenchmarkSuite(db_path=Path("full_benchmark.db"))
            all_scenarios = suite.load_scenarios(benchmarks_root)
            if all_scenarios:
                _run_benchmark_suite(agent=AgentLoop(skill_spec=registry.resolve("demo-skill", "0.1.0"), docker_client=None),
                                     scenarios=all_scenarios,
                                     db_path=Path("full_benchmark.db"))
                log.info("Benchmark suite completed; report written.")
        else:
            log.warning("Benchmarks root %s not found; skipping full suite.", benchmarks_root)


if __name__ == "__main__":
    main()