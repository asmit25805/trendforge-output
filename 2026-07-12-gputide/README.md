# gputide

## Overview

gputide turns any GPU‑equipped machine into a secure, rate‑limited, OpenAI‑compatible inference tunnel. Clients connect via a single WebSocket, authenticate with an API key, and stream chat or completion requests. The system balances load across multiple GPU workers, enforces per‑key quotas, and exposes Prometheus metrics for observability.

## Features
- **GPU multiplexing** – multiple concurrent inference streams per node, respecting configurable capacity.
- **OpenAI‑compatible API** – identical request/response schema, streaming support, and error codes.
- **Pluggable authentication** – file, SQLite, or external OAuth backends via `AuthProvider`.
- **Quota enforcement** – token usage deducted per request, with graceful 429 handling.
- **Observability** – Prometheus metrics for jobs, latency, and quota usage.

## Installation

```bash
pip install gputide
```

## Quick Start

```bash
# Clone the repository
git clone https://github.com/asmit25805/gputide.git
cd gputide

# Install dependencies
pip install -r requirements.txt

# Run the server (example uses the built‑in SQLite auth backend)
python -m gputide.server
```

The server will start on ``http://0.0.0.0:8000`` and expose Prometheus metrics on ``http://0.0.0.0:8001``.

## Architecture

```
+-------------------+          +-------------------+          +-------------------+
|   Client (WebSocket)  | <----> |   Scheduler (FastAPI) | <----> |   WorkerNode (GPU) |
+-------------------+          +-------------------+          +-------------------+
        |                               |                               |
        |                               |                               |
        v                               v                               v
+-------------------+          +-------------------+          +-------------------+
| AuthProvider (SQLite) |   | MetricsCollector (Prometheus) |
+-------------------+          +-------------------+
```

- **Client** connects via WebSocket, sends an authentication message containing an API key, then streams job requests.
- **Scheduler** validates the key using ``AuthProvider``, deducts quota, selects an available ``WorkerNode`` and forwards the request.
- **WorkerNode** performs the inference (simulated in the reference implementation) and returns the result.
- **MetricsCollector** records job counts, latency, and quota usage, exposing them for Prometheus.

## API Reference

### WebSocket Endpoint
- **URL**: ``ws://<host>:<port>/ws``
- **Authentication Message** (must be the first message):
  ```json
  {"type": "auth", "api_key": "YOUR_API_KEY"}
  ```
- **Job Message**:
  ```json
  {
    "type": "job",
    "request_id": "unique-id",
    "payload": {"prompt": "Hello, world!", "max_tokens": 50}
  }
  ```
- **Result Message** (sent by the server):
  ```json
  {
    "type": "result",
    "request_id": "unique-id",
    "result": {"choices": [{"text": "..."}]}
  }
  ```
- **Error Message**:
  ```json
  {"type": "error", "error": "description of the problem"}
  ```

### Authentication Backend
The default backend uses a SQLite database with a table ``api_keys``:
```sql
CREATE TABLE api_keys (
    key TEXT PRIMARY KEY,
    quota INTEGER NOT NULL,
    revoked INTEGER NOT NULL CHECK (revoked IN (0,1))
);
```
Insert a test key with a quota of 1000 tokens:
```sql
INSERT INTO api_keys (key, quota, revoked) VALUES ('test-key', 1000, 0);
```

## Examples

- **Example client** – see ``examples/example_client.py`` for a minimal WebSocket client that authenticates and sends a job.
- **Running with custom auth** – instantiate ``AuthProvider`` with your own backend and pass it to ``run_server``.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository:
https://github.com/asmit25805/gputide

## License

This project is licensed under the MIT License.
