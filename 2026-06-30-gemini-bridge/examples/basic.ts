import http from "node:http";
import { URL } from "node:url";
import { Readable } from "node:stream";
import { handleRequest } from "../src/server";

/**
 * Starts an HTTP server that forwards incoming requests to the Gemini Bridge
 * request handler. The server runs on the specified port and logs basic
 * diagnostics.
 *
 * @param port - TCP port to listen on.
 * @returns A promise that resolves when the server is ready.
 */
async function startServer(port: number): Promise<http.Server> {
  const server = http.createServer(async (nodeReq, nodeRes) => {
    const requestUrl = new URL(nodeReq.url ?? "/", `http://localhost:${port}`);
    const request = new Request(requestUrl.toString(), {
      method: nodeReq.method ?? "GET",
      headers: nodeReq.headers as HeadersInit,
      // Node's IncomingMessage implements a readable stream compatible with the
      // WHATWG Request body interface.
      body: nodeReq as unknown as ReadableStream<Uint8Array>,
      // The abort signal is optional; we omit it for simplicity.
    });

    try {
      const response = await handleRequest(request);
      // Forward status and headers.
      nodeRes.writeHead(response.status, Object.fromEntries(response.headers.entries()));
      // Stream the response body if present.
      if (response.body) {
        const reader = response.body.getReader();
        const encoder = new TextEncoder();
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          nodeRes.write(encoder.encode(value));
        }
      }
      nodeRes.end();
    } catch (err) {
      const errorPayload = { error: { code: "internal_error", message: "internal server error" } };
      nodeRes.writeHead(500, { "Content-Type": "application/json" });
      nodeRes.end(JSON.stringify(errorPayload));
    }
  });

  return new Promise((resolve) => {
    server.listen(port, () => {
      console.log(`🚀 Gemini Bridge example server listening at http://localhost:${port}`);
      resolve(server);
    });
  });
}

/**
 * Performs a single OpenAI‑compatible request against the local gateway.
 *
 * @param port - Port where the example server is listening.
 * @returns The parsed JSON response.
 */
async function makeOpenAIRequest(port: number): Promise<unknown> {
  const resp = await fetch(`http://localhost:${port}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "gemini-1.5-pro",
      messages: [{ role: "user", content: "What is the capital of France?" }],
      temperature: 0.7,
      stream: false,
    }),
  });

  if (!resp.ok) {
    const err = await resp.json();
    throw new Error(`OpenAI request failed: ${JSON.stringify(err)}`);
  }

  return resp.json();
}

/**
 * Demonstrates a streaming request. The function logs each SSE chunk as it
 * arrives, then resolves when the stream ends.
 *
 * @param port - Port where the example server is listening.
 */
async function makeStreamingRequest(port: number): Promise<void> {
  const resp = await fetch(`http://localhost:${port}/v1/chat/completions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      model: "gemini-1.5-pro",
      messages: [{ role: "user", content: "Tell me a short joke." }],
      temperature: 0.5,
      stream: true,
    }),
  });

  if (!resp.ok || !resp.body) {
    const err = await resp.json().catch(() => ({}));
    throw new Error(`Streaming request failed: ${JSON.stringify(err)}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();

  console.log("📡 Streaming response:");
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    const chunk = decoder.decode(value, { stream: true });
    // Gemini Bridge emits OpenAI‑compatible SSE lines prefixed with "data:".
    for (const line of chunk.split("\n")) {
      if (line.startsWith("data:")) {
        const payload = line.slice(5).trim();
        if (payload === "[DONE]") {
          console.log("🔚 Stream finished");
          return;
        }
        try {
          const parsed = JSON.parse(payload);
          console.log("➡️ Chunk:", parsed);
        } catch {
          // Non‑JSON lines are ignored.
        }
      }
    }
  }
}

/**
 * Entry point executed when the script is run directly. It starts the server,
 * performs a regular request, then a streaming request, and finally shuts down.
 */
async function main(): Promise<void> {
  const PORT = 3000;
  const server = await startServer(PORT);

  try {
    const result = await makeOpenAIRequest(PORT);
    console.log("✅ Non‑streaming response:", JSON.stringify(result, null, 2));

    await makeStreamingRequest(PORT);
  } catch (e) {
    console.error("❌ Example error:", e);
  } finally {
    server.close(() => {
      console.log("🛑 Example server stopped");
    });
  }
}

// Run the example when executed as a script.
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch((err) => {
    console.error("Fatal error:", err);
    process.exit(1);
  });
}