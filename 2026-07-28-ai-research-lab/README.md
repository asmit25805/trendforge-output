# Overview
ai-research-lab is a self‑hosted, model‑agnostic research workbench that couples an autonomous planning agent with a sandboxed compute kernel and an immutable artifact ledger.
It enables reproducible research by orchestrating LLM‑driven plans, executing them in isolated Python sandboxes, and persisting every generated artifact with cryptographic guarantees.

## Features
- **Model‑agnostic planning** – plug‑in any LLM provider via a unified `ProviderAdapter`.
- **Isolated compute kernels** – each step runs in a sandboxed Python process with no network access.
- **Immutable artifact store** – SHA‑256 hashed artifacts stored in SQLite for provenance tracking.
- **Permission profiles** – `ask`, `auto`, and `full` modes let users control autonomy.
- **Robust error handling**

## Install
```bash
npm install ai-research-lab
```

## Quick Start
```ts
import { AgentEngine } from "ai-research-lab/src/core/agentEngine";
import { ProviderAdapter } from "ai-research-lab/src/providers/providerAdapter";
import { KernelManager } from "ai-research-lab/src/kernel/kernelManager";

const provider = new ProviderAdapter({
  type: "openai",
  endpoint: "https://api.openai.com",
  apiKey: "YOUR_API_KEY",
  model: "gpt-4",
});

const kernel = new KernelManager();
const engine = new AgentEngine(provider, kernel);

engine.run({
  description: "Summarize the contents of data.csv",
});
```

## API Reference
### Core
- **AgentEngine** – orchestrates planning, execution, and observation.
- **AgentEvent** – emitted events (`planning`, `execution`, `observation`).
- **TaskSpec** – description of a task to be performed.

### Providers
- **ProviderAdapter** – adapts any LLM provider to a common interface.
- **ProviderConfig** – configuration object for a provider.

### Kernel
- **KernelManager** – manages sandboxed Python processes.
- **KernelHandle** – handle to a running kernel instance.
- **StepResult** – result of a single execution step.

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
|   AgentEngine    | ---> |  ProviderAdapter  | ---> |   LLM Provider    |
+-------------------+      +-------------------+      +-------------------+
        |
        v
+-------------------+      +-------------------+      +-------------------+
|   KernelManager   | ---> |   Python Sandbox  | ---> |   User Code       |
+-------------------+      +-------------------+      +-------------------+
        |
        v
+-------------------+      +-------------------+
|   MemoryStore    | <--- |   Artifact Ledger |
+-------------------+      +-------------------+
```

The diagram above shows the flow from high‑level planning (AgentEngine) through provider interaction, sandboxed execution (KernelManager), and artifact persistence (MemoryStore).
