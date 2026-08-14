# ci-costguard

## Overview
ci-costguard provides automatic tracking, budgeting, and alerting for Large Language Model (LLM) token usage inside continuous‑integration (CI) pipelines. It discovers provider‑specific log files, normalises them into a common token record format, aggregates usage per run, checks against configurable budgets, and dispatches alerts through pluggable back‑ends such as Slack or GitHub.

The library is framework‑agnostic and can be invoked from GitHub Actions, GitLab CI, Jenkins, or any custom CI system that can provide environment context.

## Features
- **Provider‑agnostic parsing** – plug‑in registry for parsers that understand logs from Claude, Codex, Gemini, and future providers.
- **Token aggregation** – computes total tokens per provider, per model, and per run.
- **Budget enforcement** – configurable hard and soft limits with automatic alerting.
- **Alert dispatching** – extensible back‑ends (Slack, email, GitHub comments, etc.).

## Installation
```bash
pip install ci-costguard
```

## Quick Start
```python
from src.core.parser import ProviderParser, register_parser, parse_file
from src.core.aggregator import CostAggregator
from src.core.budget import BudgetEnforcer, BudgetConfig
from src.core.alert import AlertDispatcher, AlertMessage

# Register a simple JSON‑lines parser (example)
@register_parser
class JsonLinesParser(ProviderParser):
    supported_extensions = {".jsonl"}

    def parse(self, path):
        for line in path.read_text().splitlines():
            data = json.loads(line)
            yield TokenRecord(**data)

# Parse logs, aggregate, enforce budget, and send alerts
records = list(parse_file(Path("logs/example.jsonl")))
aggregator = CostAggregator()
for r in records:
    aggregator.add_record(r)
report = aggregator.generate_report()

budget = BudgetConfig(provider="openai", hard_limit_tokens=100000)
enforcer = BudgetEnforcer()
if not enforcer.enforce(report, budget):
    dispatcher = AlertDispatcher()
    dispatcher.dispatch(AlertMessage(title="Budget Exceeded", body=str(report), severity="high"))
```

## API Reference
### Core Models (`src.core.models`)
- **TokenRecord** – Normalised representation of a single token usage event.
- **AggregatedReport** – Summary of token usage for a CI run.
- **BudgetConfig** – Configuration of hard/soft token limits.
- **AlertMessage** – Payload sent to alert back‑ends.
- **CIContext** – Information about the CI environment.

### Parser (`src.core.parser`)
- **ProviderParser** – Abstract base class for provider‑specific parsers.
- **register_parser** – Decorator to register a parser implementation.
- **parse_file** – Dispatches to the appropriate parser based on file extension.

### Aggregator (`src.core.aggregator`)
- **CostAggregator** – Collects `TokenRecord` objects and produces an `AggregatedReport`.

### Budget (`src.core.budget`)
- **BudgetEnforcer** – Checks an `AggregatedReport` against a `BudgetConfig`.
- **BudgetConfig** – Defines token limits.

### Alert (`src.core.alert`)
- **AlertDispatcher** – Sends `AlertMessage` objects to configured back‑ends.
- **AlertMessage** – Structure of an alert.

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
|   Provider Logs   | ---> |   Parser Registry | ---> |   TokenRecord(s)  |
+-------------------+      +-------------------+      +-------------------+
                                 |                         |
                                 v                         v
                         +-------------------+   +-------------------+
                         | CostAggregator    |   | BudgetEnforcer    |
                         +-------------------+   +-------------------+
                                 |                         |
                                 v                         v
                         +-------------------+   +-------------------+
                         | AggregatedReport  |   | AlertDispatcher   |
                         +-------------------+   +-------------------+
                                 |                         |
                                 v                         v
                         +---------------------------------------+
                         |            CI Plugin (CLI)            |
                         +---------------------------------------+
```

The diagram above shows the flow from raw provider logs through parsing, aggregation, budget enforcement, and finally alert dispatching.
