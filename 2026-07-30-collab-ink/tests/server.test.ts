import { Server } from "http";
import WebSocket, { WebSocketServer } from "ws";
import { randomUUID } from "crypto";
import { jest } from "@jest/globals";

import { WhiteboardServer } from "../src/server";
import { SessionManager } from "../src/session";
import { AuthMiddleware, AuthError } from "../src/auth";
import {
  User,
  SessionId,
  LLMResponse,
  LLMRequest,
  Stroke,
  StrokeId,
} from "../src/types";

describe("WhiteboardServer", () => {
  let server: WhiteboardServer;
  const port = 0; // let OS assign a free port
  const authConfig = { authBaseUrl: "http://localhost:9999" };

  beforeAll(() => {
    server = new WhiteboardServer(port, authConfig);
  });

  afterAll(() => {
    // Close underlying HTTP server
    (server as any).httpServer.close();
  });

  test("health endpoint returns ok", async () => {
    const res = await fetch(`http://localhost:${(server as any).httpServer.address().port}/health`);
    const json = await res.json();
    expect(json).toEqual({ status: "ok" });
  });
});
