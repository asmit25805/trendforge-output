# collab-orbit

## Overview

collab-orbit is a pluggable command‑line interface and runtime that enables collaborative AI workspaces. It isolates memory, files, and execution sandboxes per user, per channel, and per organization, allowing teams to share context while preserving privacy.

## Features

- Zero‑dependency CLI parser for minimal binary size.
- Deterministic `ScopeKey` generation guarantees consistent storage locations across processes.
- Plugin‑first deployment providers (Fly, AWS, Docker, and future extensions).
- Streaming LLM responses with token‑level forwarding.
- TTL‑based memory janitor to prune stale context automatically.
- Typed error hierarchy for robust error handling.

## Installation

```bash
npm install collab-orbit
```

## Quick Start

```ts
import { CommandRouter } from "collab-orbit/src/cli/router";
import { ProviderRegistry } from "collab-orbit/src/providers/registry";
import { WorkspaceManager } from "collab-orbit/src/core/workspace";
import { AgentExecutor } from "collab-orbit/src/engine/agent_executor";

// Create a router and register a simple command
const router = new CommandRouter();
router.register("hello", async (cmd) => {
  console.log("Hello", cmd.args.join(" "));
});

// Parse a command line (example)
const parsed = { command: "hello", args: ["world"], flags: {}, raw: process.argv };
router.route(parsed);
```

## API Reference

### `CommandRouter`
- **register(command: string, handler: CommandHandler): void** – Register a handler for a command.
- **route(cmd: ParsedCommand): Promise<unknown>** – Execute the appropriate handler.

### `ProviderRegistry`
- **register(provider: DeployProvider): void** – Add a deployment provider.
- **get(id: string): DeployProvider** – Retrieve a provider by its identifier.
- **deploy(id: string, config: DeployConfig): Promise<void>** – Deploy using the specified provider with retry logic.

### `WorkspaceManager`
- **getOrCreate(config: WorkspaceConfig): Workspace** – Retrieve an existing workspace or create a new one.
- **generateScopeKey(id: string): ScopeKey** – Deterministic hash used for scoping resources.

### `AgentExecutor`
- **run(input: AgentInput): Promise<AgentResult>** – Execute an agent within a workspace.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   CommandRouter  | ---> | ProviderRegistry | ---> | WorkspaceManager |
+-------------------+      +-------------------+      +-------------------+
        |                         |                         |
        v                         v                         v
+-------------------+   +-------------------+   +-------------------+
|   AgentExecutor  |   |   DeployProvider  |   |   MemoryStore /   |
+-------------------+   +-------------------+   |   FileStore       |
                                                    +-------------------+
```

The diagram illustrates the flow from CLI parsing, through provider selection, to workspace‑scoped execution.

## Contributing

Contributions are welcome! Please open issues or submit pull requests.
