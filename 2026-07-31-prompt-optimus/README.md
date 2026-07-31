# Prompt‑Optimus

## Overview
Prompt‑Optimus is an LLM‑driven prompt‑template optimizer that automatically tunes, validates, and version‑controls prompt pipelines for any Python‑exposed API. It reads a declarative optimization plan, iteratively generates candidate prompts via pluggable LLM drivers, evaluates them against user‑provided metrics, and persists every trial to both JSON and SQLite for reproducible research.

## Installation
```bash
pip install prompt-optimus
```

## Quick Start
```bash
prompt_optimus run path/to/optimization.yaml
```

The command reads the YAML manifest, runs the optimisation loop, and stores results under the `results/` directory.

## Features
- **Declarative experiment manifests** – describe target functions, metrics, and LLM choice in a single YAML file.
- **Plugin‑first LLM registry** – swap Claude, OpenAI, or local models without code changes.
- **Dual persistence** – human‑readable JSON logs plus fast SQLite aggregation.
- **Robust error handling** – fatal configuration errors abort with a traceback; transient errors are retried with exponential back‑off.

## API Reference
### Core Engine (`src.core.engine`)
- `PromptEngine` – orchestrates the optimisation loop.
- `run_optim(config_path: Path) -> None` – convenience wrapper used by the CLI.
- Private helpers:
  - `_load_config(path: Path) -> OptimizationConfig`
  - `_exponential_backoff(attempt: int) -> float`
  - `_safe_fallback_prompt(candidate: PromptCandidate) -> PromptCandidate`

### Models (`src.core.models`)
- `OptimizationConfig` – pydantic model describing the optimisation plan.
- `PromptCandidate` – dataclass representing a generated prompt.
- `TrialResult` – dataclass storing the outcome of a single trial.
- `EvaluationError` – raised when a metric evaluation fails.
- `ConfigurationError` – raised for invalid user configuration.

### Plugin Registry (`src.plugins.registry`)
- `BaseLLMDriver` – abstract base class for all LLM drivers.
- `PluginRegistry` – singleton that holds registered drivers and provides lookup.

## Architecture
```
+-------------------+        +-------------------+        +-------------------+
|   CLI (click)    |  -->   |   PromptEngine    |  -->   |   PluginRegistry  |
+-------------------+        +-------------------+        +-------------------+
          |                               |                         |
          v                               v                         v
   YAML Manifest                Optimization Loop          LLM Drivers (OpenAI,
   (OptimizationConfig)          (generate, evaluate,      Claude, Local, …)
                                   persist)                
```
The CLI parses a YAML manifest into an `OptimizationConfig`. `PromptEngine` drives the optimisation loop, requesting prompt candidates from the selected `BaseLLMDriver` via `PluginRegistry`. Each candidate is evaluated against the configured metrics, and the results are logged both to JSON files and an SQLite database for later analysis.

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.
