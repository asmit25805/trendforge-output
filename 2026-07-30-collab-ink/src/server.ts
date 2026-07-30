import express, { Request, Response, NextFunction } from "express";
import http from "http";
import { WebSocketServer, WebSocket } from "ws";
import { EventEmitter } from "events";

import {
  SessionId,
  Stroke,
  User,
  LLMRequest,
  LLMResponse,
  RETRY_LIMIT,
  exponentialBackoff,
} from "./types";

import { SessionManager } from "./session";
import { StrokeProcessor } from "./strokeProcessor";
import { LLMProxy } from "./llmProxy";
import { AuthMiddleware, AuthError } from "./auth";

/**
 * Core Whiteboard server exposing HTTP and WebSocket endpoints.
 */
export class WhiteboardServer extends EventEmitter {
  private app = express();
  private httpServer: http.Server;
  private wss: WebSocketServer;
  private sessionManager: SessionManager;
  private strokeProcessor: StrokeProcessor;
  private llmProxy: LLMProxy;
  private auth: AuthMiddleware;

  constructor(port: number, authConfig: { authBaseUrl: string }) {
    super();
    this.sessionManager = new SessionManager();
    this.strokeProcessor = new StrokeProcessor();
    this.llmProxy = new LLMProxy();
    this.auth = new AuthMiddleware(authConfig);

    this.app.use(express.json());
    this.app.use(this.auth.middleware.bind(this.auth));

    // Simple health‑check endpoint
    this.app.get("/health", (_req, res) => res.json({ status: "ok" }));

    this.httpServer = http.createServer(this.app);
    this.wss = new WebSocketServer({ server: this.httpServer });
    this.wss.on("connection", this.handleWsConnection.bind(this));

    this.httpServer.listen(port, () => {
      console.log(`Whiteboard server listening on port ${port}`);
    });
  }

  private async handleWsConnection(ws: WebSocket, req: Request) {
    try {
      const user = (req as any).user as User; // populated by AuthMiddleware
      if (!user) throw new AuthError("Unauthenticated websocket connection");

      ws.on("message", async (data) => {
        const msg = JSON.parse(data.toString());
        if (msg.type === "join") {
          const sessionId: SessionId = msg.sessionId;
          const session = this.sessionManager.getOrCreateSession(sessionId);
          session.participants.set(user.id, user);
          ws.send(JSON.stringify({ type: "joined", sessionId }));
        } else if (msg.type === "stroke") {
          const stroke: Stroke = { ...msg.stroke, userId: user.id };
          this.strokeProcessor.addStroke(stroke);
          // Broadcast to other participants
          this.wss.clients.forEach((client) => {
            if (client !== ws && client.readyState === WebSocket.OPEN) {
              client.send(JSON.stringify({ type: "stroke", stroke }));
            }
          });
        }
      });
    } catch (err) {
      ws.close(1011, (err as Error).message);
    }
  }
}

/**
 * Helper to create an Express app with all middleware wired – useful for testing.
 */
export function createApp(authConfig: { authBaseUrl: string }) {
  const app = express();
  const auth = new AuthMiddleware(authConfig);
  app.use(express.json());
  app.use(auth.middleware.bind(auth));
  app.get("/health", (_req, res) => res.json({ status: "ok" }));
  return app;
}
