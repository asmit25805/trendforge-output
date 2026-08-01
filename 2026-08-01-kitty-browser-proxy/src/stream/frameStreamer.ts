import { Server as WsServer, WebSocket } from "ws";
import { EventEmitter } from "node:events";
import { RenderConfig, RenderConfigSchema, ErrorReport, ErrorReportSchema, FramePacket, FramePacketSchema } from "../types";
import { z } from "zod";

/**
 * Represents a single client connection to the frame streamer.
 */
export type ClientConnection = WebSocket;

/**
 * FrameStreamer encodes PNG buffers into Kitty graphics protocol chunks and
 * broadcasts them to all connected clients.
 */
export class FrameStreamer extends EventEmitter {
  private wss: WsServer;
  private clients: Set<ClientConnection> = new Set();

  constructor(port: number = 0) {
    super();
    this.wss = new WsServer({ port });
    this.wss.on("connection", (ws) => this.handleConnection(ws));
  }

  private handleConnection(ws: ClientConnection) {
    this.clients.add(ws);
    ws.on("close", () => this.clients.delete(ws));
    ws.on("error", (err) => this.emit("error", err));
  }

  /** Broadcast a frame packet to all connected clients. */
  broadcast(frame: FramePacket) {
    const payload = JSON.stringify(frame);
    for (const client of this.clients) {
      if (client.readyState === WebSocket.OPEN) {
        client.send(payload);
      }
    }
  }

  /** Gracefully shut down the WebSocket server. */
  close(): Promise<void> {
    return new Promise((resolve) => {
      this.wss.close(() => resolve());
    });
  }
}
