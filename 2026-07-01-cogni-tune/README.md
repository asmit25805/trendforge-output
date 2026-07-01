# Cogni‑Tune

## Overview
Cogni‑Tune is a cloud‑config optimizer written in Rust. It consumes raw telemetry from distributed services, clusters noisy patterns into incidents, and drives large language‑model agents to propose self‑healing configuration changes. The system is built for high‑throughput environments where sub‑millisecond latency and strong type safety are mandatory.

## Features
- **High‑volume telemetry ingestion** – back‑pressure aware buffering writes to ClickHouse.
- **Incident detection** – similarity‑based clustering produces deterministic incident signatures.
- **Model Context Protocol (MCP)** – streams JSON‑RPC calls to external agents.
- **Version‑controlled configuration store** – PostgreSQL + Diesel ORM tracks proposals and agent memories.

## Installation
```bash
cargo add cogni-tune
```

## Usage
```rust
use cogni_tune::engine::{TelemetryIngestor, IncidentGrouper, AgentOrchestrator};
use cogni_tune::mcp::server::McpServer;
use cogni_tune::services::telemetry::{store_event, TelemetryEvent, Source};
use cogni_tune::services::config_store::{ConfigStore, AgentMemory, MemoryKind};

// Initialize components, ingest telemetry, and run the MCP server.
```

## API Reference
### Engine
- **TelemetryIngestor** – Handles ingestion of `TelemetryEvent` objects and forwards them to the storage layer.
- **IncidentGrouper** – Groups related telemetry into `Incident` structures based on similarity metrics.
- **AgentOrchestrator** – Coordinates LLM‑powered agents via the MCP server to generate `ConfigChangeProposal` objects.

### MCP Server
- **McpServer** – Exposes a JSON‑RPC endpoint for agents to receive proposals and send back results.
- **rpc_method** – Helper to register RPC methods with the server.

### Services
- **Telemetry Service** (`src/services/telemetry.rs`)
  - `store_event(event: TelemetryEvent) -> Result<()>` – Persists a telemetry event.
  - `query_events(...)` – Retrieves events based on filters.
- **Config Store Service** (`src/services/config_store.rs`)
  - `get_current() -> Result<Config>` – Retrieves the current configuration.
  - `save_memory(memory: AgentMemory) -> Result<()>` – Persists an agent memory.
  - `list_memories(kind: MemoryKind) -> Result<Vec<AgentMemory>>` – Lists stored memories.

### Auth Middleware
- **AuthMiddleware** – Validates `UserToken` JWTs on incoming HTTP requests.
- **resolve_token** – Extracts and verifies the token from the `Authorization` header.

## Architecture
```
+-------------------+      +-------------------+      +-------------------+
| Telemetry Ingest | ---> | Incident Grouper  | ---> | Agent Orchestrator |
+-------------------+      +-------------------+      +-------------------+
        |                           |                         |
        v                           v                         v
+-------------------+      +-------------------+      +-------------------+
| ClickHouse Store |      | In‑memory Cache   |      | MCP Server (JSON‑RPC) |
+-------------------+      +-------------------+      +-------------------+
        |                                                   |
        v                                                   v
+-------------------+                               +-------------------+
| Config Store (PG) | <-----------------------------| LLM Agents        |
+-------------------+                               +-------------------+
```
The diagram illustrates the flow of telemetry data from ingestion through incident detection to agent orchestration, with persistent storage in ClickHouse and PostgreSQL.

## Contributing
Contributions are welcome! Please open issues or pull requests on the GitHub repository.

## License
This project is licensed under the MIT License. See the `LICENSE` file for details.