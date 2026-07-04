# pipeline-pilot

## Overview

`pipeline-pilot` is a terminal‑native orchestrator that lets large language models drive data pipelines with deterministic, byte‑stable prompts. It guarantees cheap context usage by keeping the system prompt unchanged across runs and isolates sub‑tasks in fresh sessions so the parent context never balloons.

## Features

- **Stable system prompt** – pre‑computed byte‑stable header for cheap cache reuse.
- **Sub‑agent isolation** – each delegated sub‑task runs in its own `Session`, preventing context bloat.
- **Append‑only memory store** – title‑based deduplication, deterministic upserts.

## Installation

```bash
pip install pipeline-pilot
```

## Quick Start

```python
from src.core.engine import SessionManager, Session
from src.core.models import Message
from src.tool.engine import ToolEngine

# Create a session manager
manager = SessionManager()
session = Session(manager)

# Add a user message
session.add_message(Message(role="user", content="Summarize the latest sales data"))

# Run the session (this will invoke the tool engine internally)
response = session.run()
print(response.content)
```

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   SessionManager  | ---> |      Session      | ---> |   ToolEngine      |
+-------------------+      +-------------------+      +-------------------+
        |                           |                         |
        v                           v                         v
+-------------------+      +-------------------+      +-------------------+
| UnifiedReflector | <--- |   MemoryStore    | <--- |   External Tools |
+-------------------+      +-------------------+      +-------------------+
```

- **SessionManager** creates and tracks `Session` objects.
- **Session** holds the turn‑by‑turn conversation, invokes the `ToolEngine`, and stores results.
- **UnifiedReflector** extracts reflections from the conversation and writes them to the `MemoryStore`.
- **MemoryStore** provides an append‑only, title‑based deduplication store for reflections.
- **ToolEngine** safely runs external commands or API calls and returns structured `ToolResult` objects.

## API Reference

### Core Models (`src.core.models`)
- **Message** – Represents a single chat message.
- **MemoryEntry** – Represents a stored reflection or memory.
- **ToolResult** – Result returned by a tool execution.
- **ReflectResult** – Result returned by the reflector.

### Engine (`src.core.engine`)
- **SessionManager** – Manages sessions and provides a deterministic system prompt.
- **Session** – Represents an isolated conversation session.

### Sub‑Agent (`src.agent.subagent`)
- **SubAgent** – Runs an isolated sub‑task in its own `Session`.

### Memory Store (`src.memory.store`)
- **MemoryStore** – Append‑only store for `MemoryEntry` objects.
- **_sanitize_filename** – Utility to create safe filenames from titles.

### Reflector (`src.reflector.unified`)
- **UnifiedReflector** – Generates reflections from a list of messages.

### Tool Engine (`src.tool.engine`)
- **ToolEngine** – Executes external tools safely and returns `ToolResult`.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.
