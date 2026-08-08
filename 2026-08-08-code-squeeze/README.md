# code-squeeze

## Overview
code-squeeze is a plug‑and‑play HTTP proxy that sits between an IDE assistant and a large language model (LLM). It trims the context sent to the LLM by applying static‑analysis‑aware compression, dramatically reducing token usage while preserving the developer’s intent.

## Features
- **Deterministic compression** – a lint step guarantees reproducible token counts across runs.
- **Cache‑driven** – identical input signatures are served from a local SQLite cache, eliminating redundant LLM calls.
- **Provider‑agnostic** – OpenAI, Azure, and Ollama back‑ends are supported through a pluggable client interface.
- **Rate‑limit aware** – the proxy respects provider rate limits and backs off automatically.

## Installation
```bash
pip install code-squeeze
```

## Usage
```python
from src.core.models import Config, Segment
from src.api.server import ProxyServer

config = Config()
server = ProxyServer(config)
server.run()
```

## API Reference
### POST `/compress`
Accepts a JSON array of `Segment` objects and returns a JSON array of `CompressionResult` objects.

- **Request body**
```json
[
  {
    "path": "example.py",
    "content": "def foo():\n    pass",
    "start_line": 0,
    "end_line": 2
  }
]
```
- **Response**
```json
[
  {
    "compressed": "def foo():\n    pass",
    "original_length": 27,
    "compressed_length": 27
  }
]
```

## Architecture
The system is composed of three primary components:

1. **ProxyServer** – a FastAPI application exposing the `/compress` endpoint.
2. **CompressionEngine** – performs deterministic compression and caches results in a local SQLite database.
3. **LLMClient** – a pluggable client that forwards compressed code to the configured LLM provider (OpenAI, Azure, Ollama, etc.).

These components work together to provide fast, repeatable, and cost‑effective code compression for LLM‑driven IDE assistants.
