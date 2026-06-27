# LoopWatch

## Overview
LoopWatch provides real‑time compliance, cost, and safety monitoring for AI‑agent loops. It watches JSON‑line log files, evaluates each run against configurable rules, estimates upcoming token costs, and dispatches alerts to Slack, GitHub PR comments, or other channels. The design emphasizes reliability, low latency, and extensibility without requiring a database.

## Features
- **File‑based ingestion** – watches glob patterns for new loop‑run entries.
- **Rule engine** – sandboxed JavaScript rule definitions with severity levels.
- **Cost estimator** – sliding‑window token usage statistics and provider pricing.
- **Alert dispatcher** – pluggable channels, throttling, and automatic retries.
- **Config loader** – single `loopwatch.yaml` with validation and hot‑reload.

## Installation
```bash
npm install loopwatch
```

## Quick Start
```ts
import { ConfigLoader } from "loopwatch/src/config/loader";
import { LoopMonitor } from "loopwatch/src/core/engine";
import { LoopwatchConfig } from "loopwatch/src/types";

// Load configuration
const configLoader = new ConfigLoader("./loopwatch.yaml");
const config: LoopwatchConfig = await configLoader.load();

// Start monitoring
const monitor = new LoopMonitor(config);
await monitor.start();
```

## Architecture
![LoopWatch Architecture Diagram](https://raw.githubusercontent.com/asmit25805/loopwatch/main/docs/architecture.png)

The system consists of four main components:
1. **Config Loader** – parses `loopwatch.yaml` and emits change events.
2. **Loop Monitor** – watches log files, parses `LoopRun` entries, and forwards them to the rule engine.
3. **Rule Engine** – evaluates each `LoopRun` against user‑defined `RuleDefinition`s in a sandboxed VM.
4. **Cost Estimator** – maintains a sliding window of token usage and projects future costs.
5. **Alert Dispatcher** – sends alerts via configured channels (Slack, GitHub, email, etc.) with throttling and retry logic.

## API Reference
### Types
- `LoopRun` – representation of a single loop execution.
- `RuleDefinition` – user‑defined rule with a JavaScript predicate.
- `RuleResult` – outcome of a rule evaluation.
- `CostProjection` – estimated future cost based on token usage.
- `Alert` – alert payload dispatched to a channel.
- `LoopwatchConfig` – top‑level configuration object.
- `Severity` – `'info' | 'warning' | 'error'`.

### Classes
- `ConfigLoader` – loads and watches the configuration file.
- `LoopMonitor` – core engine that monitors loop runs.
- `RuleEngine` – evaluates rules against a `LoopRun`.
- `CostEstimator` – projects token costs.
- `AlertDispatcher` – sends alerts to configured channels.

### Example Usage
See `examples/basic-usage.ts` for a complete end‑to‑end example.

## Contributing
Contributions are welcome! Please fork the repository, make your changes, and submit a pull request.

## License
This project is licensed under the MIT License.
