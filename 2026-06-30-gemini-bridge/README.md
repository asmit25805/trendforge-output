# Gemini Bridge

## Overview
Gemini Bridge is a zero‑cost gateway that exposes a unified OpenAI‑compatible, Google‑compatible, and Anthropic‑compatible API. It runs as a single Cloudflare Worker script or as a Docker container, translating incoming chat requests into Gemini Web calls and streaming responses back in the OpenAI format.

## Features
- **Unified API** – One endpoint works for OpenAI, Google Gemini, and Anthropic clients.
- **Streaming support** – Server‑Sent Events (SSE) are coalesced to produce well‑formed OpenAI‑style chunks.
- **Dual transport** – Uses the Fetch API by default and falls back to raw sockets for large payloads or rate‑limited scenarios.
- **Cache‑first token handling** – Gemini auth token is cached with TTL to reduce latency.
- **Health check** – `/health` endpoint.

## Installation
```bash
npm install gemini-bridge
```

## Quick Start
```ts
import http from "node:http";
import { handleRequest } from "gemini-bridge/src/server";

const server = http.createServer((req, res) => {
  handleRequest(req, res).catch(err => {
    res.writeHead(err.status || 500, { "Content-Type": "application/json" });
    res.end(JSON.stringify(err.body ?? { error: "Internal Server Error" }));
  });
});

server.listen(8080, () => console.log("Gemini Bridge listening on port 8080"));
```

## Architecture
```
+----------------+      +----------------+      +-------------------+
|   Client API   | ---> | RequestRouter  | ---> | GeminiAdapter     |
+----------------+      +----------------+      +-------------------+
                                 |                     |
                                 v                     v
                        +----------------+   +-------------------+
                        | TransportLayer|   | StreamProcessor   |
                        +----------------+   +-------------------+
                                 |                     |
                                 v                     v
                        +----------------+   +-------------------+
                        |   Gemini API   |   |   OpenAI SSE      |
                        +----------------+   +-------------------+
```
The diagram shows the flow from an incoming OpenAI‑style request, through the router, into the GeminiAdapter which selects an appropriate TransportLayer (FetchTransport or SocketTransport). Responses are streamed back via the StreamProcessor, which converts Gemini SSE into OpenAI‑compatible chunks.

## API Reference
### `handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void>`
Entry point for HTTP servers. It parses the incoming request, validates it against the `NormalizedRequestSchema`, forwards it to the `GeminiAdapter`, and streams the response back to the client.

### `RequestRouter`
- `route(request: NormalizedRequest): Promise<ApiResponse>` – Validates and forwards the request to the appropriate adapter.

### `GeminiAdapter`
- `call(request: NormalizedRequest): Promise<ApiResponse>` – Converts a normalized request into a Gemini payload, sends it via a transport, and returns an OpenAI‑compatible response.

### `FetchTransport`
- `send(payload: GeminiPayload): Promise<GeminiResponse>` – Uses the global `fetch` API with retry logic.

### `SocketTransport`
- `send(payload: GeminiPayload): Promise<GeminiResponse>` – Uses raw TCP/TLS sockets for large payloads or when fetch fails.

### `StreamProcessor`
- `process(stream: ReadableStream<Uint8Array>): AsyncGenerator<ApiChunk>` – Transforms Gemini SSE into OpenAI‑compatible SSE chunks.

### `CacheManager`
- `getToken(): Promise<string>` – Retrieves a cached Gemini auth token, refreshing it when necessary.

## Contributing
Contributions are welcome! Please open issues or pull requests on the GitHub repository.
