# LabBench CLI

## Overview
LabBench CLI is a reproducible‑research command‑line tool that version‑controls data pipelines and orchestrates domain‑specific experiment agents. It enables scientists to declare experiments in a human‑readable YAML format, automatically resolves step dependencies, and executes each step in an isolated sandbox. The tool records checkpoints after every step, allowing runs to be paused, resumed, or inspected without re‑executing completed work. By treating plugins as first‑class assets, LabBench supports plugins written in any language that obey a simple JSON contract.

## Features
- Declarative experiment definition in YAML or JSON.
- Automatic DAG resolution and topological ordering.
- Subprocess sandbox for each plugin with configurable resource limits.
- Per‑step checkpointing.
- Extensible plugin system.

## Installation
```bash
pip install labbench-cli
```

## Quick Start
```bash
# Create an experiment definition (example_experiment.yaml)
labbench run example_experiment.yaml
```

## Usage
```bash
labbench [OPTIONS] CONFIG_PATH
```

- `CONFIG_PATH` – Path to a YAML or JSON experiment definition.
- `--plugins-dir PATH` – Directory containing plugin executables (default: current working directory).
- `-v, --verbose` – Enable verbose logging.

## API Reference
### Core Models (`src.core.models`)
- **`StepSpec`** – Pydantic model describing a single step.
- **`ExperimentConfig`** – Root model for an experiment definition.
- **`PluginSpec`** – Specification of a plugin (id, entrypoint, description).
- **`RunStatus`** – Enum (`PENDING`, `RUNNING`, `SUCCESS`, `FAILED`).
- **`RunResult`** – Result of a step execution.
- **`load_experiment_config(path)`** – Load a YAML/JSON experiment file.
- **`save_checkpoint(result, directory)`** – Persist a `RunResult` as JSON.

### Engine (`src.core.engine.Engine`)
- **`Engine(plugin_manager=None)`** – Create an engine; optionally provide a custom `PluginManager`.
- **`run(config, checkpoint_dir)`** – Execute the experiment, returning a list of `RunResult` objects.

### Plugin Manager (`src.core.plugin_manager.PluginManager`)
- **`register(spec)`** – Register a `PluginSpec`.
- **`execute(plugin_id, params)`** – Run a plugin and return its JSON output.
- **Exceptions** – `PluginError`, `FatalError`, `TransientError`.

## Architecture
```
+-------------------+        +-------------------+
|   Experiment      |        |   Plugin Manager  |
|   Definition (YAML) |<---->|   (subprocess)    |
+-------------------+        +-------------------+
          |                               |
          v                               v
+-------------------+        +-------------------+
|   Engine          |------->|   RunResult       |
|   (DAG resolver)  |        |   (checkpoint)    |
+-------------------+        +-------------------+
```
The Engine loads the experiment configuration, builds a directed acyclic graph (DAG) of steps, and executes each step in topological order using the Plugin Manager. After each step, a `RunResult` is saved to a checkpoint directory.

## Contributing
Contributions are welcome! Please open issues or pull requests on the repository:
https://github.com/asmit25805/labbench-cli

## License
This project is licensed under the MIT License.
