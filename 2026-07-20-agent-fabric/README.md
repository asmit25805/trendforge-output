# Agent Fabric

## Overview
Agent Fabric is a lightweight, plugin‑first IDE that lets developers design, version‑control, and live‑debug LLM agents with deterministic trace replay. The core runtime loads an `AgentConfig`, resolves skill definitions, streams trace events through a back‑pressure‑aware RPC channel, persists them in SQLite, and optionally forwards telemetry to PostHog.

## Features
- **Plugin‑first architecture** – skills are discovered from the `.agents/skills` directory and lazy‑loaded only when needed.
- **Deterministic trace replay** – every `TraceEvent` is stored in a local SQLite DB, enabling offline analysis and step‑by‑step debugging.
- **Custom binary RPC** – a high‑throughput, back‑pressure‑aware channel for communication between the agent runtime and UI.
- **Telemetry & analytics** – optional integration with PostHog for usage analytics.

## Installation
```bash
npm install agent-fabric
```

## Quick Start
```ts
import { AgentEngine } from "./src/core/engine";
import { SkillRegistry } from "./src/core/skillRegistry";
import { RPCChannel } from "./src/rpc/channel";
import { Analytics } from "./src/analytics";
import { TraceStore } from "./src/core/traceStore";
import { AgentConfig } from "./src/types";

const config: AgentConfig = {
  name: "simple-agent",
  skills: ["exampleSkill"],
};

const skillRegistry = new SkillRegistry();
const rpcChannel = new RPCChannel();
const analytics = new Analytics();
const traceStore = new TraceStore();

const engine = new AgentEngine(config, skillRegistry, rpcChannel, analytics, traceStore);
engine.run();
```

## API Reference
### Core
- **`AgentEngine`** – orchestrates the execution of an agent based on an `AgentConfig`.
- **`runAgent(config: AgentConfig): Promise<void>`** – convenience helper that creates an `AgentEngine` and starts it.
- **`SkillRegistry`** – discovers, validates, and lazily loads skill modules.
- **`TraceStore`** – in‑memory store for `TraceEvent` objects (used by the example implementation; a SQLite‑backed version can be swapped in).
- **`RPCChannel`** – event‑emitter based channel that transports `RPCMessage` objects between the runtime and UI.
- **`Analytics`** – captures telemetry events and forwards them to PostHog when configured.

### Types (`src/types.ts`)
- `AgentConfig`
- `SkillDefinition`
- `SkillInfo`
- `TraceEvent`
- `TelemetryRecord`
- `RPCMessage` / `RPCMessageType`
- `RunRequestPayload`
- `AnalyticsEvent`
- `COMMON_PROPERTIES`

## Architecture
```
+-------------------+        +-------------------+        +-------------------+
|   Agent Engine   | <----> |   RPC Channel    | <----> |   UI (React)     |
+-------------------+        +-------------------+        +-------------------+
        |                               |
        v                               v
+-------------------+        +-------------------+
|  Skill Registry   |        |   Trace Store    |
+-------------------+        +-------------------+
        |
        v
+-------------------+
|   Analytics      |
+-------------------+
```

The engine loads the configuration, asks the `SkillRegistry` for the required skills, and executes them while emitting `TraceEvent`s to the `TraceStore`. Those events are also sent over the `RPCChannel` to the UI, which renders them in real time. Telemetry is captured by `Analytics` and optionally sent to an external service.

## Contributing
Contributions are welcome! Please open an issue or submit a pull request.
