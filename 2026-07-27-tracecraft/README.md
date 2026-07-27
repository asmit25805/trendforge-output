# Tracecraft

## Overview

Tracecraft is a versioned skill library that enables large language models (LLMs) to generate, replay, and verify execution traces for reproducible agent workflows. By separating skill definitions from prompt rendering and enforcing double‑check validation, Tracecraft provides a robust foundation for building trustworthy autonomous agents.

## Features

- **Versioned Skill Catalog** – Define skills with semantic versions and load them from JSON/YAML manifests.
- **Think‑Act‑Prove‑Grow Cycle** – Orchestrates LLM calls, sandboxed execution, and evidence collection.
- **Docker‑Based Sandbox** – Isolates side‑effects, captures stdout, stderr, exit codes, and file changes.
- **Deterministic Replay** – Re‑executes actions in a fresh sandbox to verify claimed effects.

## Installation

```bash
pip install tracecraft
```

## Quick Start

```python
from src.core.engine import run_agent
from src.skills.registry import load_skills_from_path
from src.validation.trace import TraceValidator

# Load skill definitions from the ``skills`` directory.
registry = load_skills_from_path("./skills")
validator = TraceValidator()

# Execute a skill.
trace = run_agent(
    registry=registry,
    validator=validator,
    name="example_skill",
    version="1.0.0",
    inputs={"param": "value"},
)
print("Trace ID:", trace.id)
```

## API Reference

### Core Engine
- **`AgentLoop`** – Executes a skill and validates the resulting trace.
- **`run_agent`** – Convenience wrapper that creates an `AgentLoop` and runs a single skill.
- **`LLMUnavailable`** – Exception raised when the language‑model service cannot be reached.

### Skill Registry
- **`SkillRegistry`** – In‑memory registry for `SkillSpec` objects.
- **`load_skills_from_path(path)`** – Load skill manifests (JSON/YAML) from a directory.
- **`SkillNotFound`**, **`DuplicateSkillError`** – Registry‑related exceptions.

### Validation
- **`TraceValidator`** – Validates a `TraceRecord` (exit code, JSON output, etc.).
- **`validate_trace(trace)`** – Helper function that validates a trace using the default validator.

### Benchmarking
- **`BenchmarkSuite`** – Collection of benchmark scenarios.
- **`run_suite(suite, registry)`** – Execute a benchmark suite and return results.

## Architecture

```
+-------------------+        +-------------------+        +-------------------+
|   Skill Registry  | -----> |   Core Engine     | -----> |   Validation      |
+-------------------+        +-------------------+        +-------------------+
        |                                 |
        v                                 v
+-------------------+        +-------------------+
|   Benchmarking   | <----- |   Trace Records   |
+-------------------+        +-------------------+
```

The diagram above shows the high‑level data flow: skills are loaded into the registry, the engine executes them, validation checks the resulting traces, and benchmarking utilities can run suites of scenarios against this pipeline.
