from __future__ import annotations

import json
import logging
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol, Tuple

from src.core.models import (
    BenchmarkScenario,
    BenchmarkResult,
    TraceRecord,
    SkillSpec,
    ExpectedOutcome,
)
from src.core.engine import AgentLoop
from src.validation.trace import TraceValidator

log = logging.getLogger(__name__)
log.setLevel(logging.INFO)


class BenchmarkSuite:
    """Container for a collection of :class:`BenchmarkScenario` objects.

    The suite can be iterated over to obtain each scenario.  It also provides a
    ``run`` method that executes all scenarios using an ``AgentLoop`` and stores
    the results in a SQLite database for later analysis.
    """

    def __init__(self, scenarios: Iterable[BenchmarkScenario], db_path: str | Path = ":memory:") -> None:
        self.scenarios = list(scenarios)
        self.db_path = Path(db_path)
        self._init_db()

    def _init_db(self) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS results (
                id TEXT PRIMARY KEY,
                scenario TEXT,
                outcome TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
        conn.close()

    def run(self, registry: "src.skills.registry.SkillRegistry") -> List[BenchmarkResult]:
        validator = TraceValidator()
        loop = AgentLoop(registry, validator)
        results: List[BenchmarkResult] = []
        for scenario in self.scenarios:
            try:
                trace = loop.run(scenario.skill_name, scenario.skill_version, scenario.inputs)
                outcome = "success"
            except Exception as exc:
                log.error("Scenario %s failed: %s", scenario, exc)
                outcome = f"failure: {exc}"
            result = BenchmarkResult(
                id=str(uuid.uuid4()),
                scenario=scenario,
                outcome=outcome,
                created_at=datetime.utcnow().isoformat(),
            )
            results.append(result)
            self._store_result(result)
        return results

    def _store_result(self, result: BenchmarkResult) -> None:
        conn = sqlite3.connect(self.db_path)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO results (id, scenario, outcome, created_at) VALUES (?, ?, ?, ?)",
            (result.id, json.dumps(asdict(result.scenario)), result.outcome, result.created_at),
        )
        conn.commit()
        conn.close()


def run_suite(suite: BenchmarkSuite, registry: "src.skills.registry.SkillRegistry") -> List[BenchmarkResult]:
    """Execute a :class:`BenchmarkSuite` and return the collected results.

    This thin wrapper exists so that the public API matches the specification in
    the project manifest.
    """
    return suite.run(registry)
