import { randomUUID } from "crypto";
import WebSocket from "ws";

import { WhiteboardServer } from "../src/server";
import { SessionManager } from "../src/session";
import { AuthMiddleware } from "../src/auth";
import {
  Stroke,
  LLMResponse,
  User,
  SessionId,
} from "../src/types";

/**
 * Minimal runnable example that starts a WhiteboardServer, connects a client,
 * sends a stroke, and logs the resulting LLMResponse annotation.
 */
async function main(): Promise<void> {
  // -------------------------------------------------------------------------
  // 1. Initialise core components
  // -------------------------------------------------------------------------
  const sessionManager = new SessionManager();
  const authMiddleware = new AuthMiddleware({
    authBaseUrl: "http://auth.local",
  });
  const server = new WhiteboardServer(sessionManager, authMiddleware);

  // Start the server on an OS‑assigned port.
  await server.start(0);
  // @ts-expect-error – expose underlying http server for address extraction.
  const httpServer = (server as any).httpServer as import("http").Server;
  const { port } = httpServer.address() as import("net").AddressInfo;

  // -------------------------------------------------------------------------
  // 2. Mock user and authentication token
  // -------------------------------------------------------------------------
  const dummyUser: User = {
    id: randomUUID(),
    name: "Example User",
    scopes: ["read", "write"],
  };
  const dummyJwt = "dummy.jwt.token";

  // -------------------------------------------------------------------------
  // 3. Create a session owned by the dummy user
  // -------------------------------------------------------------------------
  const session = sessionManager.createSession(dummyUser.id);
  const sessionId: SessionId = session.id;

  // -------------------------------------------------------------------------
  // 4. Connect a WebSocket client and perform the handshake
  // -------------------------------------------------------------------------
  const ws = new WebSocket(`ws://localhost:${port}`);

  await new Promise<void>((resolve, reject) => {
    ws.once("open", resolve);
    ws.once("error", reject);
  });

  // Send authentication message expected by the server.
  ws.send(JSON.stringify({ type: "auth", token: dummyJwt }));

  // Wait for the server to acknowledge authentication (optional).
  await new Promise<void>((resolve) => {
    const timeout = setTimeout(resolve, 500);
    ws.once("message", () => clearTimeout(timeout));
  });

  // -------------------------------------------------------------------------
  // 5. Join the session
  // -------------------------------------------------------------------------
  ws.send(JSON.stringify({ type: "join", sessionId }));

  // -------------------------------------------------------------------------
  // 6. Send a single stroke
  // -------------------------------------------------------------------------
  const stroke: Stroke = {
    id: randomUUID(),
    path: [
      [10, 10],
      [20, 30],
      [40, 50],
    ],
    color: "#ff6600",
    width: 3,
    timestamp: Date.now(),
  };

  ws.send(JSON.stringify({ type: "stroke", sessionId, stroke }));

  // -------------------------------------------------------------------------
  // 7. Await the LLMResponse broadcast and log it
  // -------------------------------------------------------------------------
  const llmResponse: LLMResponse = await new Promise<LLMResponse>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("LLMResponse timeout")), 10_000);

    ws.on("message", (data) => {
      try {
        const msg = JSON.parse(data.toString());
        if (msg.type === "llmResponse" && msg.sessionId === sessionId) {
          clearTimeout(timer);
          resolve(msg.payload as LLMResponse);
        }
      } catch {
        // ignore malformed messages
      }
    });
  });

  console.log("Received LLM annotation:", llmResponse.content);

  // -------------------------------------------------------------------------
  // 8. Clean up
  // -------------------------------------------------------------------------
  ws.terminate();
  await server.shutdown();
  await new Promise<void>((resolve) => httpServer.close(() => resolve()));
}

// Execute the example when the file is run directly.
if (require.main === module) {
  main().catch((err) => {
    console.error("Example failed:", err);
    process.exit(1);
  });
}