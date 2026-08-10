# Overview

`review-sync` provides a secure, offline‑first workflow for reviewing HTML documents. Human reviewers add inline comments and edits in a sandboxed browser UI while a local pollable server streams batched feedback to AI agents. The design isolates the artifact in a separate loopback origin, uses per‑session tokens for CSRF protection, and avoids WebSocket dependencies to stay usable behind restrictive firewalls.

## Features

- **Zero‑install CLI** – `review-sync` runs as a single executable script.
- **Sandboxed UI** – The reviewed artifact loads in an iframe on a dedicated loopback hostname, preventing accidental script access.
- **Robust anchoring** – `AnchorResolver` stores prefix/quote/suffix context, surviving whitespace and formatting changes.
- **Batch polling** – A lightweight polling mechanism lets AI agents retrieve comment batches without needing persistent connections.

## Installation

```bash
npm install review-sync
```

## Usage

```bash
# Start the review server
review-sync start

# Open the UI (the command prints a URL you can open in a browser)
review-sync open
```

## API Reference

The server exposes a small REST‑style API. All endpoints return JSON and use standard HTTP status codes.

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/info` | Returns basic server information (`ServerInfo`). |
| `POST` | `/batch` | Accepts a batch of comments/edits (`ReviewBatch`). |
| `GET` | `/batch/:id` | Retrieves the status of a previously submitted batch. |
| `GET` | `/anchor/:id` | Resolves an anchor to its current text location. |

All request bodies must conform to the TypeScript interfaces defined in `src/types.ts`.

## Architecture

```
+-------------------+        +-------------------+
|   Review Server  |<------>|   UI Renderer     |
| (Express + HTTP) |        | (CommentEngine)   |
+-------------------+        +-------------------+
        |                               |
        |  REST API (JSON)               |
        v                               v
+-------------------+        +-------------------+
|   CLI (Commander) |        |   AnchorResolver |
+-------------------+        +-------------------+
```

- **ReviewServer** – Manages the Express HTTP server, stores session state, and writes a lock file with connection details.
- **CLI** – Provides commands (`start`, `stop`, `open`) that interact with the server.
- **CommentEngine** – Handles creation, storage, and retrieval of comments and edits.
- **AnchorResolver** – Generates and resolves anchors that survive document changes.
- **API Router** – Routes incoming HTTP requests to the appropriate handlers.

## Contributing

Contributions are welcome! Please open issues or pull requests on the GitHub repository:

https://github.com/asmit25805/review-sync
