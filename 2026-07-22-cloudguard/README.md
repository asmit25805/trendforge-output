# cloudguard

## Overview

cloudguard is an open‑source, typed A2A (Agent‑to‑Agent) policy engine that automatically remediates multi‑cloud incidents. It receives alerts from any source (CloudWatch, Prometheus, etc.), wraps them in a strongly typed `A2AMessage`, and routes the message through a dynamic gateway to a deterministic `PolicyEngine`. When the baseline plan contains high‑risk actions, the engine marks the plan as requiring human approval. An optional `LLMPlanner` can enrich the plan, after which a `HealingAgent` executes the actions in dry‑run mode, promoting to real writes only after explicit approval. All steps are logged, audited, and emitted as `A2AResponse` objects.

## Features

- Typed A2A protocol guarantees contract stability across agents.
- Dynamic endpoint registry enables flexible routing.
- Policy engine evaluates incidents against configurable policy rules.
- Optional LLM‑driven planning enriches remediation actions.
- Healing agent executes actions safely with dry‑run support.
- Comprehensive logging and audit trails.

## Installation

```bash
pip install cloudguard
```

## Quick Start

```python
from src.core.gateway import A2AGateway, GatewaySettings
from src.core.models import A2AMessage, PriorityLevel

# Configure the gateway
settings = GatewaySettings()
gateway = A2AGateway(settings)

# Create a sample message
msg = A2AMessage(
    incident_id="inc-123",
    source="cloudwatch",
    priority=PriorityLevel.HIGH,
    payload={"detail": "example"},
)

# Send the message through the gateway
response = await gateway.handle_message(msg)
print(response)
```

## Architecture

```
+----------------+      +----------------+      +-------------------+
|   Source(s)   | ---> |   Gateway      | ---> |   Policy Engine   |
+----------------+      +----------------+      +-------------------+
                                 |                         |
                                 v                         v
                         +----------------+      +-------------------+
                         |  LLM Planner   |      | Healing Agent     |
                         +----------------+      +-------------------+
```

The **Gateway** receives `A2AMessage` objects and forwards them to the **Policy Engine**. The engine evaluates the incident against `PolicyRule`s and produces a remediation plan (`RemediationAction`s). If the plan is high‑risk, it is flagged for human approval. An optional **LLM Planner** can augment the plan with additional context or actions. Finally, the **Healing Agent** executes the plan, initially in dry‑run mode.

## API Reference

### Core Models (`src.core.models`)
- `A2AMessage` – The inbound message format.
- `A2AResponse` – The outbound response format.
- `Incident` – Representation of an incident.
- `PolicyRule` – Definition of a policy rule.
- `RemediationAction` – Action to remediate an incident.
- `PriorityLevel` – Enum of priority levels (`LOW`, `MEDIUM`, `HIGH`).
- `ResponseStatus` – Enum of response statuses (`SUCCESS`, `FAILURE`).
- `AgentBase` – Base class for agents.

### Gateway (`src.core.gateway`)
- `GatewaySettings` – Configuration for the gateway.
- `A2AGateway` – Main class handling message routing.

### Policy Engine (`src.core.policy_engine`)
- `PolicyEngineSettings` – Configuration for the policy engine.
- `PolicyEngine` – Evaluates incidents against policy rules.

### LLM Planner (`src.llm.llm_client`)
- `LLMPlanner` – Optional planner that enriches remediation plans using an LLM.
- `TokenCache` – Simple cache for LLM authentication tokens.

### Healing Agent (`src.agents.healing_agent`)
- `HealingAgent` – Executes remediation actions safely.

## Contributing

Contributions are welcome! Please open issues and submit pull requests.

## License

This project is licensed under the MIT License.
