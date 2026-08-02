# codeguard-diff

## Overview

`codeguard-diff` is an incremental security analysis tool that focuses on code changes. It scans only the diff between two Git references, sends the relevant fragments to a language model, and produces actionable findings. The tool runs inside a sandboxed container, automatically detecting host security capabilities (AppArmor, Landlock, seccomp) and configuring the execution environment accordingly.

## Features
- **Diff‑driven scanning** – reduces token usage and speeds up CI pipelines.
- **LLM‑powered detection** – leverages a large language model to identify vulnerabilities in changed code.
- **Sandboxed execution** – adapts to host security features for safe runtime.
- **SQLite persistence** – immutable scan snapshots with fast local queries.
- **Remediation planning** – generates actionable remediation steps for identified findings.

## Installation

```bash
pip install codeguard-diff
```

## Quick Start

```bash
codeguard-diff scan --base main --head feature-branch
```

The command above scans the diff between `main` and `feature-branch`, stores the results in a local SQLite database, and prints a summary table.

## API Reference

- **`src.core.models`** – Pydantic models used across the project (`FilePatch`, `Finding`, `ScanResult`, `RuntimeConfig`, `Severity`, `FindingStatus`).
- **`src.engine.scanner.DiffScanner`** – Core scanner that computes patches and queries the LLM endpoint.
- **`src.store.sqlite.FindingsStore`** – SQLite‑backed store for persisting scan results.
- **`src.runtime.adapter.ContainerRuntimeAdapter`** – Detects host security capabilities and configures the container runtime.
- **`src.remediation.planner.RemediationPlanner`** – Generates and applies remediation actions based on findings.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   CLI (parser)   | ---> |   DiffScanner     | ---> |   LLM Endpoint    |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
+-------------------+      +-------------------+      +-------------------+
| FindingsStore (  | <--- | RemediationPlanner| <--- | ContainerRuntime  |
|   SQLite)         |      +-------------------+      +-------------------+
+-------------------+
```

The CLI parses arguments and invokes `DiffScanner`. The scanner produces `Finding` objects which are stored via `FindingsStore`. `RemediationPlanner` can later read these findings and generate `RemediationAction` objects. All runtime interactions are mediated by `ContainerRuntimeAdapter`, which ensures the process runs with the appropriate security profiles.

## Contributing

Contributions are welcome. Please open issues or submit pull requests on the GitHub repository.

## License

This project is licensed under the MIT License.
