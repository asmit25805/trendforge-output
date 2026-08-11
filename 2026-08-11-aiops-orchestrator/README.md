# aiops-orchestrator

## Overview
aiops-orchestrator is a self‑hosted, cryptographically‑verified platform that turns LLM agents into plug‑and‑play micro‑services for DevOps automation. It provides a secure plugin system, a persistent cron scheduler, and an event‑driven engine that can be extended with custom agents and plugins.

## Features
- **Secure plugin loading** – plugins are signed with RSA‑SHA256 manifests, guaranteeing supply‑chain integrity.
- **Persistent cron scheduler** – SQLite‑backed cron jobs give exact‑once execution guarantees across restarts.
- **Event bus** – decoupled publish/subscribe mechanism lets plugins react to system events without tight coupling.
- **Agent abstraction** – high‑level agents are defined declaratively and can swap LLM providers.

## Installation
```bash
pip install aiops-orchestrator
```

## Usage
```bash
aiops-orchestrator path/to/config.json
```

## API Reference
- `src.core.engine.Engine` – main orchestrator class.
- `src.plugins.manager.PluginManager` – loads and verifies plugins.
- `src.scheduler.cron.Scheduler` – runs persistent cron jobs.
- `src.core.models.Event` and `EventBus` – event system.

## Architecture
The system consists of three core components:

1. **Engine** – coordinates plugins, scheduler, and event bus.
2. **PluginManager** – verifies and loads plugins using RSA signatures.
3. **Scheduler** – stores cron definitions in SQLite and ensures jobs run exactly once.

These components interact via the `EventBus`, enabling loose coupling and extensibility.
