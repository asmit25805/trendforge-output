# huntforge

## Overview

**huntforge** is a modular, AI‑driven red‑team platform that orchestrates reconnaissance, exploit synthesis, and verifiable reporting across any LLM backend. The framework separates concerns into well‑defined plugins and modules, enabling teams to plug in custom LLM providers, reconnaissance primitives, and exploit generators without touching core logic. Findings are streamed directly into exploit synthesis and validated in isolated Docker sandboxes, producing reproducible verdicts and signed reports suitable for compliance audits and CI pipelines.

## Installation

```bash
pip install huntforge
```

## Quick Start

```bash
python -m huntforge run examples/example_hunt.yaml
```

The example configuration demonstrates how to declare a target, select reconnaissance modules, and chain exploit modules.

## API Reference

### Core
- **Orchestrator** – Coordinates the hunt workflow.
- **run_hunt(config: HuntConfig) → HuntReport** – Entry point for programmatic execution.

### Plugins
- **LLMProviderPlugin** – Abstract base for any LLM service exposing an OpenAI‑compatible API.
- **OpenAICompatAdapter** – Example implementation that talks to OpenAI‑compatible endpoints.

### Modules
- **BaseReconModule** – Base class for reconnaissance primitives.
-   **PortScanReconModule** – Simple TCP port scanner.
-   **SubdomainReconModule** – Sub‑domain enumeration using a wordlist.
- **BaseExploitModule** – Base class for exploit generation.
-   **TemplateExploitModule** – Generates exploits from Jinja2 templates.

### Reporting
- **ReportGenerator** – Produces a signed, machine‑readable report bundle.
- **ReportBundle** – Container for the final report artifacts.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   Orchestrator   | ---> |   Recon Modules   | ---> |   Exploit Modules |
+-------------------+      +-------------------+      +-------------------+
          |                         |                         |
          v                         v                         v
   +----------------+        +----------------+        +----------------+
   |   LLM Provider |        |   Findings    |        |   Verdicts    |
   +----------------+        +----------------+        +----------------+
          \                         |                         /
           \________________________|________________________/
                                 v
                         +-------------------+
                         |  ReportGenerator  |
                         +-------------------+
```

The diagram illustrates the data flow: the **Orchestrator** drives the pipeline, invoking recon modules, feeding findings to exploit modules, collecting verdicts, and finally handing everything to the **ReportGenerator**.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## License

This project is licensed under the MIT License.
