# collab-ink

**collab-ink** is a web‑first real‑time collaborative whiteboard that streams vector strokes to large language model (LLM) back‑ends via a low‑latency WebSocket API. Multiple participants can draw simultaneously, and the system batches and simplifies strokes before invoking an LLM to generate contextual annotations, code snippets, or explanations linked to the originating strokes.

## Features

- Real‑time collaborative drawing with per‑stroke vector data.
- Secure WebSocket connections protected by JWT authentication.
- Session management with automatic persistence and versioned stroke history.
- Stroke processing pipeline that debounces, simplifies, and batches strokes.
- Provider‑agnostic LLM integration supporting OpenAI, Anthropic, Claude, etc.
- Rate‑limited LLM calls with exponential back‑off retries.

## Installation

```bash
npm install collab-ink
```

## Quick Start

```ts
import { WhiteboardServer } from "collab-ink/src/server";
import { AuthMiddleware } from "collab-ink/src/auth";

const server = new WhiteboardServer(3000, { authBaseUrl: "https://auth.mycompany.com" });
```

The server will start on port 3000 and expose:

- `GET /health` – health‑check endpoint.
- WebSocket endpoint at the same host for real‑time communication.

## Architecture

```
+-------------------+      +-------------------+      +-------------------+
|   Client (Web)   | ---> |   WhiteboardServer| ---> |   LLM Provider    |
|  (WebSocket)     |      |  (Node.js)        |      | (OpenAI, etc.)    |
+-------------------+      +-------------------+      +-------------------+
        |                         |                         |
        |   1. Auth (JWT)         |   2. Batch strokes      |   3. Generate answer
        |------------------------>|------------------------>|-------------------->
```

- **Client** connects via WebSocket, sends strokes and receives LLM annotations.
- **WhiteboardServer** validates JWTs, manages sessions, batches strokes, and forwards them to the configured LLM provider.
- **LLM Provider** processes the request and returns a textual response that is broadcast back to participants.

## API Reference

### Server
- `new WhiteboardServer(port: number, authConfig: { authBaseUrl: string })`
  - Starts the HTTP and WebSocket server.
- `createApp(authConfig)` – Returns an Express app with authentication middleware attached (useful for integration tests).

### SessionManager
- `getOrCreateSession(sessionId?: SessionId): Session`
- `addStroke(sessionId: SessionId, stroke: Stroke): Promise<void>`

### StrokeProcessor
- `addStroke(stroke: Stroke): void`
  - Batches strokes according to the configured `maxBatchSize` and `maxBatchMs`.
- Emits `"llmResponse"` with an `LLMResponse` when the LLM returns a result.

### LLMProxy
- `sendRequest(request: LLMRequest): Promise<LLMResponse>`
  - Handles rate‑limiting and retries.
- `ProviderEnum` – Supported providers (`OpenAI`, `Anthropic`, `Claude`).

### AuthMiddleware
- `middleware(req, res, next)` – Express middleware that validates JWTs.
- Throws `AuthError` on failure.

## Contributing

Contributions are welcome! Please open issues or submit pull requests on the GitHub repository:

https://github.com/asmit25805/collab-ink

## License

This project is licensed under the MIT License.
